from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


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


def save_batch_state(paths: BatchPaths, payload: dict) -> Path:
    temporary = paths.state.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(paths.state)
    return paths.state


def load_batch_state(run_dir: str | Path) -> dict:
    path = Path(run_dir) / "working" / "batch_state.json"
    return json.loads(path.read_text(encoding="utf-8"))


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
    return is_valid_pdf(path) and _sha256(path) == expected_hash


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _copy_exclusively(source: Path, target: Path) -> bool:
    with source.open("rb") as source_handle:
        try:
            target_handle = target.open("xb")
        except FileExistsError:
            return False
        try:
            with target_handle:
                shutil.copyfileobj(source_handle, target_handle)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    try:
        shutil.copystat(source, target)
    except OSError:
        pass
    return True


def copy_pdf_safely(source: str | Path, destination_dir: str | Path, filename: str) -> Path:
    source_path = Path(source).expanduser().resolve()
    if not is_valid_pdf(source_path):
        raise ValueError("not_pdf_response")
    safe_filename = _validate_path_component(filename, error="invalid_filename")
    destination = Path(destination_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / safe_filename
    source_hash = _sha256(source_path)

    while True:
        if _path_exists(target):
            if _same_pdf_content(target, source_hash):
                return target
            break
        if _copy_exclusively(source_path, target):
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
        if _copy_exclusively(source_path, candidate):
            return candidate
