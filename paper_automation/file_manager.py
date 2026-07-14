from __future__ import annotations

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


def make_pdf_filename(metadata: MetadataResult, max_title_chars: int = 80) -> str:
    """Final delivery name: 年份-作者-题名.pdf"""
    year = _safe_component(metadata.year or "0000", "0000")
    author = _safe_component(_first_author_surname(metadata.authors), "Unknown")
    title = _safe_component(metadata.title or metadata.query_title or "paper", "paper")
    short_title = "-".join(title.split())[:max_title_chars].strip(".-_") or "paper"
    year = year.replace(" ", "-")
    author = author.replace(" ", "-")
    name = f"{year}-{author}-{short_title}.pdf"
    if len(name) > 180:
        keep = max(20, 180 - len(f"{year}-{author}-.pdf"))
        name = f"{year}-{author}-{short_title[:keep].rstrip('.-_')}.pdf"
    return name


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


def _first_author_surname(authors: list[str]) -> str:
    """Prefer family/surname for 年份-作者-题名 filenames.

    - ``Zhang, Wei`` → Zhang (comma form)
    - ``Zhang Wei`` → Zhang (Family Given, common in this project)
    """
    if not authors:
        return "Unknown"
    first = str(authors[0] or "").strip()
    if not first:
        return "Unknown"
    if "," in first:
        return first.split(",", 1)[0].strip() or "Unknown"
    parts = first.split()
    return parts[0] if parts else "Unknown"

