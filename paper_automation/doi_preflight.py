"""Pre-download DOI validation and title-based rematch."""
from __future__ import annotations

from dataclasses import dataclass

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
) -> tuple[list[dict], list[PreflightChange]]:
    """Validate/correct DOIs in-place for pending rows.

    Returns (rows, changes). Non-pending rows are left untouched.
    """

    metadata_resolver = resolver or MetadataResolver(email=email, timeout=8)
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
            fixed = _validate_or_rematch(
                metadata_resolver,
                doi=old_doi,
                title=title,
                year=year,
                journal=journal,
                min_title_similarity=min_title_similarity,
            )
            if fixed is None:
                continue
            new_doi, detail, meta = fixed
            if new_doi != old_doi or detail.startswith("enriched"):
                _apply_metadata(row, meta, new_doi)
                changes.append(
                    PreflightChange(
                        task_id=task_id,
                        action="rematch" if new_doi != old_doi else "enrich",
                        old_doi=old_doi,
                        new_doi=new_doi,
                        detail=detail,
                    )
                )
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
    resolved_doi = clean_doi(by_doi.doi or "").lower()
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
    new_doi = clean_doi(by_title.doi or "").lower()
    if not new_doi:
        return (resolved_doi, "doi_keep_unverified", by_doi) if resolved_doi else None
    sim = title_similarity(title, by_title.title or "")
    if sim < min_title_similarity and by_title.confidence < 0.65:
        return (resolved_doi, "doi_keep_weak_title_match", by_doi) if resolved_doi else None
    if new_doi != doi:
        return new_doi, f"title_rematch sim={sim:.2f} conf={by_title.confidence:.2f}", by_title
    return new_doi, f"doi_confirmed sim={sim:.2f}", by_title


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
