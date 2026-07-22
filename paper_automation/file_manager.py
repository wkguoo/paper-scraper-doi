from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .models import MetadataResult, PaperCandidate


WINDOWS_INVALID_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_LEADING_TABLE_INDEX_RE = re.compile(r"^\s*\|?\s*\d+\s*\|?\s*")


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


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MATHML_NOISE_RE = re.compile(
    r"(?i)\b(?:MathML|altimg|xmlns)\b|http-www-w3-org\S*"
)
_GREEK_MAP = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "μ": "u",
    "°": "deg",
    "–": "-",
    "—": "-",
    "−": "-",
    "′": "",
    "″": "",
}


def clean_title_for_filename(title: str) -> str:
    """Strip markdown/HTML/MathML/table junk so delivery names use a real paper title."""
    text = str(title or "").strip()
    if not text:
        return ""
    link = _MARKDOWN_LINK_RE.search(text)
    if link:
        text = link.group(1)
    text = _LEADING_TABLE_INDEX_RE.sub("", text)
    # HTML / MathML first so tag guts do not leak into the slug.
    text = _HTML_TAG_RE.sub(" ", text)
    text = _MATHML_NOISE_RE.sub(" ", text)
    # Common Crossref residues: iin-situ-i, Ti-sub2-sub, bare iin situ i
    text = re.sub(r"(?i)\bi\s*in[\s\-]?situ\s*i\b", "in-situ", text)
    text = re.sub(r"(?i)\biin[\s\-]?situ(?:[\s\-]?i)?\b", "in-situ", text)
    text = re.sub(r"(?i)\bin[\s\-]?situ[\s\-]?i\b", "in-situ", text)
    text = re.sub(r"(?i)\bin[\s\-]?situi\b", "in-situ", text)
    text = re.sub(r"(?i)[\-_]sub(\d+)[\-_]?sub", r"\1", text)
    text = re.sub(r"(?i)(?<![A-Za-z])sub(\d+)[\-]?sub(?![A-Za-z])", r"\1", text)
    text = re.sub(r"(?i)[\-_]sup(\d+)[\-_]?sup", r"\1", text)
    text = re.sub(r"(?i)(?<![A-Za-z])sup(\d+)[\-]?sup(?![A-Za-z])", r"\1", text)
    for src, dst in _GREEK_MAP.items():
        text = text.replace(src, dst)
    text = re.sub(r"[|*#>`]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-_|")
    return text


def needs_delivery_metadata(row: dict) -> bool:
    """True when year/author/title are missing or title looks like intake junk."""
    year = str(row.get("year", "") or "").strip()
    authors = str(row.get("authors", "") or "").strip()
    title = str(row.get("title", "") or row.get("input_title", "") or "").strip()
    cleaned = clean_title_for_filename(title)
    if not year or year in {"0000", "0"}:
        return True
    if not authors:
        return True
    if not cleaned:
        return True
    if cleaned != title and ("|" in title or "[" in title or "](" in title):
        return True
    return False


def enrich_row_metadata_for_delivery(
    row: dict,
    *,
    email: str = "",
    resolver: Callable[[PaperCandidate], MetadataResult] | None = None,
    metadata_cache_path: str | Path | None = None,
) -> dict:
    """Fill year/authors/title from Crossref when missing so delivery names are final.

    Delivery filenames must be chosen at publish time as 年份-作者-题名.pdf.
    Network lookup is best-effort; failures leave the row unchanged except title cleaning.
    """
    result = dict(row)
    raw_title = str(result.get("title", "") or result.get("input_title", "") or "")
    cleaned_title = clean_title_for_filename(raw_title)
    if cleaned_title and cleaned_title != raw_title:
        result["title"] = cleaned_title

    doi = str(result.get("doi", "") or result.get("input_doi", "") or "").strip()
    if not doi or not needs_delivery_metadata(result):
        return result

    try:
        if resolver is not None:
            metadata = resolver(
                PaperCandidate(
                    source_index=int(str(result.get("source_index", "") or "0") or 0),
                    raw_text=raw_title,
                    doi=doi,
                    title=cleaned_title or raw_title,
                )
            )
        else:
            from .metadata_resolver import MetadataResolver

            metadata = MetadataResolver(
                email=email,
                cache_path=metadata_cache_path,
            ).resolve_one(
                PaperCandidate(
                    source_index=int(str(result.get("source_index", "") or "0") or 0),
                    raw_text=raw_title,
                    doi=doi,
                    title=cleaned_title or raw_title,
                )
            )
    except Exception:
        return result

    if metadata.year and not str(result.get("year", "") or "").strip():
        result["year"] = str(metadata.year)
    if metadata.authors and not str(result.get("authors", "") or "").strip():
        result["authors"] = " | ".join(metadata.authors)
    if metadata.title:
        meta_title = clean_title_for_filename(metadata.title) or str(metadata.title)
        current = str(result.get("title", "") or "").strip()
        # Prefer Crossref title when intake title is empty, markdown/table junk,
        # or looks like an author list (common in messy MD/Excel exports).
        looks_like_authors = bool(
            current
            and not meta_title.casefold() == current.casefold()
            and (
                current.count(";") >= 2
                or current.count(",") >= 3
                or (len(current) < 80 and current.count(".") >= 2 and " " not in current[:20])
            )
        )
        polluted = (
            not current
            or "|" in current
            or "](" in current
            or (current.startswith("[") and "]" in current)
            or looks_like_authors
        )
        if polluted:
            result["title"] = meta_title
    if metadata.journal and not str(result.get("journal", "") or "").strip():
        result["journal"] = str(metadata.journal)
    if metadata.publisher and not str(result.get("publisher", "") or "").strip():
        result["publisher"] = str(metadata.publisher)
    if metadata.doi and not str(result.get("doi", "") or "").strip():
        result["doi"] = str(metadata.doi)
    return result


def make_pdf_filename(metadata: MetadataResult, max_title_chars: int = 80) -> str:
    """Final delivery name: 年份-作者-题名.pdf"""
    year = _safe_component(metadata.year or "0000", "0000")
    author = _safe_component(_first_author_surname(metadata.authors), "Unknown")
    title_src = clean_title_for_filename(metadata.title or metadata.query_title or "") or (
        metadata.title or metadata.query_title or "paper"
    )
    title = _safe_component(title_src, "paper")
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

