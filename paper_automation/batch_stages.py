from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from sd_institutional_skill import main as sd_main

from .batch_workflow import is_valid_pdf
from .institutional import run_institutional_workflow
from .workflow import run_workflow


@dataclass(frozen=True)
class BatchOptions:
    email: str = ""
    cookies: str = ""
    browser_exe: str = ""
    login_wait_seconds: int = 0
    debug_port: int = 9333
    throttle_seconds: float = 1.0


@dataclass(frozen=True)
class StageResult:
    task_id: str
    doi: str
    title: str
    status: str
    file: str
    reason: str
    source: str


def split_institutional_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    science_direct: list[dict] = []
    other: list[dict] = []
    for row in rows:
        target = science_direct if str(row.get("doi", "")).strip().lower().startswith("10.1016/") else other
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
    input_text = "\n".join(_oa_input_value(row) for row in rows)
    try:
        workflow_result = run_workflow(input_text, output_dir / "oa", email=options.email)
    except Exception as exc:
        return _stage_failure(rows, "oa", _exception_reason(exc))

    report_path = Path(getattr(workflow_result, "manifest_csv", ""))
    return _map_report(
        rows,
        report_path,
        source="oa",
        status_field="download_status",
        success_statuses={"downloaded", "skipped"},
    )


def run_sciencedirect_stage(input_path: Path, output_dir: Path, options: BatchOptions) -> list[StageResult]:
    rows = _read_stage_input(input_path)
    if not rows:
        return []
    argv = [
        "--input",
        str(input_path),
        "--out",
        str(output_dir),
        "--run-name",
        "sciencedirect",
        "--no-download-supplements",
    ]
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
        return _stage_failure(rows, "sciencedirect", _exception_reason(exc))
    if exit_code != 0:
        return _stage_failure(rows, "sciencedirect", f"stage_exit_code_{exit_code}")

    return _map_report(
        rows,
        output_dir / "sciencedirect" / "pdf_download_report.csv",
        source="sciencedirect",
        status_field="status",
        success_statuses={"success"},
    )


def run_non_elsevier_stage(input_path: Path, output_dir: Path, options: BatchOptions) -> list[StageResult]:
    rows = _read_stage_input(input_path)
    if not rows:
        return []
    try:
        workflow_result = run_institutional_workflow(
            input_path=input_path,
            output_dir=output_dir,
            email=options.email,
            browser_exe=options.browser_exe or None,
            debug_port=options.debug_port,
            login_wait_seconds=options.login_wait_seconds,
            throttle_seconds=options.throttle_seconds,
        )
    except Exception as exc:
        return _stage_failure(rows, "non_elsevier", _exception_reason(exc))

    report_path = Path(
        getattr(
            workflow_result,
            "report_path",
            output_dir / "non_elsevier_institutional" / "institutional_pdf_download_report.csv",
        )
    )
    return _map_report(
        rows,
        report_path,
        source="non_elsevier",
        status_field="status",
        success_statuses={"pdf_downloaded"},
    )


def _oa_input_value(row: dict) -> str:
    doi = str(row.get("doi", "")).strip()
    title = str(row.get("title", "")).strip()
    return doi or title


def _read_stage_input(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [{key: str(value or "") for key, value in row.items()} for row in csv.DictReader(handle)]


def _map_report(
    input_rows: list[dict],
    report_path: Path,
    *,
    source: str,
    status_field: str,
    success_statuses: set[str],
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
            results.append(_failure_for_row(input_row, source, "missing_stage_report_row"))
            continue
        results.append(_normalise_report_row(input_row, report_row, source, status_field, success_statuses))
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
    input_doi = _normalise_identity(input_row.get("doi", ""))
    input_title = _normalise_identity(input_row.get("title", ""))
    if input_doi and input_title:
        for index, report_row in enumerate(report_rows):
            if _normalise_identity(report_row.get("doi", "")) == input_doi and _normalise_identity(report_row.get("title", "")) == input_title:
                return index
    if input_doi:
        for index, report_row in enumerate(report_rows):
            if _normalise_identity(report_row.get("doi", "")) == input_doi:
                return index
    if input_title:
        for index, report_row in enumerate(report_rows):
            if _normalise_identity(report_row.get("title", "")) == input_title:
                return index
    return None


def _find_matching_row_number(index: int, report_rows: list[dict[str, str]]) -> int | None:
    expected_numbers = {index + 1, index + 2}
    for report_index, report_row in enumerate(report_rows):
        try:
            if int(report_row.get("row_number", "")) in expected_numbers:
                return report_index
        except ValueError:
            continue
    return None


def _normalise_report_row(
    input_row: dict,
    report_row: dict[str, str],
    source: str,
    status_field: str,
    success_statuses: set[str],
) -> StageResult:
    status = report_row.get(status_field, "").strip()
    reason = report_row.get("reason", "").strip()
    file = report_row.get("file", "").strip()
    if status.lower() in success_statuses:
        if _is_valid_local_pdf(file):
            return StageResult(
                task_id=str(input_row.get("task_id", "")),
                doi=report_row.get("doi", "") or str(input_row.get("doi", "")),
                title=report_row.get("title", "") or str(input_row.get("title", "")),
                status="downloaded",
                file=file,
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


def _is_valid_local_pdf(file: str) -> bool:
    if not file or file.lower().startswith(("http://", "https://")):
        return False
    try:
        path = Path(file).expanduser()
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


def _exception_reason(exc: Exception) -> str:
    return f"stage_exception_{type(exc).__name__}"
