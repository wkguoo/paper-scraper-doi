"""Automatic Sci-Hub / Anna's Archive PDF fallback for failed DOI downloads.

Invoked after the normal institutional/OA download paths finish.  Walks every
``status == "failed"`` record and tries Sci-Hub first, then Anna's Archive.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

from .downloader import BROWSER_HEADERS, get_bytes

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_SCIHUB_ENV = os.environ.get("SCIHUB_DOMAINS", "").strip()
SCIHUB_DOMAINS: tuple[str, ...] = tuple(
    d.strip() for d in (_SCIHUB_ENV.split(",") if _SCIHUB_ENV else
                        ["sci-hub.se", "sci-hub.ru", "sci-hub.st"])
    if d.strip()
)

ANNAS_ARCHIVE_BASE = "https://annas-archive.org"
INTER_REQUEST_DELAY = 5.0   # seconds between Sci-Hub requests
REQUEST_TIMEOUT = 45        # seconds per HTTP call

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class FallbackResult:
    success: bool
    source: str          # "scihub", "annas_archive", or ""
    source_url: str      # the URL that actually produced the PDF
    reason: str          # empty on success


BytesGetter = Callable[[str, dict[str, str] | None, int], object]

# ---------------------------------------------------------------------------
# Sci-Hub
# ---------------------------------------------------------------------------

_IFRAME_SRC = re.compile(r'<iframe[^>]+src\s*=\s*["\']([^"\']+)', re.IGNORECASE)
_EMBED_SRC = re.compile(r'<embed[^>]+src\s*=\s*["\']([^"\']+)', re.IGNORECASE)
_PDF_LINK = re.compile(r'https?://[^\s"\'<>]+\.pdf(?:/[^\s"\'<>]*)?(?=[\s"\'<>])', re.IGNORECASE)


def _scrape_scihub_pdf_url(html: str, base_url: str) -> str | None:
    """Extract the PDF URL from a Sci-Hub article page."""
    # 1. Try <iframe> — most common pattern
    for pattern in (_IFRAME_SRC, _EMBED_SRC):
        match = pattern.search(html)
        if match:
            src = match.group(1)
            # Handle protocol-relative URLs (//domain/...)
            if src.startswith("//"):
                src = "https:" + src
            else:
                src = urljoin(base_url, src)
            parsed = urlparse(src)
            if parsed.scheme in {"http", "https"} and ".pdf" in parsed.path.lower():
                return src
            # Sometimes the iframe src isn't the PDF itself — try as a secondary page
            return src if parsed.scheme in {"http", "https"} and parsed.netloc else None

    # 2. Bare PDF link in the page
    match = _PDF_LINK.search(html)
    if match:
        return match.group(0)

    return None


def try_scihub(
    doi: str,
    target: Path,
    *,
    http_bytes: BytesGetter | None = None,
    timeout: int = REQUEST_TIMEOUT,
) -> FallbackResult:
    """Attempt to download *doi* from Sci-Hub, write to *target*."""
    getter = http_bytes or get_bytes
    headers = dict(BROWSER_HEADERS)
    clean_doi = doi.strip().lower()

    for domain in SCIHUB_DOMAINS:
        scihub_url = f"https://{domain}/{clean_doi}"
        try:
            # Step 1 – fetch the Sci-Hub landing page
            response = getter(scihub_url, headers, timeout)
            html = getattr(response, "content", b"")
            if isinstance(html, bytes):
                html = html.decode("utf-8", errors="replace")

            # Step 2 – extract PDF URL
            pdf_url = _scrape_scihub_pdf_url(html, scihub_url)
            if not pdf_url:
                continue

            # Step 3 – download the PDF
            pdf_response = getter(pdf_url, headers, timeout)
            pdf_bytes = bytes(getattr(pdf_response, "content", b""))

            # Step 4 – validate
            if not pdf_bytes.startswith(b"%PDF"):
                continue

            # Step 5 – write
            target.parent.mkdir(parents=True, exist_ok=True)
            import tempfile
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{target.stem}.", suffix=".tmp", dir=str(target.parent)
            )
            tmp_path = Path(tmp_name)
            try:
                import os as _os
                with _os.fdopen(fd, "wb") as f:
                    f.write(pdf_bytes)
                    f.flush()
                    _os.fsync(f.fileno())
                if tmp_path.stat().st_size <= 0:
                    continue
                _os.replace(tmp_path, target)
            except Exception:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                continue

            return FallbackResult(success=True, source="scihub", source_url=scihub_url, reason="")

        except Exception:
            # Try next domain on any failure
            continue

    return FallbackResult(success=False, source="scihub", source_url="", reason="scithub_all_domains_failed")


# ---------------------------------------------------------------------------
# Anna's Archive
# ---------------------------------------------------------------------------

_AA_MD5_LINK = re.compile(r'/md5/([0-9a-f]{32})', re.IGNORECASE)
_AA_DOWNLOAD_URL = re.compile(r'https?://[^\s"\'<>]+\.(?:pdf|epub|djvu)[^\s"\'<>]*', re.IGNORECASE)


def _scrape_annas_pdf_url(html: str, base_url: str) -> str | None:
    """Extract a PDF download URL from an Anna's Archive search or detail page."""
    # Detail page – look for direct download links
    for match in _AA_DOWNLOAD_URL.finditer(html):
        url = match.group(0)
        if url.lower().endswith(".pdf"):
            return url
    return None


def try_annas_archive(
    doi: str,
    target: Path,
    *,
    http_bytes: BytesGetter | None = None,
    timeout: int = REQUEST_TIMEOUT,
) -> FallbackResult:
    """Attempt to download *doi* from Anna's Archive, write to *target*."""
    getter = http_bytes or get_bytes
    headers = dict(BROWSER_HEADERS)
    clean_doi = doi.strip().lower()

    try:
        # Step 1 – search
        search_url = f"{ANNAS_ARCHIVE_BASE}/search?q={clean_doi}"
        response = getter(search_url, headers, timeout)
        html = getattr(response, "content", b"")
        if isinstance(html, bytes):
            html = html.decode("utf-8", errors="replace")

        # Step 2 – find MD5 hash in search results
        md5_match = _AA_MD5_LINK.search(html)
        if md5_match:
            md5 = md5_match.group(1)
            detail_url = f"{ANNAS_ARCHIVE_BASE}/md5/{md5}"
            detail_response = getter(detail_url, headers, timeout)
            detail_html = getattr(detail_response, "content", b"")
            if isinstance(detail_html, bytes):
                detail_html = detail_html.decode("utf-8", errors="replace")

            pdf_url = _scrape_annas_pdf_url(detail_html, detail_url)
            if pdf_url:
                pdf_response = getter(pdf_url, headers, timeout)
                pdf_bytes = bytes(getattr(pdf_response, "content", b""))
                if pdf_bytes.startswith(b"%PDF"):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    import tempfile as _tmp
                    fd, tmp_name = _tmp.mkstemp(
                        prefix=f".{target.stem}.", suffix=".tmp", dir=str(target.parent)
                    )
                    tmp_path = Path(tmp_name)
                    try:
                        import os as _os
                        with _os.fdopen(fd, "wb") as f:
                            f.write(pdf_bytes)
                            f.flush()
                            _os.fsync(f.fileno())
                        if tmp_path.stat().st_size <= 0:
                            pass  # fall through to failure
                        else:
                            _os.replace(tmp_path, target)
                            return FallbackResult(
                                success=True, source="annas_archive",
                                source_url=detail_url, reason=""
                            )
                    except Exception:
                        try:
                            tmp_path.unlink(missing_ok=True)
                        except Exception:
                            pass

    except Exception:
        pass

    return FallbackResult(success=False, source="annas_archive", source_url="", reason="annas_archive_failed")


# ---------------------------------------------------------------------------
# Main entry point – called from doi_batch_utils / CLI
# ---------------------------------------------------------------------------

try:
    from doi_batch_utils import PdfDownloadRecord, write_pdf_bytes_atomic  # type: ignore[import]
except ImportError:
    PdfDownloadRecord = None   # type: ignore[assignment]
    write_pdf_bytes_atomic = None   # type: ignore[assignment]


def apply_auto_fallback(
    records: list,
    target_dir: Path,
    *,
    enable_scihub: bool = True,
    enable_annas: bool = True,
    throttle: float = INTER_REQUEST_DELAY,
) -> tuple[list, int, int]:
    """Walk every ``status == "failed"`` record and try Sci-Hub, then Anna's Archive.

    Returns ``(updated_records, success_delta, failed_delta)``.
    """
    failed_indices = [
        index for index, record in enumerate(records)
        if getattr(record, "status", "") == "failed"
    ]
    if not failed_indices:
        return records, 0, 0

    updated = list(records)
    success_count = 0
    fail_count = 0
    total = len(failed_indices)

    for seq, index in enumerate(failed_indices):
        record = updated[index]
        doi = getattr(record, "doi", "") or ""
        if not doi:
            continue

        # Determine PDF filename
        existing_file = getattr(record, "file", "") or ""
        stem = Path(existing_file).name if existing_file else f"scihub_{doi.replace('/', '_')}.pdf"
        target = target_dir / stem

        if target.exists():
            # Already obtained via fallback; mark success
            updated[index] = _with_status(record, "scihub_downloaded", "", "scihub", "")
            success_count += 1
            continue

        result = None

        if enable_scihub:
            result = try_scihub(doi, target)
            if result.success:
                updated[index] = _with_status(
                    record, "scihub_downloaded", stem,
                    result.source_url, "",
                )
                success_count += 1
                print(f"  [Sci-Hub] [{seq + 1}/{total}] ✓ {doi[:50]}")
                if seq + 1 < total:
                    time.sleep(throttle)
                continue

        if enable_annas:
            result = try_annas_archive(doi, target)
            if result.success:
                updated[index] = _with_status(
                    record, "scihub_downloaded", stem,
                    result.source_url, "",
                )
                success_count += 1
                print(f"  [Anna's]  [{seq + 1}/{total}] ✓ {doi[:50]}")
                if seq + 1 < total:
                    time.sleep(throttle)
                continue

        # Both failed — keep original "failed" status but note the attempt
        reason = getattr(record, "reason", "") or ""
        updated[index] = _with_status(
            record, "failed", getattr(record, "file", ""),
            "", f"{reason}; auto_fallback_exhausted",
        )
        fail_count += 1
        print(f"  [回退]   [{seq + 1}/{total}] ✗ {doi[:50]}")

        if seq + 1 < total:
            time.sleep(throttle)

    return updated, success_count, fail_count


def _with_status(
    record,
    status: str,
    file: str,
    source_url: str,
    reason: str,
):
    """Build a new PdfDownloadRecord with updated fallback fields."""
    return type(record)(
        doi=getattr(record, "doi", ""),
        pii=getattr(record, "pii", ""),
        title=getattr(record, "title", ""),
        status=status,
        file=file or getattr(record, "file", ""),
        reason=reason or getattr(record, "reason", ""),
        manual_pdf_url=source_url,
        manual_status=status,
        manual_reason=reason,
    )
