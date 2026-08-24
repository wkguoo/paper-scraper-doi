from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from doi_batch_utils import clean_doi
from sd_institutional_skill import main as sd_main

from .batch_workflow import is_valid_pdf
from .institutional import run_institutional_workflow
from .parser import extract_dois
from .workflow import run_workflow


_MULTIPLE_DOIS_LAYOUT = -1


@dataclass(frozen=True)
class BatchOptions:
    email: str = ""
    cookies: str = ""
    browser_exe: str = ""
    login_wait_seconds: int = 0
    debug_port: int = 9333
    throttle_seconds: float = 1.0
    # When True (default), auth/captcha failures go straight to zotero_fallback.
    skip_manual_retry: bool = True
    # Supplements on by default; disable with --no-download-supplements.
    download_supplements: bool = True
    # Opt2: Elsevier→SD, gold OA→OA first, other→adapters (skip blanket OA-first).
    smart_route: bool = True
    # Opt3: ScienceDirect fixed session break (was 150s; now 60s).
    session_break_seconds: float = 60.0
    session_break_every: int = 8
    # Opt1: do not auto-resolve title-only metadata during intake unless requested.
    resolve_title_metadata: bool = False
    # B2.3: trip non-Elsevier adapter after N consecutive failures.
    circuit_breaker_threshold: int = 3
    # B3.3: after institutional failures, try bounded OA (unsupported/not_pdf always;
    # other failures need OA signal). Disable with auto_oa_recovery=False.
    auto_oa_recovery: bool = True
    # C6: IUCr (10.1107) short institutional try — trip adapter after 1 fail → OA → Zotero.
    iucr_short_try: bool = True
    # Explicit API-only mode: Elsevier API attempts only; no browser/OA/Zotero fallback.
    api_only: bool = False
    # Elsevier article/PDF/supplement jobs; bounded to 1-3 by state validation.
    api_workers: int = 2


@dataclass(frozen=True)
class StageResult:
    task_id: str
    doi: str
    title: str
    status: str
    file: str
    reason: str
    source: str


@dataclass(frozen=True)
class _PreparedRows:
    owner_rows: list[dict]
    layout: list[int | None]


def is_elsevier_doi(doi: str) -> bool:
    return clean_doi(doi).lower().startswith("10.1016/")


def is_iucr_doi(doi: str) -> bool:
    """IUCr journals share the 10.1107/ prefix."""
    return clean_doi(doi).lower().startswith("10.1107/")


def is_gold_oa_doi(doi: str) -> bool:
    """Heuristic gold-OA publishers worth trying open PDF first."""
    d = clean_doi(doi).lower()
    if not d:
        return False
    return (
        d.startswith("10.3390/")  # MDPI
        or d.startswith("10.3389/")  # Frontiers
        or d.startswith("10.1371/")  # PLOS
        or d.startswith("10.1186/")  # BMC
        or d.startswith("10.1038/s41598")
        or d.startswith("10.1038/srep")
        or d.startswith("10.1038/s41467")
        or d.startswith("10.1038/s41524")
    )


def split_route_rows(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split into (gold_oa, elsevier, other) for smart routing."""
    gold_oa: list[dict] = []
    science_direct: list[dict] = []
    other: list[dict] = []
    for row in rows:
        doi = str(row.get("doi", "") or "")
        if is_gold_oa_doi(doi):
            gold_oa.append(row)
        elif is_elsevier_doi(doi):
            science_direct.append(row)
        else:
            other.append(row)
    return gold_oa, science_direct, other


def split_institutional_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    science_direct: list[dict] = []
    other: list[dict] = []
    for row in rows:
        target = science_direct if is_elsevier_doi(str(row.get("doi", "") or "")) else other
        target.append(row)
    return science_direct, other


def needs_manual_retry(status: str, reason: str) -> bool:
    text = f"{status} {reason}".lower()
    return any(token in text for token in ("auth_required", "captcha", "turnstile", "login_required", "login required"))


def write_stage_input(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["task_id", "doi", "title", "authors", "journal", "year"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return path


def run_oa_stage(rows: list[dict], output_dir: Path, options: BatchOptions) -> list[StageResult]:
    if not rows:
        return []
    prepared = _prepare_stage_rows(rows)
    if not prepared.owner_rows:
        return _restore_stage_results(rows, prepared, [], "oa")
    stage_rows: list[dict] = []
    input_values: list[str] = []
    for row in prepared.owner_rows:
        stage_row = dict(row)
        input_value = _oa_input_value(row)
        if input_value:
            input_values.append(input_value)
            stage_row["_stage_source_index"] = str(len(input_values))
        stage_rows.append(stage_row)
    input_text = "\n".join(input_values)
    try:
        workflow_result = run_workflow(input_text, output_dir / "oa", email=options.email)
    except Exception as exc:
        owner_results = _stage_failure(prepared.owner_rows, "oa", _exception_reason(exc))
        return _restore_stage_results(rows, prepared, owner_results, "oa")

    report_path = _optional_report_path(getattr(workflow_result, "manifest_csv", None))
    if report_path is None:
        owner_results = _stage_failure(stage_rows, "oa", "stage_report_missing")
        return _restore_stage_results(rows, prepared, owner_results, "oa")
    raw_output_dir = getattr(workflow_result, "output_dir", "")
    workflow_output_dir = str(raw_output_dir).strip() if raw_output_dir is not None else ""
    pdf_base_dir = (
        Path(workflow_output_dir) / "pdfs"
        if workflow_output_dir
        else report_path.parent.parent / "pdfs"
    )
    owner_results = _map_report(
        stage_rows,
        report_path,
        pdf_base_dir=pdf_base_dir,
        source="oa",
        status_field="download_status",
        success_statuses={"downloaded", "skipped"},
    )
    return _restore_stage_results(rows, prepared, owner_results, "oa")


def run_sciencedirect_stage(input_path: Path, output_dir: Path, options: BatchOptions) -> list[StageResult]:
    rows = _read_stage_input(input_path)
    if not rows:
        return []
    prepared = _prepare_stage_rows(rows)
    if not prepared.owner_rows:
        return _restore_stage_results(rows, prepared, [], "sciencedirect")
    stage_input_path = _deduplicated_stage_input(
        input_path,
        output_dir,
        prepared,
        source="sciencedirect",
    )
    argv = [
        "--input",
        str(stage_input_path),
        "--out",
        str(output_dir),
        "--run-name",
        "sciencedirect",
    ]
    # Supplements on by default.
    if bool(getattr(options, "download_supplements", True)):
        argv.append("--download-supplements")
    else:
        argv.append("--no-download-supplements")
    if bool(getattr(options, "api_only", False)):
        argv.append("--api-only")
    argv.extend(["--api-workers", str(int(getattr(options, "api_workers", 2) or 2))])
    # Opt3: fixed session break (default 60s / every 8 successes).
    break_s = float(getattr(options, "session_break_seconds", 60.0) or 60.0)
    break_n = int(getattr(options, "session_break_every", 8) or 8)
    argv.extend(["--session-break-seconds", str(break_s)])
    argv.extend(["--session-break-every", str(break_n)])
    if options.email:
        argv.extend(["--email", options.email])
    if options.cookies:
        argv.extend(["--cookies", options.cookies])
    if options.browser_exe:
        argv.extend(["--browser-exe", options.browser_exe])
    if options.login_wait_seconds:
        argv.extend(["--login-wait-seconds", str(options.login_wait_seconds)])

    try:
        exit_code = sd_main(argv)
    except Exception as exc:
        owner_results = _stage_failure(prepared.owner_rows, "sciencedirect", _exception_reason(exc))
        return _restore_stage_results(rows, prepared, owner_results, "sciencedirect")

    report_path = output_dir / "sciencedirect" / "pdf_download_report.csv"
    if exit_code != 0 and not report_path.is_file():
        owner_results = _stage_failure(prepared.owner_rows, "sciencedirect", f"stage_exit_code_{exit_code}")
        return _restore_stage_results(rows, prepared, owner_results, "sciencedirect")
    owner_results = _map_report(
        prepared.owner_rows,
        report_path,
        pdf_base_dir=report_path.parent / "pdfs",
        source="sciencedirect",
        status_field="status",
        success_statuses={"success"},
        missing_row_reason=(
            f"stage_exit_code_{exit_code}"
            if exit_code != 0
            else "missing_stage_report_row"
        ),
    )
    return _restore_stage_results(rows, prepared, owner_results, "sciencedirect")


def run_non_elsevier_stage(input_path: Path, output_dir: Path, options: BatchOptions) -> list[StageResult]:
    rows = _read_stage_input(input_path)
    if not rows:
        return []
    prepared = _prepare_stage_rows(rows)
    if not prepared.owner_rows:
        return _restore_stage_results(rows, prepared, [], "non_elsevier")
    stage_input_path = _deduplicated_stage_input(
        input_path,
        output_dir,
        prepared,
        source="non_elsevier",
    )
    try:
        workflow_result = run_institutional_workflow(
            input_path=stage_input_path,
            output_dir=output_dir,
            email=options.email,
            browser_exe=options.browser_exe or None,
            debug_port=options.debug_port,
            login_wait_seconds=options.login_wait_seconds,
            throttle_seconds=options.throttle_seconds,
            circuit_breaker_threshold=int(getattr(options, "circuit_breaker_threshold", 3) or 3),
            iucr_short_try=bool(getattr(options, "iucr_short_try", True)),
        )
    except Exception as exc:
        owner_results = _stage_failure(prepared.owner_rows, "non_elsevier", _exception_reason(exc))
        return _restore_stage_results(rows, prepared, owner_results, "non_elsevier")

    report_path = _optional_report_path(getattr(workflow_result, "report_path", None))
    if report_path is None:
        owner_results = _stage_failure(prepared.owner_rows, "non_elsevier", "stage_report_missing")
        return _restore_stage_results(rows, prepared, owner_results, "non_elsevier")
    owner_results = _map_report(
        prepared.owner_rows,
        report_path,
        pdf_base_dir=report_path.parent / "pdfs",
        source="non_elsevier",
        status_field="status",
        success_statuses={"pdf_downloaded"},
    )
    return _restore_stage_results(rows, prepared, owner_results, "non_elsevier")


def _oa_input_value(row: dict) -> str:
    doi = str(row.get("doi", "")).strip()
    title = str(row.get("title", "")).strip()
    return doi or title


def _read_stage_input(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [{key: str(value or "") for key, value in row.items()} for row in csv.DictReader(handle)]


def _optional_report_path(value: object) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    return Path(text) if text else None


def _prepare_stage_rows(rows: list[dict]) -> _PreparedRows:
    owner_rows: list[dict] = []
    layout: list[int | None] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if len(_stage_input_dois(row)) > 1:
            layout.append(_MULTIPLE_DOIS_LAYOUT)
            continue
        identity = _stage_input_identity(row)
        if identity is not None and identity in seen:
            layout.append(None)
            continue
        if identity is not None:
            seen.add(identity)
        layout.append(len(owner_rows))
        owner_rows.append(row)
    return _PreparedRows(owner_rows=owner_rows, layout=layout)


def _stage_input_dois(row: dict) -> list[str]:
    text = " ".join(
        value
        for value in (
            str(row.get("doi", "")).strip(),
            str(row.get("title", "")).strip(),
        )
        if value
    )
    return extract_dois(text)


def _stage_input_identity(row: dict) -> tuple[str, str] | None:
    doi = _normalise_doi(row.get("doi", ""))
    if doi:
        return "doi", doi
    title = _normalise_identity(row.get("title", ""))
    if title:
        return "title", title
    return None


def _deduplicated_stage_input(
    input_path: Path,
    output_dir: Path,
    prepared: _PreparedRows,
    *,
    source: str,
) -> Path:
    if len(prepared.owner_rows) == len(prepared.layout):
        return input_path
    return write_stage_input(
        prepared.owner_rows,
        output_dir / "working" / f"{source}_stage_input.csv",
    )


def _restore_stage_results(
    input_rows: list[dict],
    prepared: _PreparedRows,
    owner_results: list[StageResult],
    source: str,
) -> list[StageResult]:
    results: list[StageResult] = []
    for row, owner_index in zip(input_rows, prepared.layout):
        if owner_index == _MULTIPLE_DOIS_LAYOUT:
            results.append(
                _failure_for_row(
                    row,
                    source,
                    "multiple_dois_in_stage_input",
                )
            )
        elif owner_index is None:
            results.append(
                StageResult(
                    task_id=str(row.get("task_id", "")),
                    doi=str(row.get("doi", "")),
                    title=str(row.get("title", "")),
                    status="duplicate",
                    file="",
                    reason="duplicate_stage_input",
                    source=source,
                )
            )
        else:
            results.append(owner_results[owner_index])
    return results


def _map_report(
    input_rows: list[dict],
    report_path: Path,
    *,
    pdf_base_dir: Path,
    source: str,
    status_field: str,
    success_statuses: set[str],
    missing_row_reason: str = "missing_stage_report_row",
) -> list[StageResult]:
    if not report_path.is_file():
        return _stage_failure(input_rows, source, "stage_report_missing")
    try:
        with report_path.open("r", newline="", encoding="utf-8-sig") as handle:
            report_rows = [{key: str(value or "") for key, value in row.items()} for row in csv.DictReader(handle)]
    except (OSError, UnicodeError, csv.Error):
        return _stage_failure(input_rows, source, "stage_report_read_error")

    matched_rows = _match_report_rows(input_rows, report_rows)
    results: list[StageResult] = []
    for input_row, report_row in zip(input_rows, matched_rows):
        if report_row is None:
            results.append(_failure_for_row(input_row, source, missing_row_reason))
            continue
        results.append(
            _normalise_report_row(
                input_row,
                report_row,
                pdf_base_dir,
                source,
                status_field,
                success_statuses,
            )
        )
    return results


def _match_report_rows(input_rows: list[dict], report_rows: list[dict[str, str]]) -> list[dict[str, str] | None]:
    unused = list(report_rows)
    matches: list[dict[str, str] | None] = []
    for index, input_row in enumerate(input_rows):
        matched_index = _find_matching_report_row(input_row, unused)
        if matched_index is None:
            matched_index = _find_matching_row_number(index, unused)
        matches.append(unused.pop(matched_index) if matched_index is not None else None)
    return matches


def _find_matching_report_row(input_row: dict, report_rows: list[dict[str, str]]) -> int | None:
    source_index = str(input_row.get("_stage_source_index", "")).strip()
    if source_index:
        for index, report_row in enumerate(report_rows):
            if report_row.get("source_index", "").strip() == source_index:
                return index
    input_doi = _normalise_doi(input_row.get("doi", ""))
    input_title = _normalise_identity(input_row.get("title", ""))
    if input_doi and input_title:
        for index, report_row in enumerate(report_rows):
            if _normalise_doi(report_row.get("doi", "")) == input_doi and _normalise_identity(report_row.get("title", "")) == input_title:
                return index
    if input_doi:
        for index, report_row in enumerate(report_rows):
            if _normalise_doi(report_row.get("doi", "")) == input_doi:
                return index
    if input_title:
        for index, report_row in enumerate(report_rows):
            if _normalise_identity(report_row.get("title", "")) == input_title:
                return index
    return None


def _find_matching_row_number(index: int, report_rows: list[dict[str, str]]) -> int | None:
    expected_number = index + 2
    for report_index, report_row in enumerate(report_rows):
        try:
            if int(report_row.get("row_number", "")) == expected_number:
                return report_index
        except ValueError:
            continue
    return None


def _normalise_report_row(
    input_row: dict,
    report_row: dict[str, str],
    pdf_base_dir: Path,
    source: str,
    status_field: str,
    success_statuses: set[str],
) -> StageResult:
    status = report_row.get(status_field, "").strip()
    reason = report_row.get("reason", "").strip()
    file = report_row.get("file", "").strip()
    if status.lower() in success_statuses:
        pdf_path = _resolve_report_pdf(file, pdf_base_dir)
        if pdf_path is not None and _is_valid_local_pdf(pdf_path):
            return StageResult(
                task_id=str(input_row.get("task_id", "")),
                doi=report_row.get("doi", "") or str(input_row.get("doi", "")),
                title=report_row.get("title", "") or str(input_row.get("title", "")),
                status="downloaded",
                file=str(pdf_path),
                reason="",
                source=source,
            )
        return _failure_for_row(input_row, source, "invalid_pdf", doi=report_row.get("doi", ""), title=report_row.get("title", ""))
    return StageResult(
        task_id=str(input_row.get("task_id", "")),
        doi=report_row.get("doi", "") or str(input_row.get("doi", "")),
        title=report_row.get("title", "") or str(input_row.get("title", "")),
        status=status or "failed",
        file="",
        reason=reason or "stage_report_status_missing",
        source=source,
    )


def _resolve_report_pdf(file: str, pdf_base_dir: Path) -> Path | None:
    if not file or file.lower().startswith(("http://", "https://")):
        return None
    path = Path(file).expanduser()
    if path.is_absolute():
        try:
            return path.resolve()
        except OSError:
            return None
    try:
        # Check the reported relative entry before resolving the base path.
        # Windows can spell the same temp directory as a long path or an 8.3
        # alias; resolving first can hide the final symlink from this guard.
        base_input = pdf_base_dir.expanduser()
        candidate_input = base_input / path
        if candidate_input.is_symlink():
            return None
        base_dir = base_input.resolve()
        candidate = base_dir / path
        resolved = candidate.resolve()
        resolved.relative_to(base_dir)
    except (OSError, ValueError):
        return None
    return resolved


def _is_valid_local_pdf(path: Path) -> bool:
    try:
        return not path.is_symlink() and path.is_file() and is_valid_pdf(path)
    except OSError:
        return False


def _stage_failure(rows: list[dict], source: str, reason: str) -> list[StageResult]:
    return [_failure_for_row(row, source, reason) for row in rows]


def _failure_for_row(input_row: dict, source: str, reason: str, *, doi: str = "", title: str = "") -> StageResult:
    return StageResult(
        task_id=str(input_row.get("task_id", "")),
        doi=doi or str(input_row.get("doi", "")),
        title=title or str(input_row.get("title", "")),
        status="failed",
        file="",
        reason=reason,
        source=source,
    )


def _normalise_identity(value: object) -> str:
    return " ".join(str(value or "").split()).lower()


def _normalise_doi(value: object) -> str:
    return clean_doi(value).lower()


def _exception_reason(exc: Exception) -> str:
    return f"stage_exception_{type(exc).__name__}"
