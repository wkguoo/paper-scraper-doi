from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

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
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
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
) -> tuple[bool, dict]:
    """Atomically claim a run's one allowed manual retry and return its state."""

    with batch_state_lock(run_dir, timeout=timeout):
        state = load_batch_state(run_dir)
        if state.get("manual_retry_used"):
            return False, state
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
