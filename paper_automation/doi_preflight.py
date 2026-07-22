"""Pre-download DOI validation and title-based rematch."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from doi_batch_utils import clean_doi

from .deduplicator import title_similarity
from .metadata_resolver import MetadataResolver
from .models import PaperCandidate


@dataclass(frozen=True)
class PreflightChange:
    task_id: str
    action: str
    old_doi: str
    new_doi: str
    detail: str


def preflight_rows(
    rows: list[dict],
    *,
    email: str = "",
    min_title_similarity: float = 0.72,
    resolver: MetadataResolver | None = None,
    cache_path: str | Path | None = None,
) -> tuple[list[dict], list[PreflightChange]]:
    """Validate/correct DOIs in-place for pending rows.

    Returns (rows, changes). Non-pending rows are left untouched.
    """

    metadata_resolver = resolver or MetadataResolver(
        email=email,
        timeout=8,
        cache_path=cache_path,
    )
    changes: list[PreflightChange] = []
    for row in rows:
        if str(row.get("status", "")).strip().lower() != "pending":
            continue
        task_id = str(row.get("task_id", "") or "")
        title = str(row.get("title", "") or row.get("input_title", "") or "").strip()
        old_doi = clean_doi(str(row.get("doi", "") or "")).lower()
        year = str(row.get("year", "") or "").strip()
        journal = str(row.get("journal", "") or "").strip()

        if old_doi:
            row["doi"] = old_doi
            if not _has_independent_title(title, old_doi):
                # A DOI-only input is already a bounded identifier.  Do not turn
                # an optional metadata enrichment into a network precondition.
                continue
            fixed = _validate_or_rematch(
                metadata_resolver,
                doi=old_doi,
                title=title,
                year=year,
                journal=journal,
                min_title_similarity=min_title_similarity,
            )
            if fixed is None:
                # Unresolvable DOI: keep for audit, do not download.
                row["status"] = "metadata_uncertain"
                row["reason"] = "doi_unresolvable_preflight"
                changes.append(
                    PreflightChange(
                        task_id=task_id,
                        action="reject",
                        old_doi=old_doi,
                        new_doi="",
                        detail="doi_unresolvable_preflight",
                    )
                )
                continue
            new_doi, detail, meta = fixed
            if detail.startswith("lookup_deferred_"):
                existing = str(row.get("reason", "") or "")
                marker = f"doi_preflight_{detail}"
                row["reason"] = f"{existing};{marker}".strip(";")
                continue
            if title and getattr(meta, "title", None):
                sim = title_similarity(title, str(meta.title or ""))
                if sim < 0.45 and "rematch" not in detail and "title_rematch" not in detail:
                    # Severe title/DOI mismatch without a confident rematch.
                    row["status"] = "metadata_uncertain"
                    row["reason"] = f"doi_title_mismatch_preflight:sim={sim:.2f}"
                    changes.append(
                        PreflightChange(
                            task_id=task_id,
                            action="reject",
                            old_doi=old_doi,
                            new_doi=new_doi,
                            detail=row["reason"],
                        )
                    )
                    continue
            if new_doi != old_doi or detail.startswith("enriched") or detail.startswith("doi_ok"):
                _apply_metadata(row, meta, new_doi)
                if new_doi != old_doi or detail.startswith("enriched"):
                    changes.append(
                        PreflightChange(
                            task_id=task_id,
                            action="rematch" if new_doi != old_doi else "enrich",
                            old_doi=old_doi,
                            new_doi=new_doi,
                            detail=detail,
                        )
                    )
            # Stash OA signal for later bounded recovery (B3.3).
            if _metadata_has_oa_signal(meta):
                existing = str(row.get("reason", "") or "")
                marker = "oa_signal=1"
                if marker not in existing:
                    row["reason"] = f"{existing};{marker}".strip(";") if existing else marker
            continue

        # No DOI: try title/year resolution
        if not title or title.upper().startswith("[SEARCH"):
            continue
        candidate = PaperCandidate(
            source_index=_source_index(row),
            raw_text=f"{title} {year} {journal}".strip(),
            title=title,
            doi="",
        )
        meta = metadata_resolver.resolve_one(candidate)
        new_doi = clean_doi(meta.doi or "").lower()
        if not new_doi:
            continue
        sim = title_similarity(title, meta.title or "") if meta.title else 0.0
        if meta.confidence < 0.55 and sim < min_title_similarity:
            continue
        _apply_metadata(row, meta, new_doi)
        row["status"] = "pending"
        row["reason"] = f"doi_resolved_preflight:conf={meta.confidence:.2f};sim={sim:.2f}"
        changes.append(
            PreflightChange(
                task_id=task_id,
                action="resolve",
                old_doi="",
                new_doi=new_doi,
                detail=f"title_resolve conf={meta.confidence:.2f} sim={sim:.2f}",
            )
        )
    return rows, changes


def _validate_or_rematch(
    resolver: MetadataResolver,
    *,
    doi: str,
    title: str,
    year: str,
    journal: str,
    min_title_similarity: float,
) -> tuple[str, str, object] | None:
    candidate = PaperCandidate(
        source_index=1,
        raw_text=doi,
        title=title,
        doi=doi,
    )
    by_doi = resolver.resolve_one(candidate)
    doi_metadata_found = bool(
        getattr(by_doi, "crossref", None)
        or getattr(by_doi, "openalex", None)
        or getattr(by_doi, "unpaywall", None)
    )
    deferred = _transient_lookup_status(by_doi)
    if deferred and not doi_metadata_found:
        return doi, f"lookup_deferred_{deferred}", by_doi
    resolved_doi = clean_doi(by_doi.doi or "").lower() if doi_metadata_found else ""
    if resolved_doi and (not title or not by_doi.title):
        return resolved_doi, "enriched_from_doi", by_doi
    if resolved_doi and title and by_doi.title:
        sim = title_similarity(title, by_doi.title)
        if sim >= min_title_similarity:
            return resolved_doi, f"doi_ok sim={sim:.2f}", by_doi
        # DOI exists but title mismatch — rematch by title
    if not title:
        if resolved_doi:
            return resolved_doi, "doi_exists_no_title", by_doi
        return None

    title_candidate = PaperCandidate(
        source_index=1,
        raw_text=f"{title} {year} {journal}".strip(),
        title=title,
        doi="",
    )
    by_title = resolver.resolve_one(title_candidate)
    title_metadata_found = bool(
        getattr(by_title, "crossref", None) or getattr(by_title, "openalex", None)
    )
    title_deferred = _transient_lookup_status(by_title)
    if title_deferred and not title_metadata_found and not resolved_doi:
        return doi, f"lookup_deferred_{title_deferred}", by_doi
    new_doi = clean_doi(by_title.doi or "").lower()
    if not new_doi:
        return (resolved_doi, "doi_keep_unverified", by_doi) if resolved_doi else None
    sim = title_similarity(title, by_title.title or "")
    if sim < min_title_similarity and by_title.confidence < 0.65:
        return (resolved_doi, "doi_keep_weak_title_match", by_doi) if resolved_doi else None
    if new_doi != doi:
        return new_doi, f"title_rematch sim={sim:.2f} conf={by_title.confidence:.2f}", by_title
    return new_doi, f"doi_confirmed sim={sim:.2f}", by_title


def _has_independent_title(title: str, doi: str) -> bool:
    value = str(title or "").strip()
    if not value:
        return False
    lowered = value.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi "):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix):].strip()
            break
    return lowered.rstrip(".,; ") != doi.lower()


def _transient_lookup_status(meta: object) -> str:
    outcomes = getattr(meta, "lookup_outcomes", None) or {}
    statuses = [
        str(getattr(outcome, "status", "") or "")
        for outcome in outcomes.values()
    ]
    for status in ("timeout", "rate_limited", "network_error", "invalid_response"):
        if status in statuses:
            return status
    return ""


def _apply_metadata(row: dict, meta: object, doi: str) -> None:
    row["doi"] = doi
    if not str(row.get("input_doi", "") or "").strip():
        row["input_doi"] = doi
    title = str(getattr(meta, "title", "") or "").strip()
    if title:
        row["title"] = title
    authors = getattr(meta, "authors", None) or []
    if authors and not str(row.get("authors", "") or "").strip():
        if isinstance(authors, list):
            row["authors"] = "; ".join(str(item) for item in authors if str(item).strip())
        else:
            row["authors"] = str(authors)
    year = str(getattr(meta, "year", "") or "").strip()
    if year and not str(row.get("year", "") or "").strip():
        row["year"] = year
    journal = str(getattr(meta, "journal", "") or "").strip()
    if journal and not str(row.get("journal", "") or "").strip():
        row["journal"] = journal


def _source_index(row: dict) -> int:
    try:
        return int(str(row.get("source_index", "") or "0"))
    except ValueError:
        return 0


def _metadata_has_oa_signal(meta: object) -> bool:
    openalex = getattr(meta, "openalex", None) or {}
    if isinstance(openalex, dict):
        open_access = openalex.get("open_access") or {}
        if open_access.get("is_oa"):
            return True
        best = openalex.get("best_oa_location") or {}
        if any(str(best.get(key) or "").strip() for key in ("pdf_url", "url_for_pdf")):
            return True
    unpaywall = getattr(meta, "unpaywall", None) or {}
    if isinstance(unpaywall, dict) and unpaywall.get("is_oa"):
        return True
    pdf_candidates = getattr(meta, "pdf_candidates", None) or []
    return bool(pdf_candidates)
