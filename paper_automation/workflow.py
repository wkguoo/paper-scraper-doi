from __future__ import annotations

from pathlib import Path

from .deduplicator import deduplicate_candidates
from .downloader import BytesGetter, download_pdf
from .file_manager import ensure_output_dirs, make_pdf_filename
from .artifact_store import make_artifact_filename
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
    artifact_filenames: bool = False,
    metadata_cache_path: str | Path | None = None,
) -> WorkflowResult:
    dirs = ensure_output_dirs(output_dir)
    candidates = parse_mixed_text(input_text)
    if limit is not None:
        candidates = candidates[:limit]
    deduped = deduplicate_candidates(candidates)
    resolver = MetadataResolver(
        email=email,
        http_json=http_json,
        cache_path=metadata_cache_path,
    )

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
            filename = (
                make_artifact_filename(candidate.source_index, metadata)
                if artifact_filenames
                else make_pdf_filename(metadata)
            )
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

