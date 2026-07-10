from __future__ import annotations

import csv
import errno
import hashlib
import inspect
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

if os.name == "nt":
    import msvcrt
else:
    import fcntl


_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
    "COM¹",
    "COM²",
    "COM³",
    "LPT¹",
    "LPT²",
    "LPT³",
}

_LOCK_POLL_SECONDS = 0.05
_STATE_REPLACE_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class BatchPaths:
    root: Path
    pdfs: Path
    reports: Path
    working: Path
    state: Path
    normalized_input: Path
    manual_retry: Path
    zotero_fallback: Path
    zotero_results: Path


NORMALIZED_FIELDS = [
    "task_id",
    "source_index",
    "input_doi",
    "input_title",
    "doi",
    "title",
    "authors",
    "journal",
    "year",
    "publisher",
    "status",
    "source",
    "file",
    "reason",
]

SUCCESS_STATUSES = {
    "oa_downloaded",
    "institutional_downloaded",
    "zotero_existing_pdf",
    "zotero_downloaded",
}
_STAGE_SUCCESS_STATUSES = {"downloaded", "oa_downloaded", "institutional_downloaded"}
_INSTITUTIONAL_SOURCES = {"sciencedirect", "non_elsevier", "institutional"}


@dataclass(frozen=True)
class BatchRunResult:
    paths: BatchPaths
    total_count: int
    success_count: int
    failed_count: int
    manual_retry_count: int
    zotero_fallback_count: int


def _validate_path_component(value: str, *, error: str, clean_spaces: bool = False) -> str:
    raw = str(value)
    path = Path(raw)
    if (
        not raw
        or path.is_absolute()
        or bool(path.drive)
        or "/" in raw
        or "\\" in raw
        or ".." in raw
        or any(character in _WINDOWS_INVALID_CHARS or ord(character) < 32 for character in raw)
    ):
        raise ValueError(error)

    cleaned = "_".join(raw.strip().split()) if clean_spaces else raw
    if (
        not cleaned
        or cleaned in {".", ".."}
        or cleaned != cleaned.rstrip(". ")
        or cleaned.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
    ):
        raise ValueError(error)
    return cleaned


def create_batch_paths(
    output_root: str | Path,
    run_name: str | None = None,
    now: datetime | None = None,
) -> BatchPaths:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    prefix = "paper_batch" if run_name is None else _validate_path_component(
        run_name,
        error="invalid_run_name",
        clean_spaces=True,
    )
    output = Path(output_root).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    base_name = f"{prefix}_{stamp}"
    counter = 1
    while True:
        name = base_name if counter == 1 else f"{base_name}_{counter}"
        root = output / name
        try:
            root.mkdir()
        except FileExistsError:
            counter += 1
        else:
            break

    pdfs, reports, working = root / "pdfs", root / "reports", root / "working"
    for path in (pdfs, reports, working):
        path.mkdir()
    return BatchPaths(
        root=root,
        pdfs=pdfs,
        reports=reports,
        working=working,
        state=working / "batch_state.json",
        normalized_input=working / "normalized_input.csv",
        manual_retry=working / "manual_retry.csv",
        zotero_fallback=working / "zotero_fallback.csv",
        zotero_results=working / "zotero_results.csv",
    )


def _state_path(run_dir: str | Path) -> Path:
    return Path(run_dir).expanduser().resolve() / "working" / "batch_state.json"


def _replace_state_file(temporary: Path, destination: Path) -> None:
    deadline = time.monotonic() + _STATE_REPLACE_TIMEOUT_SECONDS
    while True:
        try:
            os.replace(temporary, destination)
        except OSError as exc:
            retryable = os.name == "nt" and (
                isinstance(exc, PermissionError)
                or getattr(exc, "winerror", None) in {5, 32, 33}
            )
            remaining = deadline - time.monotonic()
            if not retryable or remaining <= 0:
                raise
            time.sleep(min(_LOCK_POLL_SECONDS, remaining))
        else:
            return


def _write_batch_state_file(path: Path, payload: dict) -> Path:
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    descriptor_open = True
    try:
        handle = os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n")
        descriptor_open = False
        with handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_state_file(temporary, path)
    finally:
        if descriptor_open:
            try:
                os.close(file_descriptor)
            except OSError:
                pass
        temporary.unlink(missing_ok=True)
    return path


def save_batch_state(paths: BatchPaths, payload: dict) -> Path:
    """Durably replace one snapshot; read-modify-write callers must hold the lock."""

    return _write_batch_state_file(paths.state, payload)


def load_batch_state(run_dir: str | Path) -> dict:
    """Read one snapshot; read-modify-write callers must hold ``batch_state_lock``."""

    path = _state_path(run_dir)
    return json.loads(path.read_text(encoding="utf-8"))


def _try_file_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_file_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _is_lock_contention(exc: OSError) -> bool:
    return (
        isinstance(exc, BlockingIOError)
        or exc.errno in {errno.EACCES, errno.EAGAIN}
        or getattr(exc, "winerror", None) in {32, 33}
    )


@contextmanager
def _file_lock(
    lock_path: Path,
    *,
    timeout: float,
    invalid_timeout_error: str,
    timeout_error: str,
) -> Iterator[None]:
    timeout_seconds = float(timeout)
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError(invalid_timeout_error)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    acquired = False
    try:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                _try_file_lock(handle)
            except OSError as exc:
                if not _is_lock_contention(exc):
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(timeout_error) from exc
                time.sleep(min(_LOCK_POLL_SECONDS, remaining))
            else:
                acquired = True
                break
        yield
    finally:
        try:
            if acquired:
                _release_file_lock(handle)
        finally:
            handle.close()


@contextmanager
def batch_state_lock(
    run_dir: str | Path,
    *,
    timeout: float = 10.0,
) -> Iterator[None]:
    """Exclusively lock one run's state; this context manager is not re-entrant."""

    lock_path = _state_path(run_dir).with_suffix(".lock")
    with _file_lock(
        lock_path,
        timeout=timeout,
        invalid_timeout_error="invalid_batch_state_lock_timeout",
        timeout_error="batch_state_lock_timeout",
    ):
        yield


def claim_manual_retry(
    run_dir: str | Path,
    *,
    timeout: float = 10.0,
    validate_before_claim: Callable[[dict], None] | None = None,
) -> tuple[bool, dict]:
    """Atomically claim a run's one allowed manual retry and return its state."""

    with batch_state_lock(run_dir, timeout=timeout):
        state = load_batch_state(run_dir)
        if state.get("manual_retry_used"):
            return False, state
        if validate_before_claim is not None:
            validate_before_claim(state)
        state["manual_retry_used"] = True
        _write_batch_state_file(_state_path(run_dir), state)
        return True, state


def is_valid_pdf(path: str | Path, minimum_size: int = 12) -> bool:
    target = Path(path)
    if not target.is_file() or target.stat().st_size < minimum_size:
        return False
    with target.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_pdf_content(path: Path, expected_hash: str) -> bool:
    return (
        not path.is_symlink()
        and is_valid_pdf(path)
        and _sha256(path) == expected_hash
    )


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


@contextmanager
def _pdf_publish_lock(destination: Path, *, timeout: float) -> Iterator[None]:
    with _file_lock(
        destination / ".pdf_publish.lock",
        timeout=timeout,
        invalid_timeout_error="invalid_pdf_publish_lock_timeout",
        timeout_error="pdf_publish_lock_timeout",
    ):
        yield


def _cleanup_stale_pdf_snapshots(destination: Path) -> None:
    # Snapshot creation also holds the destination lock, so any snapshot visible
    # to the current lock owner was abandoned by a process that no longer owns it.
    for snapshot in destination.glob(".pdf_snapshot_*.tmp"):
        snapshot.unlink(missing_ok=True)


def _publish_pdf_snapshot(snapshot: Path, target: Path) -> bool:
    try:
        os.link(snapshot, target)
    except FileExistsError:
        return False
    except OSError as exc:
        raise OSError(f"hard_link_publish_failed: {exc}") from exc
    return True


def _snapshot_pdf_source(source: Path, destination: Path) -> tuple[Path, str]:
    file_descriptor, snapshot_name = tempfile.mkstemp(
        prefix=".pdf_snapshot_",
        suffix=".tmp",
        dir=destination,
    )
    snapshot = Path(snapshot_name)
    digest = hashlib.sha256()
    descriptor_open = True
    try:
        snapshot_handle = os.fdopen(file_descriptor, "wb")
        descriptor_open = False
        with snapshot_handle:
            with source.open("rb") as source_handle:
                for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
                    snapshot_handle.write(chunk)
                    digest.update(chunk)
            snapshot_handle.flush()
            os.fsync(snapshot_handle.fileno())
        if not is_valid_pdf(snapshot):
            raise ValueError("not_pdf_response")
        return snapshot, digest.hexdigest()
    except BaseException:
        snapshot.unlink(missing_ok=True)
        raise
    finally:
        if descriptor_open:
            try:
                os.close(file_descriptor)
            except OSError:
                pass


def copy_pdf_safely(
    source: str | Path,
    destination_dir: str | Path,
    filename: str,
    *,
    lock_timeout: float = 10.0,
) -> Path:
    safe_filename = _validate_path_component(filename, error="invalid_filename")
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise ValueError("not_pdf_response")
    destination = Path(destination_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with _pdf_publish_lock(destination, timeout=lock_timeout):
        _cleanup_stale_pdf_snapshots(destination)
        snapshot = None
        try:
            snapshot, source_hash = _snapshot_pdf_source(source_path, destination)
            target = destination / safe_filename
            while True:
                if _path_exists(target):
                    if _same_pdf_content(target, source_hash):
                        return target
                    break
                if _publish_pdf_snapshot(snapshot, target):
                    return target

            counter = 1
            while True:
                suffix = "" if counter == 1 else f"_{counter}"
                candidate = target.with_name(
                    f"{target.stem}_{source_hash[:8]}{suffix}{target.suffix}"
                )
                if _path_exists(candidate):
                    if _same_pdf_content(candidate, source_hash):
                        return candidate
                    counter += 1
                    continue
                if _publish_pdf_snapshot(snapshot, candidate):
                    return candidate
        finally:
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)


def run_oa_stage(rows: list[dict], output_dir: Path, options: Any):
    """Late import keeps the Task 2 PDF helper free of a circular import."""

    from .batch_stages import run_oa_stage as stage

    return stage(rows, output_dir, options)


def run_sciencedirect_stage(input_path: Path, output_dir: Path, options: Any):
    from .batch_stages import run_sciencedirect_stage as stage

    return stage(input_path, output_dir, options)


def run_non_elsevier_stage(input_path: Path, output_dir: Path, options: Any):
    from .batch_stages import run_non_elsevier_stage as stage

    return stage(input_path, output_dir, options)


def _batch_options_type():
    from .batch_stages import BatchOptions

    return BatchOptions


def _stage_input_writer(rows: list[dict], path: Path) -> Path:
    from .batch_stages import write_stage_input

    return write_stage_input(rows, path)


def _split_institutional_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    from .batch_stages import split_institutional_rows

    return split_institutional_rows(rows)


def _needs_manual_retry(status: str, reason: str) -> bool:
    from .batch_stages import needs_manual_retry

    return needs_manual_retry(status, reason)


def _normalise_doi(value: object) -> str:
    from doi_batch_utils import clean_doi

    return clean_doi(str(value or "")).lower()


def _empty_normalized_row() -> dict[str, str]:
    return {field: "" for field in NORMALIZED_FIELDS}


def _normalise_row_mapping(row: object) -> dict:
    if is_dataclass(row):
        raw = asdict(row)
    elif isinstance(row, dict):
        raw = dict(row)
    else:
        raise ValueError("invalid_batch_row")
    result = _empty_normalized_row()
    result.update({key: value for key, value in raw.items() if key in result or key.startswith("_") or key == "fixture_pdf"})
    for field in NORMALIZED_FIELDS:
        result[field] = str(result.get(field, "") or "")
    return result


def _write_csv_rows(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=NORMALIZED_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in NORMALIZED_FIELDS})
    return path


def normalize_input(
    *,
    input_text: str | None,
    input_path: str | Path | None,
    paths: BatchPaths,
    options: Any,
) -> list[dict]:
    """Use the existing intake contract without ever modifying the source input."""

    if (input_text is None) == (input_path is None):
        raise ValueError("exactly_one_input_required")
    from paper_automation.parser import extract_dois
    from sd_institutional_skill import build_intake

    path_values = [] if input_path is None else [Path(input_path).expanduser().resolve()]
    intake = build_intake(
        texts=[] if input_text is None else [input_text],
        input_paths=path_values,
        folder_paths=[],
        output_dir=paths.working / "intake",
        resolve_metadata=True,
        resolve_title_only_files=True,
        min_confidence=0.65,
        email=str(getattr(options, "email", "") or ""),
    )

    rows: list[dict] = []
    seen_dois: set[str] = set()
    seen_titles: set[str] = set()
    for intake_row in intake.all_rows:
        raw = asdict(intake_row)
        title = str(raw.get("title", "") or "").strip()
        intake_status = str(raw.get("status", "") or "").strip().lower()
        if intake_status == "duplicate":
            continue
        extracted_dois: list[str] = []
        for field in ("raw_value", "input_doi", "doi"):
            for doi in extract_dois(raw.get(field, "")):
                normalized_doi = _normalise_doi(doi)
                if normalized_doi and normalized_doi not in extracted_dois:
                    extracted_dois.append(normalized_doi)

        if not extracted_dois:
            title_key = " ".join(title.lower().split())
            if title_key and title_key in seen_titles:
                continue
            if title_key:
                seen_titles.add(title_key)
            extracted_dois = [""]

        for doi in extracted_dois:
            if doi:
                if doi in seen_dois:
                    continue
                seen_dois.add(doi)
            is_pending = intake_status == "valid" and bool(doi)
            row = _empty_normalized_row()
            row.update({
                "source_index": str(raw.get("row_number", "") or ""),
                "input_doi": str(raw.get("input_doi", "") or ""),
                "input_title": str(raw.get("input_title", "") or ""),
                "doi": doi,
                "title": title,
                "authors": str(raw.get("authors", "") or ""),
                "journal": str(raw.get("journal", "") or ""),
                "year": str(raw.get("year", "") or ""),
                "status": "pending" if is_pending else "metadata_uncertain",
                "source": str(raw.get("source", "") or "input"),
                "reason": "" if is_pending else str(raw.get("reason", "") or "metadata_uncertain"),
            })
            rows.append(row)

    if not rows:
        raise ValueError("empty_input")
    for index, row in enumerate(rows, start=1):
        row["task_id"] = f"paper-{index:04d}"
    _write_csv_rows(paths.normalized_input, rows)
    return rows


def _is_successful_status(status: object) -> bool:
    value = str(status or "").strip().lower()
    return value in SUCCESS_STATUSES


def _is_terminal_status(status: object) -> bool:
    return _is_successful_status(status) or str(status or "").strip().lower() == "duplicate"


def _update_as_mapping(update: object) -> dict:
    result = _normalise_row_mapping(update)
    if not result["task_id"]:
        raise ValueError("gateway_task_id_missing")
    return result


def _validate_stage_updates(rows: list[dict], updates: object) -> list[dict]:
    if not isinstance(updates, list):
        raise ValueError("invalid_gateway_updates")
    known_ids = {str(row.get("task_id", "")) for row in rows}
    if len(known_ids) != len(rows) or "" in known_ids:
        raise ValueError("invalid_state_task_ids")
    normalized_updates: list[dict] = []
    seen_ids: set[str] = set()
    for update in updates:
        normalized = _update_as_mapping(update)
        task_id = normalized["task_id"]
        if task_id not in known_ids:
            raise ValueError("gateway_task_id_unknown")
        if task_id in seen_ids:
            raise ValueError("gateway_task_id_duplicate")
        seen_ids.add(task_id)
        normalized_updates.append(normalized)
    return normalized_updates


def _copy_successful_pdf(row: dict, paths: BatchPaths) -> dict:
    status = str(row.get("status", "") or "").strip().lower()
    if status not in _STAGE_SUCCESS_STATUSES:
        return row
    result = dict(row)
    if status == "downloaded":
        source = str(row.get("source", "") or "").strip().lower()
        if source == "oa":
            canonical_status = "oa_downloaded"
        elif source in _INSTITUTIONAL_SOURCES:
            canonical_status = "institutional_downloaded"
        else:
            result.update(
                status="invalid_download_source",
                file="",
                reason=f"invalid_download_source:{source or 'missing'}",
            )
            return result
    else:
        canonical_status = status
    source_file = str(row.get("file", "") or "").strip()
    source_path = Path(source_file).expanduser() if source_file else None
    try:
        valid_source = bool(
            source_path is not None
            and not source_path.is_symlink()
            and is_valid_pdf(source_path)
        )
    except OSError:
        valid_source = False
    if not valid_source:
        result.update(status="not_pdf_response", file="", reason="not_pdf_response")
        return result
    try:
        copied = copy_pdf_safely(source_path, paths.pdfs, f"{row['task_id']}.pdf")
    except (OSError, ValueError) as exc:
        result.update(
            status="not_pdf_response",
            file="",
            reason=f"not_pdf_response:{type(exc).__name__}",
        )
        return result
    result["status"] = canonical_status
    result["file"] = str(copied)
    result["reason"] = ""
    return result


def _merge_stage_rows(rows: list[dict], updates: object, paths: BatchPaths) -> list[dict]:
    normalized_updates = _validate_stage_updates(rows, updates)
    updates_by_id = {update["task_id"]: update for update in normalized_updates}
    merged_rows: list[dict] = []
    for existing in rows:
        task_id = str(existing.get("task_id", ""))
        update = updates_by_id.get(task_id)
        if update is None or _is_terminal_status(existing.get("status", "")):
            merged_rows.append(dict(existing))
            continue
        merged = dict(existing)
        merged.update(update)
        merged["task_id"] = task_id
        merged_rows.append(_copy_successful_pdf(merged, paths))
    return merged_rows


def _apply_stage_updates(state: dict, updates: object, paths: BatchPaths) -> None:
    normalized_updates = _validate_stage_updates(state["rows"], updates)
    for update in normalized_updates:
        state["rows"] = _merge_stage_rows(state["rows"], [update], paths)
        save_batch_state(paths, state)


def _required_task_ids(rows: list[dict]) -> list[str]:
    return [
        str(row.get("task_id", ""))
        for row in rows
        if str(row.get("status", "")).strip().lower() not in {"metadata_uncertain", "duplicate"}
        and not _is_successful_status(row.get("status", ""))
    ]


def _mark_required_failures(
    state: dict,
    paths: BatchPaths,
    task_ids: set[str],
    status: str,
    reason: str,
) -> None:
    updates = []
    for row in state["rows"]:
        task_id = str(row.get("task_id", ""))
        if task_id not in task_ids or _is_terminal_status(row.get("status", "")):
            continue
        updates.append({**row, "status": status, "file": "", "reason": reason})
    _apply_stage_updates(state, updates, paths)


def _accepts_on_updates(method: Callable[..., object]) -> bool:
    parameters = inspect.signature(method).parameters.values()
    return any(
        parameter.name == "on_updates" or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def _run_gateway_with_state(
    *,
    runner: object,
    method_name: str,
    rows: list[dict],
    paths: BatchPaths,
    options: Any,
    state: dict,
    required_ids: set[str],
) -> None:
    method = getattr(runner, method_name)
    callback_error: Exception | None = None

    def persist_updates(updates: list[dict]) -> None:
        nonlocal callback_error
        try:
            _apply_stage_updates(state, updates, paths)
        except Exception as exc:
            callback_error = exc
            raise

    try:
        if _accepts_on_updates(method):
            returned_updates = method(rows, paths, options, on_updates=persist_updates)
        else:
            returned_updates = method(rows, paths, options)
    except Exception as exc:
        if callback_error is exc or (
            isinstance(exc, ValueError)
            and str(exc).startswith(("gateway_task_id", "invalid_gateway_updates"))
        ):
            raise
        failure = f"gateway_exception_{type(exc).__name__}"
        _mark_required_failures(state, paths, required_ids, failure, failure)
        return

    normalized_updates = _validate_stage_updates(state["rows"], returned_updates)
    _apply_stage_updates(state, normalized_updates, paths)
    returned_ids = {update["task_id"] for update in normalized_updates}
    missing_ids = required_ids - returned_ids
    if missing_ids:
        _mark_required_failures(
            state,
            paths,
            missing_ids,
            "missing_stage_update",
            "missing_stage_update",
        )


def _pending_rows(rows: list[dict], *, manual_retry_used: bool) -> tuple[list[dict], list[dict]]:
    manual_rows: list[dict] = []
    fallback_rows: list[dict] = []
    for row in rows:
        if _is_terminal_status(row.get("status", "")):
            continue
        if not manual_retry_used and _needs_manual_retry(row.get("status", ""), row.get("reason", "")):
            manual_rows.append(row)
        else:
            fallback_rows.append(row)
    return manual_rows, fallback_rows


def _write_pending_files(paths: BatchPaths, rows: list[dict], *, manual_retry_used: bool = False) -> None:
    manual_rows, fallback_rows = _pending_rows(rows, manual_retry_used=manual_retry_used)
    _write_csv_rows(paths.manual_retry, manual_rows)
    _write_csv_rows(paths.zotero_fallback, fallback_rows)


def _serialize_options(options: Any) -> dict[str, object]:
    if not is_dataclass(options):
        raise ValueError("invalid_batch_options")
    return _validate_options_data(asdict(options))


def _validate_options_data(data: object) -> dict[str, object]:
    expected_fields = {
        "email",
        "cookies",
        "browser_exe",
        "login_wait_seconds",
        "debug_port",
        "throttle_seconds",
    }
    if not isinstance(data, dict) or set(data) != expected_fields:
        raise ValueError("invalid_batch_options")
    if not isinstance(data["email"], str) or not isinstance(data["browser_exe"], str):
        raise ValueError("invalid_batch_options")
    if not isinstance(data["cookies"], str):
        raise ValueError("cookies_must_be_path")
    cookie_path = data["cookies"].strip()
    lowered_cookie = cookie_path.lower()
    if cookie_path and (
        any(character in cookie_path for character in ("\r", "\n", "=", ";"))
        or "cookie:" in lowered_cookie
        or "://" in cookie_path
        or cookie_path.lstrip().startswith(("{", "["))
        or Path(cookie_path).suffix.lower() != ".json"
    ):
        raise ValueError("cookies_must_be_path")

    login_wait_seconds = data["login_wait_seconds"]
    if type(login_wait_seconds) is not int or login_wait_seconds < 0:
        raise ValueError("invalid_login_wait_seconds")
    debug_port = data["debug_port"]
    if type(debug_port) is not int or not 1 <= debug_port <= 65535:
        raise ValueError("invalid_debug_port")
    throttle_seconds = data["throttle_seconds"]
    if (
        isinstance(throttle_seconds, bool)
        or not isinstance(throttle_seconds, (int, float))
        or not math.isfinite(float(throttle_seconds))
        or float(throttle_seconds) < 0
    ):
        raise ValueError("invalid_throttle_seconds")
    return {
        "email": data["email"],
        "cookies": cookie_path,
        "browser_exe": data["browser_exe"],
        "login_wait_seconds": login_wait_seconds,
        "debug_port": debug_port,
        "throttle_seconds": float(throttle_seconds),
    }


def _options_from_state(state: dict):
    saved = state.get("options")
    try:
        validated = _validate_options_data(saved)
    except ValueError as exc:
        raise ValueError("invalid_batch_state_options") from exc
    return _batch_options_type()(**validated)


def _validate_state(state: object) -> dict:
    if not isinstance(state, dict):
        raise ValueError("invalid_batch_state")
    if state.get("version") != 1 or not isinstance(state.get("run_dir"), str):
        raise ValueError("invalid_batch_state")
    if not isinstance(state.get("manual_retry_used"), bool) or not isinstance(state.get("rows"), list):
        raise ValueError("invalid_batch_state")
    _validate_stage_updates([_normalise_row_mapping(row) for row in state["rows"]], [])
    _options_from_state(state)
    return state


def _paths_from_run_dir(run_dir: str | Path) -> BatchPaths:
    root = Path(run_dir).expanduser().resolve()
    working = root / "working"
    return BatchPaths(
        root=root,
        pdfs=root / "pdfs",
        reports=root / "reports",
        working=working,
        state=working / "batch_state.json",
        normalized_input=working / "normalized_input.csv",
        manual_retry=working / "manual_retry.csv",
        zotero_fallback=working / "zotero_fallback.csv",
        zotero_results=working / "zotero_results.csv",
    )


def _read_csv_rows(path: Path) -> list[dict]:
    if not path.is_file():
        raise ValueError("pending_file_missing")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return [{key: str(value or "") for key, value in row.items()} for row in csv.DictReader(handle)]


def _validate_manual_retry_preclaim(state: dict, paths: BatchPaths) -> list[dict]:
    _validate_state(state)
    if not paths.manual_retry.is_file():
        raise ValueError("manual_retry_file_missing")
    with paths.manual_retry.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        if not set(NORMALIZED_FIELDS).issubset(fieldnames):
            raise ValueError("manual_retry_fields_invalid")
        rows = [{key: str(value or "") for key, value in row.items()} for row in reader]

    state_by_id = {str(row.get("task_id", "")): row for row in state["rows"]}
    seen_ids: set[str] = set()
    for row in rows:
        task_id = row.get("task_id", "")
        if not task_id or task_id in seen_ids:
            raise ValueError("manual_retry_task_id_invalid")
        seen_ids.add(task_id)
        state_row = state_by_id.get(task_id)
        if state_row is None:
            raise ValueError("manual_retry_unknown_task_id")
        if not _needs_manual_retry(row.get("status", ""), row.get("reason", "")):
            raise ValueError("manual_retry_status_invalid")
        if not _needs_manual_retry(state_row.get("status", ""), state_row.get("reason", "")):
            raise ValueError("manual_retry_state_not_pending")
    return rows


def write_final_reports(paths: BatchPaths, rows: list[dict]) -> None:
    """Minimal Task 4 reports; Task 5 may extend this interface for Zotero reconciliation."""

    _write_csv_rows(paths.reports / "batch_status.csv", rows)
    summary = {
        "total_count": len(rows),
        "success_count": sum(1 for row in rows if _is_successful_status(row.get("status", ""))),
        "failed_count": sum(1 for row in rows if not _is_terminal_status(row.get("status", ""))),
    }
    (paths.reports / "batch_status.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _result_from_state(paths: BatchPaths, state: dict) -> BatchRunResult:
    rows = state["rows"]
    manual_rows, fallback_rows = _pending_rows(
        rows,
        manual_retry_used=bool(state.get("manual_retry_used")),
    )
    return BatchRunResult(
        paths=paths,
        total_count=len(rows),
        success_count=sum(1 for row in rows if _is_successful_status(row.get("status", ""))),
        failed_count=sum(1 for row in rows if not _is_terminal_status(row.get("status", ""))),
        manual_retry_count=len(manual_rows),
        zotero_fallback_count=len(fallback_rows),
    )


class DefaultStageGateway:
    def run_initial(
        self,
        rows: list[dict],
        paths: BatchPaths,
        options: Any,
        *,
        on_updates: Callable[[list[dict]], None] | None = None,
    ) -> list[dict]:
        runnable = [dict(row) for row in rows if str(row.get("status", "")).lower() == "pending"]
        if not runnable:
            return []
        oa_updates = [_update_as_mapping(row) for row in run_oa_stage(runnable, paths.reports, options)]
        if on_updates is not None:
            on_updates(oa_updates)
        after_oa = _merge_stage_rows(rows, oa_updates, paths)
        runnable_ids = {str(row.get("task_id", "")) for row in runnable}
        unresolved = [
            row for row in after_oa
            if str(row.get("task_id", "")) in runnable_ids
            and not _is_terminal_status(row.get("status", ""))
        ]
        science_direct, other = _split_institutional_rows(unresolved)
        unresolved_ids = {str(row.get("task_id", "")) for row in unresolved}
        updates = [
            update for update in oa_updates
            if update["task_id"] not in unresolved_ids
        ]
        if science_direct:
            stage_input = _stage_input_writer(science_direct, paths.working / "sciencedirect_input.csv")
            stage_updates = [_update_as_mapping(row) for row in run_sciencedirect_stage(stage_input, paths.reports, options)]
            if on_updates is not None:
                on_updates(stage_updates)
            updates.extend(stage_updates)
        if other:
            stage_input = _stage_input_writer(other, paths.working / "non_elsevier_input.csv")
            stage_updates = [_update_as_mapping(row) for row in run_non_elsevier_stage(stage_input, paths.reports, options)]
            if on_updates is not None:
                on_updates(stage_updates)
            updates.extend(stage_updates)
        return updates

    def run_retry(
        self,
        rows: list[dict],
        paths: BatchPaths,
        options: Any,
        *,
        on_updates: Callable[[list[dict]], None] | None = None,
    ) -> list[dict]:
        manual_rows = [
            row for row in rows
            if _needs_manual_retry(row.get("status", ""), row.get("reason", ""))
        ]
        science_direct, other = _split_institutional_rows(manual_rows)
        updates: list[dict] = []
        if science_direct:
            stage_input = _stage_input_writer(science_direct, paths.working / "sciencedirect_retry_input.csv")
            stage_updates = [_update_as_mapping(row) for row in run_sciencedirect_stage(stage_input, paths.reports, options)]
            if on_updates is not None:
                on_updates(stage_updates)
            updates.extend(stage_updates)
        if other:
            stage_input = _stage_input_writer(other, paths.working / "non_elsevier_retry_input.csv")
            stage_updates = [_update_as_mapping(row) for row in run_non_elsevier_stage(stage_input, paths.reports, options)]
            if on_updates is not None:
                on_updates(stage_updates)
            updates.extend(stage_updates)
        return updates


def start_batch(
    *,
    input_text: str | None,
    input_path: str | Path | None,
    output_root: str | Path,
    run_name: str | None = None,
    options: Any | None = None,
    gateway=None,
    normalizer=None,
    now: datetime | None = None,
) -> BatchRunResult:
    if (input_text is None) == (input_path is None):
        raise ValueError("exactly_one_input_required")
    selected_options = options or _batch_options_type()()
    serialized_options = _serialize_options(selected_options)
    paths = create_batch_paths(output_root, run_name=run_name, now=now)
    normalize = normalizer or normalize_input
    rows = [_normalise_row_mapping(row) for row in normalize(
        input_text=input_text,
        input_path=input_path,
        paths=paths,
        options=selected_options,
    )]
    _validate_stage_updates(rows, [])
    _write_csv_rows(paths.normalized_input, rows)
    state = {
        "version": 1,
        "run_dir": str(paths.root),
        "manual_retry_used": False,
        "options": serialized_options,
        "rows": rows,
    }
    save_batch_state(paths, state)
    runner = gateway or DefaultStageGateway()
    _run_gateway_with_state(
        runner=runner,
        method_name="run_initial",
        rows=rows,
        paths=paths,
        options=selected_options,
        state=state,
        required_ids=set(_required_task_ids(rows)),
    )
    _write_pending_files(paths, state["rows"])
    write_final_reports(paths, state["rows"])
    return _result_from_state(paths, state)


def resume_batch(
    run_dir: str | Path,
    *,
    gateway=None,
    options: Any | None = None,
) -> BatchRunResult:
    paths = _paths_from_run_dir(run_dir)
    retry_csv_rows: list[dict] = []

    def validate_before_claim(state: dict) -> None:
        retry_csv_rows.extend(_validate_manual_retry_preclaim(state, paths))
        if options is not None:
            _serialize_options(options)

    claimed, state = claim_manual_retry(
        run_dir,
        validate_before_claim=validate_before_claim,
    )
    if not claimed:
        return _result_from_state(paths, state)
    selected_options = options or _options_from_state(state)
    retry_ids = {row.get("task_id", "") for row in retry_csv_rows}
    retry_rows = [row for row in state["rows"] if str(row.get("task_id", "")) in retry_ids]
    if retry_rows:
        runner = gateway or DefaultStageGateway()
        _run_gateway_with_state(
            runner=runner,
            method_name="run_retry",
            rows=retry_rows,
            paths=paths,
            options=selected_options,
            state=state,
            required_ids=set(retry_ids),
        )
    _write_pending_files(paths, state["rows"], manual_retry_used=True)
    write_final_reports(paths, state["rows"])
    return _result_from_state(paths, state)
