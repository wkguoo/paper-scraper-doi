"""A3: hot-refresh 结果/ inventory — rename orphans, map to failed DOIs, rewrite 下载清单."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from doi_batch_utils import clean_doi, extract_doi_from_text

from .batch_workflow import (
    SUCCESS_STATUSES,
    USER_DELIVERY_DIR_NAME,
    batch_state_lock,
    load_batch_state,
    paths_from_run_dir,
    publish_user_delivery,
    save_batch_state,
)
from .file_manager import clean_title_for_filename, make_pdf_filename, sanitize_filename
from .models import MetadataResult


RENAME_MAP_NAME = "重命名对照表.csv"
RENAME_MAP_FIELDS = [
    "old_name",
    "new_name",
    "doi",
    "year",
    "author",
    "title",
    "status",
    "note",
]


@dataclass(frozen=True)
class DeliveryRefreshResult:
    run_dir: Path
    renamed: int
    mapped_to_row: int
    external_kept: int
    inventory_path: Path
    rename_map_path: Path


def _sha256(path: Path, *, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _year_author_title_name(year: str, author: str, title: str) -> str:
    meta = MetadataResult(
        source_index=0,
        query_title=title or "",
        doi="",
        title=clean_title_for_filename(title) or title or "paper",
        authors=[author] if author else [],
        year=str(year or "0000") or "0000",
    )
    return make_pdf_filename(meta)


def _safe_name(name: str, *, fallback: str) -> str:
    cleaned = sanitize_filename(name) or fallback
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:180] or fallback


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _guess_meta_from_stem(stem: str) -> tuple[str, str, str]:
    """Best-effort year/author/title from an existing delivery-like filename stem."""
    text = clean_title_for_filename(stem) or stem
    text = re.sub(r"[_]+", "-", text)
    m = re.match(r"^(?P<year>(?:19|20)\d{2})-(?P<rest>.+)$", text)
    if not m:
        return "", "", text
    year = m.group("year")
    rest = m.group("rest")
    parts = rest.split("-", 1)
    if len(parts) == 1:
        return year, parts[0], ""
    return year, parts[0], parts[1].replace("-", " ")


def _lookup_crossref(doi: str, *, email: str = "") -> dict[str, str]:
    doi = clean_doi(doi)
    if not doi:
        return {}
    try:
        from .metadata_resolver import MetadataResolver
        from .models import PaperCandidate

        meta = MetadataResolver(email=email).resolve_one(
            PaperCandidate(source_index=0, raw_text=doi, doi=doi, title="")
        )
    except Exception:
        return {}
    if not meta or not (meta.title or meta.year):
        return {}
    author = ""
    if meta.authors:
        first = str(meta.authors[0] or "")
        if "," in first:
            author = first.split(",", 1)[0].strip()
        else:
            author = first.split()[0] if first.split() else first
    return {
        "doi": clean_doi(meta.doi or doi),
        "title": clean_title_for_filename(meta.title or "") or str(meta.title or ""),
        "year": str(meta.year or ""),
        "author": author,
        "authors": " | ".join(meta.authors) if meta.authors else author,
        "journal": str(meta.journal or ""),
    }


def _extract_doi_from_pdf_bytes(data: bytes) -> str:
    """Cheap binary scan for a DOI-looking string (no full PDF parser)."""
    # Prefer ASCII-ish windows to avoid huge regex over binary.
    try:
        text = data[: 512 * 1024].decode("latin-1", errors="ignore")
    except Exception:
        return ""
    return extract_doi_from_text(text)


def refresh_delivery(
    run_dir: str | Path,
    *,
    email: str = "",
    apply_rename: bool = True,
) -> DeliveryRefreshResult:
    """Scan ``结果/``, rename nonstandard PDFs, map orphans to failed rows, rewrite inventory.

    Safe to run repeatedly. Uses content-hash matching against batch row files and
    existing delivery names. Manual drops without DOI stay as 外部补入 after publish.
    """
    paths = paths_from_run_dir(run_dir)
    delivery = paths.root / USER_DELIVERY_DIR_NAME
    delivery.mkdir(parents=True, exist_ok=True)

    with batch_state_lock(paths.root):
        state = load_batch_state(paths.root)
        rows: list[dict] = list(state.get("rows") or [])

        # Hash of each success row's source file (if present).
        row_hashes: dict[str, list[dict]] = {}
        for row in rows:
            file_value = str(row.get("file", "") or "").strip()
            if not file_value:
                continue
            src = Path(file_value)
            if not src.is_file() or src.is_symlink():
                continue
            try:
                row_hashes.setdefault(_sha256(src), []).append(row)
            except OSError:
                continue

        pdfs = sorted(
            p
            for p in delivery.iterdir()
            if p.is_file() and not p.is_symlink() and p.suffix.lower() == ".pdf"
        )

        rename_log: list[dict[str, str]] = []
        renamed = 0
        mapped = 0
        external_kept = 0
        used_names = {p.name.lower() for p in pdfs}

        for pdf in list(pdfs):
            try:
                digest = _sha256(pdf)
            except OSError:
                continue

            matched_rows = row_hashes.get(digest) or []
            doi = ""
            year = ""
            author = ""
            title = ""
            note = ""

            if matched_rows:
                row = matched_rows[0]
                doi = clean_doi(row.get("doi") or row.get("input_doi") or "")
                year = str(row.get("year") or "")
                authors = str(row.get("authors") or "")
                author = authors.split("|")[0].split(",")[0].strip().split()[0] if authors else ""
                title = str(row.get("title") or row.get("input_title") or "")
                note = "hash_match_row"
            else:
                # Try DOI from filename or PDF bytes.
                doi = extract_doi_from_text(pdf.stem) or _extract_doi_from_pdf_bytes(
                    pdf.read_bytes()[: 512 * 1024]
                )
                if doi:
                    meta = _lookup_crossref(doi, email=email)
                    if meta:
                        doi = meta.get("doi") or doi
                        year = meta.get("year") or ""
                        author = meta.get("author") or ""
                        title = meta.get("title") or ""
                        note = "crossref_from_doi"
                    else:
                        y, a, t = _guess_meta_from_stem(pdf.stem)
                        year, author, title = y, a, t
                        note = "doi_no_crossref"
                else:
                    year, author, title = _guess_meta_from_stem(pdf.stem)
                    note = "filename_guess"

                # Attach to failed/missing row with same DOI.
                if doi:
                    target = None
                    for row in rows:
                        row_doi = clean_doi(row.get("doi") or row.get("input_doi") or "").lower()
                        if row_doi and row_doi == doi.lower():
                            target = row
                            break
                    if target is not None:
                        status = str(target.get("status") or "").lower()
                        if status not in SUCCESS_STATUSES:
                            target["status"] = "manual_imported"
                            target["source"] = "manual_import"
                            target["file"] = str(pdf.resolve())
                            target["reason"] = "manual_import_from_结果"
                            if year and not str(target.get("year") or "").strip():
                                target["year"] = year
                            if title and not str(target.get("title") or "").strip():
                                target["title"] = title
                            if author and not str(target.get("authors") or "").strip():
                                target["authors"] = author
                            mapped += 1
                            note = f"{note};mapped_row"
                            matched_rows = [target]

            # Build preferred delivery name when we have year/author/title.
            new_name = pdf.name
            if apply_rename and (year or author or title):
                preferred = _safe_name(
                    _year_author_title_name(year, author, title),
                    fallback=pdf.name,
                )
                if preferred.lower() != pdf.name.lower():
                    base = preferred
                    counter = 2
                    while preferred.lower() in used_names and preferred.lower() != pdf.name.lower():
                        preferred = f"{Path(base).stem}_{counter}.pdf"
                        counter += 1
                    if preferred.lower() != pdf.name.lower():
                        dest = pdf.with_name(preferred)
                        if not dest.exists():
                            old_name = pdf.name
                            old_resolved = str(pdf.resolve())
                            pdf.rename(dest)
                            used_names.discard(old_name.lower())
                            used_names.add(preferred.lower())
                            new_resolved = str(dest.resolve())
                            for row in matched_rows:
                                current = str(row.get("file") or "")
                                if current in {old_resolved, str(pdf), old_name}:
                                    row["file"] = new_resolved
                            # Mapped rows that pointed at delivery path
                            for row in rows:
                                if str(row.get("file") or "") == old_resolved:
                                    row["file"] = new_resolved
                            rename_log.append(
                                {
                                    "old_name": old_name,
                                    "new_name": preferred,
                                    "doi": doi,
                                    "year": year,
                                    "author": author,
                                    "title": title,
                                    "status": "renamed",
                                    "note": note,
                                }
                            )
                            renamed += 1
                            pdf = dest
                            continue
            if not matched_rows and not doi:
                external_kept += 1
            rename_log.append(
                {
                    "old_name": pdf.name,
                    "new_name": pdf.name,
                    "doi": doi,
                    "year": year,
                    "author": author,
                    "title": title,
                    "status": "unchanged" if not matched_rows else "tracked",
                    "note": note,
                }
            )

        state["rows"] = rows
        save_batch_state(paths, state)

    # Rebuild delivery from state (merge-safe: preserves remaining orphans).
    with batch_state_lock(paths.root):
        state = load_batch_state(paths.root)
        inventory_path = publish_user_delivery(paths, state["rows"])

    map_path = paths.root / RENAME_MAP_NAME
    _write_csv(map_path, RENAME_MAP_FIELDS, rename_log)

    return DeliveryRefreshResult(
        run_dir=paths.root,
        renamed=renamed,
        mapped_to_row=mapped,
        external_kept=external_kept,
        inventory_path=inventory_path,
        rename_map_path=map_path,
    )
