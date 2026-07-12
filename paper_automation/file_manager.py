from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .models import MetadataResult


WINDOWS_INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def ensure_output_dirs(output_dir: str | Path) -> dict[str, Path]:
    root = Path(output_dir)
    dirs = {
        "root": root,
        "pdfs": root / "pdfs",
        "metadata": root / "metadata",
        "logs": root / "logs",
        "failed": root / "failed",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def make_pdf_filename(metadata: MetadataResult, max_title_chars: int = 64) -> str:
    year = _safe_component(metadata.year or "undated", "undated")
    author = _safe_component(_first_author(metadata.authors), "unknown")
    title = _safe_component(metadata.title or metadata.query_title or "paper", "paper")
    short_title = "_".join(title.split())[:max_title_chars].strip("._") or "paper"
    digest_source = metadata.doi or metadata.title or metadata.query_title or str(metadata.source_index)
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:8]
    return f"{year}_{author}_{short_title}_{digest}.pdf"


def sanitize_filename(value: str) -> str:
    value = WINDOWS_INVALID_RE.sub(" ", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" .")
    reserved = {"con", "prn", "aux", "nul", "com1", "com2", "com3", "lpt1", "lpt2", "lpt3"}
    if value.lower() in reserved:
        value = f"{value}_file"
    return value


def _safe_component(value: str, fallback: str) -> str:
    cleaned = sanitize_filename(value)
    # Keep common Latin letters used in author names (ä, ö, ü, ñ, …).
    cleaned = re.sub(r"[^A-Za-z0-9\u00C0-\u024F\u4e00-\u9fff._ -]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ._-")
    return cleaned or fallback


def _first_author(authors: list[str]) -> str:
    if not authors:
        return "unknown"
    first = authors[0].strip()
    return first.split()[0] if first else "unknown"

