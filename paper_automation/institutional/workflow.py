from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from doi_batch_utils import DoiRecord, load_doi_records, write_pdf_bytes_atomic
from paper_automation.file_manager import make_pdf_filename
from paper_automation.metadata_resolver import MetadataResolver
from paper_automation.models import MetadataResult, PaperCandidate
from paper_automation.pdf_validation import is_pdf_bytes, is_valid_pdf

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
    circuit_breaker_threshold: int = 3,
    # When True (default): after unsupported / browser PDF failure, try bounded OA HTTP download.
    try_oa_direct: bool = True,
    # C6: IUCr short institutional try — trip iucr adapter after 1 fail → OA → Zotero.
    iucr_short_try: bool = True,
) -> InstitutionalWorkflowResult:
    directories = ensure_output_dirs(output_dir)
    records = load_doi_records(input_path, doi_column=doi_column, sheet_name=sheet_name)
    metadata_resolver = resolver or MetadataResolver(email=email)
    session_builder = session_factory or (lambda exe, port: DebugBrowserSession(browser_exe=exe, debug_port=port))
    session = session_builder(browser_exe, debug_port)
    oa_email = str(email or "")

    papers = [_resolve_paper(record, metadata_resolver) for record in records]
    # B2.1: pre-split unsupported so we never open a browser for adapter-less-only batches.
    supported_papers = [paper for paper in papers if select_adapter(paper) is not None]
    session_error = ""
    if supported_papers:
        try:
            # B2.4: reuse existing debug port when available.
            launched = session.ensure_ready()
            if launched and login_wait_seconds > 0:
                session.open_login_page(supported_papers[0].landing_url or f"https://doi.org/{supported_papers[0].doi}")
                print(
                    f"[提示] 已启动 {session.browser_name} 调试浏览器；如需机构登录，请在 {login_wait_seconds}s 内完成。"
                )
                time.sleep(login_wait_seconds)
        except RuntimeError as exc:
            session_error = str(exc)
    else:
        print("[机构] 无受支持出版社条目，跳过浏览器启动", flush=True)
        if try_oa_direct and papers:
            print("[机构] 无适配器条目将尝试 OA 直下（HTTP，无浏览器）", flush=True)

    rows: list[InstitutionalReportRow] = []
    # B2.3: consecutive failures per adapter name trip a circuit breaker.
    breaker_threshold = max(1, int(circuit_breaker_threshold or 3))
    consecutive_failures: dict[str, int] = {}
    tripped_adapters: set[str] = set()

    def _adapter_threshold(name: str) -> int:
        # C6: first IUCr browser miss trips remaining IUCr → OA/Zotero (no long thrash).
        if iucr_short_try and name == "iucr":
            return 1
        return breaker_threshold

    if iucr_short_try and any(
        (a := select_adapter(p)) is not None and a.name == "iucr" for p in papers
    ):
        print("[IUCr] short_try 开启：机构适配器失败 1 次后熔断，其余直送 OA/Zotero", flush=True)

    for index, paper in enumerate(papers, start=1):
        adapter = select_adapter(paper)
        adapter_name = adapter.name if adapter is not None else ""
        if adapter is None:
            row = _download_one(
                paper=paper,
                pdf_dir=directories["pdfs"],
                overwrite=overwrite,
                session=session,
                session_error=session_error,
                email=oa_email,
                try_oa_direct=try_oa_direct,
                iucr_short_try=iucr_short_try,
            )
            rows.append(row)
            continue
        if adapter_name in tripped_adapters:
            # Circuit-breaker skip still gets OA direct (no browser).
            reason = f"circuit_breaker:{adapter_name}"
            if adapter_name == "iucr" and iucr_short_try:
                reason = "circuit_breaker:iucr_short_try"
                print(f"[IUCr] short_try skip browser doi={paper.doi} → OA/Zotero", flush=True)
            row = _report_row(
                paper,
                adapter=adapter_name,
                status="not_pdf_response",
                reason=reason,
            )
            if try_oa_direct:
                row = _maybe_oa_direct(
                    paper,
                    pdf_dir=directories["pdfs"],
                    overwrite=overwrite,
                    email=oa_email,
                    prior=row,
                )
            rows.append(row)
            continue
        row = _download_one(
            paper=paper,
            pdf_dir=directories["pdfs"],
            overwrite=overwrite,
            session=session,
            session_error=session_error,
            email=oa_email,
            try_oa_direct=try_oa_direct,
            iucr_short_try=iucr_short_try,
        )
        rows.append(row)
        # Browser adapter success resets breaker; browser-path failure increments it.
        # OA-only rescues (adapter=oa_direct) do not count as adapter success.
        if row.status == "pdf_downloaded" and row.adapter == adapter_name:
            consecutive_failures[adapter_name] = 0
        elif row.adapter == adapter_name or (
            row.status != "pdf_downloaded" and row.adapter != "oa_direct"
        ):
            count = consecutive_failures.get(adapter_name, 0) + 1
            consecutive_failures[adapter_name] = count
            threshold = _adapter_threshold(adapter_name)
            if count >= threshold:
                tripped_adapters.add(adapter_name)
                label = "IUCr short_try" if adapter_name == "iucr" and iucr_short_try else "机构"
                print(
                    f"[{label}] 熔断 adapter={adapter_name} 连续失败 {count} 次，"
                    f"剩余同适配器条目将直送 OA/fallback",
                    flush=True,
                )
        # Throttle only after browser adapter attempts (not pure OA / unsupported).
        if (
            throttle_seconds > 0
            and index < len(papers)
            and row.adapter == adapter_name
            and not str(row.reason or "").startswith("oa_direct")
        ):
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
    *,
    email: str = "",
    try_oa_direct: bool = True,
    iucr_short_try: bool = True,
) -> InstitutionalReportRow:
    adapter = select_adapter(paper)
    if not adapter:
        prior = _report_row(
            paper,
            adapter="",
            status="unsupported_publisher",
            reason=unsupported_reason(paper),
        )
        if try_oa_direct:
            return _maybe_oa_direct(
                paper,
                pdf_dir=pdf_dir,
                overwrite=overwrite,
                email=email,
                prior=prior,
            )
        return prior
    if session_error:
        prior = _report_row(paper, adapter=adapter.name, status="error", reason=session_error)
        if try_oa_direct:
            return _maybe_oa_direct(
                paper, pdf_dir=pdf_dir, overwrite=overwrite, email=email, prior=prior
            )
        return prior
    if not (paper.landing_url or paper.doi):
        return _report_row(paper, adapter=adapter.name, status="error", reason="missing_landing_url")

    landing_url = paper.landing_url or f"https://doi.org/{paper.doi}"
    try:
        landing = session.load_page(landing_url)
    except RuntimeError as exc:
        prior = _report_row(
            paper, adapter=adapter.name, status="error", reason=str(exc), landing_url=landing_url
        )
        if try_oa_direct:
            return _maybe_oa_direct(
                paper, pdf_dir=pdf_dir, overwrite=overwrite, email=email, prior=prior
            )
        return prior
    except OSError as exc:
        prior = _report_row(
            paper, adapter=adapter.name, status="error", reason=str(exc), landing_url=landing_url
        )
        if try_oa_direct:
            return _maybe_oa_direct(
                paper, pdf_dir=pdf_dir, overwrite=overwrite, email=email, prior=prior
            )
        return prior
    attempt_notes: list[str] = []
    candidates = list(adapter.build_pdf_candidates(paper, landing))
    # C6: fewer PDF probes for IUCr short try (top high-value URLs only).
    if iucr_short_try and adapter.name == "iucr" and len(candidates) > 3:
        candidates = candidates[:3]
    for candidate in candidates:
        target_path = pdf_dir / _make_filename(paper)
        if target_path.exists() and not overwrite:
            if is_valid_pdf(target_path):
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
                target_path.unlink()
            except OSError:
                return _report_row(
                    paper,
                    adapter=adapter.name,
                    status="error",
                    reason="invalid_existing_pdf",
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
        if capture.pdf_bytes and is_pdf_bytes(capture.pdf_bytes):
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
        if capture.pdf_bytes:
            attempt_notes.append("not_pdf_response")
        else:
            attempt_notes.append(capture.note)
    status, reason = adapter.classify_failure(landing, tuple(attempt_notes))
    prior = _report_row(
        paper,
        adapter=adapter.name,
        status=status,
        reason=reason,
        landing_url=landing_url,
        final_landing_url=landing.final_url,
    )
    if try_oa_direct and status != "pdf_downloaded":
        return _maybe_oa_direct(
            paper,
            pdf_dir=pdf_dir,
            overwrite=overwrite,
            email=email,
            prior=prior,
        )
    return prior


def _maybe_oa_direct(
    paper: InstitutionalPaper,
    *,
    pdf_dir: Path,
    overwrite: bool,
    email: str = "",
    prior: InstitutionalReportRow,
) -> InstitutionalReportRow:
    """Bounded OA/repo HTTP download after institutional miss (no browser)."""

    doi = (paper.doi or paper.input_doi or "").strip()
    if not doi:
        return prior
    target_path = pdf_dir / _make_filename(paper)
    if target_path.exists() and not overwrite and is_valid_pdf(target_path):
        return _report_row(
            paper,
            adapter="oa_direct",
            status="pdf_downloaded",
            file=str(target_path),
            reason=f"oa_direct:file_exists; prior={prior.status}:{prior.reason}",
            landing_url=prior.landing_url,
            final_landing_url=prior.final_landing_url,
        )
    try:
        from paper_automation.oa_recovery import recover_oa_limited
    except Exception as exc:  # noqa: BLE001
        return _report_row(
            paper,
            adapter=prior.adapter,
            status=prior.status,
            file=prior.file,
            reason=f"{prior.reason}; oa_direct_import_failed:{exc}"[:500],
            landing_url=prior.landing_url,
            final_landing_url=prior.final_landing_url,
            pdf_url=prior.pdf_url,
        )
    try:
        result = recover_oa_limited(
            doi,
            email=email,
            output_dir=pdf_dir,
            budget_seconds=45.0,
        )
    except Exception as exc:  # noqa: BLE001
        return _report_row(
            paper,
            adapter=prior.adapter,
            status=prior.status,
            file=prior.file,
            reason=f"{prior.reason}; oa_direct_exc:{type(exc).__name__}"[:500],
            landing_url=prior.landing_url,
            final_landing_url=prior.final_landing_url,
            pdf_url=prior.pdf_url,
        )
    if result.status == "oa_downloaded" and result.file:
        print(
            f"[OA直下] {doi} <- {result.reason} -> {Path(result.file).name}",
            flush=True,
        )
        return _report_row(
            paper,
            adapter="oa_direct",
            status="pdf_downloaded",
            file=result.file,
            reason=f"oa_direct:{result.reason}; prior={prior.status}:{prior.reason}",
            landing_url=prior.landing_url or f"https://doi.org/{doi}",
            final_landing_url=prior.final_landing_url,
            pdf_url=result.reason,
        )
    # Keep prior institutional status; append OA attempt outcome for audit.
    note = f"oa_direct:{result.status}"
    if result.reason and result.reason != result.status:
        note = f"{note}({result.reason})"
    prior_reason = (prior.reason or "").strip()
    combined = f"{prior_reason}; {note}".strip("; ") if prior_reason else note
    return _report_row(
        paper,
        adapter=prior.adapter,
        status=prior.status,
        file=prior.file,
        reason=combined[:500],
        landing_url=prior.landing_url,
        final_landing_url=prior.final_landing_url,
        pdf_url=prior.pdf_url,
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
