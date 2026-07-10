from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


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


def create_batch_paths(
    output_root: str | Path,
    run_name: str | None = None,
    now: datetime | None = None,
) -> BatchPaths:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    root = Path(output_root).expanduser().resolve() / (run_name or f"paper_batch_{stamp}")
    pdfs, reports, working = root / "pdfs", root / "reports", root / "working"
    for path in (root, pdfs, reports, working):
        path.mkdir(parents=True, exist_ok=True)
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


def copy_pdf_safely(source: str | Path, destination_dir: str | Path, filename: str) -> Path:
    source_path = Path(source).expanduser().resolve()
    if not is_valid_pdf(source_path):
        raise ValueError("not_pdf_response")
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / filename
    source_hash = _sha256(source_path)
    if target.exists():
        if is_valid_pdf(target) and _sha256(target) == source_hash:
            return target
        target = target.with_name(f"{target.stem}_{source_hash[:8]}{target.suffix}")
    shutil.copy2(source_path, target)
    return target
