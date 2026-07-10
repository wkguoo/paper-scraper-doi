from __future__ import annotations

from pathlib import Path

from .deduplicator import deduplicate_candidates
from .downloader import BytesGetter, download_pdf
from .file_manager import ensure_output_dirs, make_pdf_filename
from .manifest import write_duplicates, write_manifest
from .metadata_resolver import JsonGetter, MetadataResolver
from .models import WorkflowResult
from .parser import parse_mixed_text
from .pdf_finder import choose_pdf_candidate


def run_workflow(
    input_text: str,
    output_dir: str | Path,
    email: str = "",
    dry_run: bool = False,
    overwrite: bool = False,
    limit: int | None = None,
    http_json: JsonGetter | None = None,
    http_bytes: BytesGetter | None = None,
) -> WorkflowResult:
    dirs = ensure_output_dirs(output_dir)
    candidates = parse_mixed_text(input_text)
    if limit is not None:
        candidates = candidates[:limit]
    deduped = deduplicate_candidates(candidates)
    resolver = MetadataResolver(email=email, http_json=http_json)

    rows: list[dict] = []
    resolved_count = 0
    downloaded_count = 0
    failed_count = 0

    for candidate in deduped.unique:
        metadata = resolver.resolve_one(candidate)
        if metadata.doi or metadata.title:
            resolved_count += 1
        pdf = choose_pdf_candidate(metadata)

        if candidate.status == "needs_review":
            download_status = "needs_review"
            file = ""
            reason = candidate.reason
        elif not pdf:
            download_status = "failed"
            file = ""
            reason = "no_legal_open_pdf"
            failed_count += 1
        elif dry_run:
            download_status = "dry_run"
            file = ""
            reason = "dry_run"
        else:
            filename = make_pdf_filename(metadata)
            download_result = download_pdf(
                pdf,
                dirs["pdfs"] / filename,
                http_bytes=http_bytes,
                overwrite=overwrite,
            )
            download_status = download_result.status
            file = download_result.file
            reason = download_result.reason
            if download_result.status == "downloaded":
                downloaded_count += 1
            elif download_result.status != "skipped":
                failed_count += 1

        rows.append({
            "source_index": candidate.source_index,
            "input_doi": candidate.doi,
            "input_title": candidate.title,
            "doi": metadata.doi,
            "title": metadata.title,
            "authors": metadata.authors,
            "journal": metadata.journal,
            "year": metadata.year,
            "publisher": metadata.publisher,
            "url": metadata.url,
            "is_oa": metadata.is_oa,
            "confidence": f"{metadata.confidence:.3f}",
            "pdf_source": pdf.source if pdf else "",
            "pdf_url": pdf.url if pdf else "",
            "download_status": download_status,
            "file": file,
            "reason": reason,
        })

    # --- 自动 Sci-Hub / Anna's Archive 回退（OA 路径失败后） ---
    failed_rows = [row for row in rows if row["download_status"] == "failed"]
    if failed_rows:
        from doi_batch_utils import PdfDownloadRecord, apply_auto_fallback

        records = [
            PdfDownloadRecord(
                doi=row["doi"],
                pii="",
                title=row["title"],
                status="failed",
                file=row["file"],
                reason=row["reason"],
            )
            for row in failed_rows
        ]
        updated, auto_success, auto_failed = apply_auto_fallback(records, dirs["pdfs"])
        updated_map = {rec.doi: rec for rec in updated if rec.doi}
        for row in rows:
            if row["download_status"] == "failed" and row["doi"] in updated_map:
                rec = updated_map[row["doi"]]
                if rec.status == "scihub_downloaded":
                    row["download_status"] = rec.status
                    row["file"] = rec.file
                    row["reason"] = rec.reason
                    row["pdf_source"] = getattr(rec, "manual_status", "") or "scihub"
                    row["pdf_url"] = getattr(rec, "manual_pdf_url", "") or ""
                    downloaded_count += 1
                    failed_count -= 1
        if auto_success or auto_failed:
            print(f"  [自动回退] Sci-Hub/Anna's 补下载: 成功 {auto_success}，仍失败 {auto_failed}")

    manifest_csv, manifest_json = write_manifest(rows, dirs["metadata"])
    duplicates_csv = write_duplicates(deduped.duplicates, dirs["failed"])
    return WorkflowResult(
        output_dir=str(dirs["root"]),
        total_input=len(candidates),
        unique_count=len(deduped.unique),
        duplicate_count=len(deduped.duplicates),
        resolved_count=resolved_count,
        downloaded_count=downloaded_count,
        failed_count=failed_count,
        manifest_csv=str(manifest_csv),
        manifest_json=str(manifest_json),
        duplicates_csv=str(duplicates_csv),
    )

