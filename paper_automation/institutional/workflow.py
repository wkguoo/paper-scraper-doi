from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from doi_batch_utils import DoiRecord, load_doi_records, write_pdf_bytes_atomic
from paper_automation.file_manager import make_pdf_filename
from paper_automation.metadata_resolver import MetadataResolver
from paper_automation.models import MetadataResult, PaperCandidate

from .browser_session import DebugBrowserSession
from .models import InstitutionalPaper, InstitutionalReportRow, InstitutionalWorkflowResult
from .registry import select_adapter, unsupported_reason
from .reporting import ensure_output_dirs, merge_manifest, write_report, write_run_summary


SessionFactory = Callable[[str | None, int], DebugBrowserSession]


def run_institutional_workflow(
    input_path: str | Path,
    output_dir: str | Path,
    doi_column: str | None = None,
    sheet_name: str | None = None,
    email: str = "",
    browser_exe: str | None = None,
    debug_port: int = 9333,
    login_wait_seconds: int = 0,
    throttle_seconds: float = 1.0,
    overwrite: bool = False,
    merge_manifest_path: str | Path | None = None,
    resolver: MetadataResolver | None = None,
    session_factory: SessionFactory | None = None,
) -> InstitutionalWorkflowResult:
    directories = ensure_output_dirs(output_dir)
    records = load_doi_records(input_path, doi_column=doi_column, sheet_name=sheet_name)
    metadata_resolver = resolver or MetadataResolver(email=email)
    session_builder = session_factory or (lambda exe, port: DebugBrowserSession(browser_exe=exe, debug_port=port))
    session = session_builder(browser_exe, debug_port)

    papers = [_resolve_paper(record, metadata_resolver) for record in records]
    supported_papers = [paper for paper in papers if select_adapter(paper) is not None]
    session_error = ""
    if supported_papers:
        try:
            launched = session.ensure_ready()
            if launched and login_wait_seconds > 0:
                session.open_login_page(supported_papers[0].landing_url or f"https://doi.org/{supported_papers[0].doi}")
                print(
                    f"[提示] 已启动 {session.browser_name} 调试浏览器；如需机构登录，请在 {login_wait_seconds}s 内完成。"
                )
                time.sleep(login_wait_seconds)
        except RuntimeError as exc:
            session_error = str(exc)

    rows: list[InstitutionalReportRow] = []
    for index, paper in enumerate(papers, start=1):
        row = _download_one(
            paper=paper,
            pdf_dir=directories["pdfs"],
            overwrite=overwrite,
            session=session,
            session_error=session_error,
        )
        rows.append(row)
        if throttle_seconds > 0 and index < len(papers):
            time.sleep(throttle_seconds)

    report_path = write_report(rows, output_dir)
    manifest_update_path = ""
    if merge_manifest_path:
        manifest_update_path = str(merge_manifest(merge_manifest_path, rows, output_dir))
    summary_path = write_run_summary(rows, output_dir, report_path, manifest_update_path=manifest_update_path)
    status_counts = _status_counts(rows)
    return InstitutionalWorkflowResult(
        output_dir=str(directories["root"]),
        pdf_dir=str(directories["pdfs"]),
        total_input=len(records),
        resolved_count=sum(1 for row in rows if row.doi),
        downloaded_count=status_counts.get("pdf_downloaded", 0),
        failed_count=len(rows) - status_counts.get("pdf_downloaded", 0),
        status_counts=status_counts,
        report_path=str(report_path),
        run_summary_path=str(summary_path),
        manifest_update_path=manifest_update_path,
        rows=tuple(rows),
    )


def _resolve_paper(record: DoiRecord, resolver: MetadataResolver) -> InstitutionalPaper:
    candidate = PaperCandidate(
        source_index=record.row_number,
        raw_text=record.raw_value or record.title or record.doi,
        doi=record.doi,
        title=record.title,
    )
    metadata = resolver.resolve_one(candidate)
    landing_url = metadata.url or (f"https://doi.org/{metadata.doi}" if metadata.doi else "")
    return InstitutionalPaper(
        row_number=record.row_number,
        input_doi=record.doi,
        doi=metadata.doi or record.doi,
        title=metadata.title or record.title or metadata.query_title or record.raw_value,
        input_title=record.title,
        authors=tuple(metadata.authors),
        journal=metadata.journal or record.journal,
        year=metadata.year or record.year,
        publisher=metadata.publisher,
        landing_url=landing_url,
        metadata_source=metadata.source,
        raw_value=record.raw_value,
    )


def _download_one(
    paper: InstitutionalPaper,
    pdf_dir: Path,
    overwrite: bool,
    session: DebugBrowserSession,
    session_error: str,
) -> InstitutionalReportRow:
    adapter = select_adapter(paper)
    if not adapter:
        return _report_row(
            paper,
            adapter="",
            status="unsupported_publisher",
            reason=unsupported_reason(paper),
        )
    if session_error:
        return _report_row(paper, adapter=adapter.name, status="error", reason=session_error)
    if not (paper.landing_url or paper.doi):
        return _report_row(paper, adapter=adapter.name, status="error", reason="missing_landing_url")

    landing_url = paper.landing_url or f"https://doi.org/{paper.doi}"
    try:
        landing = session.load_page(landing_url)
    except RuntimeError as exc:
        return _report_row(paper, adapter=adapter.name, status="error", reason=str(exc), landing_url=landing_url)
    except OSError as exc:
        return _report_row(paper, adapter=adapter.name, status="error", reason=str(exc), landing_url=landing_url)
    attempt_notes: list[str] = []
    for candidate in adapter.build_pdf_candidates(paper, landing):
        target_path = pdf_dir / _make_filename(paper)
        if target_path.exists() and not overwrite:
            return _report_row(
                paper,
                adapter=adapter.name,
                status="pdf_downloaded",
                file=str(target_path),
                reason="file_exists",
                landing_url=landing_url,
                final_landing_url=landing.final_url,
                pdf_url=candidate.url,
            )
        try:
            capture = session.capture_pdf(candidate.url, candidate.fetch_patterns)
        except RuntimeError as exc:
            attempt_notes.append(str(exc))
            continue
        except OSError as exc:
            attempt_notes.append(str(exc))
            continue
        if capture.pdf_bytes:
            write_pdf_bytes_atomic(target_path, capture.pdf_bytes)
            return _report_row(
                paper,
                adapter=adapter.name,
                status="pdf_downloaded",
                file=str(target_path),
                landing_url=landing_url,
                final_landing_url=landing.final_url,
                pdf_url=capture.pdf_url or candidate.url,
            )
        attempt_notes.append(capture.note)
    status, reason = adapter.classify_failure(landing, tuple(attempt_notes))
    return _report_row(
        paper,
        adapter=adapter.name,
        status=status,
        reason=reason,
        landing_url=landing_url,
        final_landing_url=landing.final_url,
    )


def _make_filename(paper: InstitutionalPaper) -> str:
    metadata = MetadataResult(
        source_index=paper.row_number,
        query_title=paper.input_title or paper.title,
        doi=paper.doi,
        title=paper.title,
        authors=list(paper.authors),
        year=paper.year,
    )
    return make_pdf_filename(metadata)


def _report_row(
    paper: InstitutionalPaper,
    adapter: str,
    status: str,
    file: str = "",
    reason: str = "",
    landing_url: str = "",
    final_landing_url: str = "",
    pdf_url: str = "",
) -> InstitutionalReportRow:
    return InstitutionalReportRow(
        row_number=paper.row_number,
        doi=paper.doi or paper.input_doi,
        title=paper.title,
        journal=paper.journal,
        year=paper.year,
        publisher=paper.publisher,
        adapter=adapter,
        status=status,
        file=file,
        reason=reason,
        landing_url=landing_url,
        final_landing_url=final_landing_url,
        pdf_url=pdf_url,
        metadata_source=paper.metadata_source,
    )


def _status_counts(rows: list[InstitutionalReportRow]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts
