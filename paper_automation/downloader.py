from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Iterator
from urllib.error import URLError
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, urljoin
from urllib.request import Request, urlopen

from .models import DownloadResponse, DownloadResult, PdfCandidate
from .pdf_validation import is_pdf_bytes, is_valid_pdf
from .artifact_store import (
    DEFAULT_PDF_MAX_BYTES,
    STREAM_CHUNK_SIZE,
    publish_pdf_bytes_atomic,
    publish_pdf_stream_atomic,
)


BytesGetter = Callable[[str, dict[str, str] | None, int], DownloadResponse]
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}

_MDPI_HOST_RE = re.compile(r"(^|\.)mdpi\.com$", re.I)
_DOI_PREFIX_MDPI = "10.3390/"
_INTERSTITIAL_MARKERS = (
    "akamai/interstitial",
    "_sec/verify",
    "bm-verify",
    "triggerInterstitialChallenge",
)


def download_pdf(
    candidate: PdfCandidate,
    path: str | Path,
    http_bytes: BytesGetter | None = None,
    overwrite: bool = False,
    retries: int = 2,
    timeout: int = 30,
    delay_seconds: float = 1.0,
    max_bytes: int = DEFAULT_PDF_MAX_BYTES,
) -> DownloadResult:
    target = Path(path)
    if target.exists() and not overwrite:
        if is_valid_pdf(target):
            return DownloadResult("skipped", str(target), "file_exists")

    urls = expand_download_urls(candidate.url)
    last_error = ""
    for url in urls:
        headers = headers_for_url(url)
        for attempt in range(retries + 1):
            if attempt:
                time.sleep(delay_seconds)
            try:
                if http_bytes is None:
                    published = _download_pdf_stream(
                        url,
                        headers,
                        timeout,
                        target,
                        max_bytes=max_bytes,
                    )
                    return DownloadResult("downloaded", str(published), "")
                response = http_bytes(url, headers, timeout)
            except Exception as exc:
                last_error = str(exc)
                # Try next URL form on hard client/server blocks.
                if _is_hard_block_error(last_error):
                    break
                continue
            if _is_pdf_response(response):
                try:
                    published = publish_pdf_bytes_atomic(
                        response.content,
                        target.parent,
                        target.name,
                        max_bytes=max_bytes,
                    )
                except (OSError, ValueError) as exc:
                    last_error = str(exc) or type(exc).__name__
                    continue
                return DownloadResult("downloaded", str(published), "")
            last_error = "response_not_pdf"
            # Non-PDF body on MDPI often means bot HTML; try next variant.
            if is_mdpi_url(url):
                break

    return DownloadResult("failed", "", last_error or "download_failed")


def _download_pdf_stream(
    url: str,
    headers: dict[str, str],
    timeout: int,
    target: Path,
    *,
    max_bytes: int,
) -> Path:
    if is_mdpi_url(url) or _doi_from_url(url).startswith(_DOI_PREFIX_MDPI):
        try:
            return _download_pdf_stream_mdpi(
                url,
                headers,
                timeout,
                target,
                max_bytes=max_bytes,
            )
        except (ImportError, ModuleNotFoundError):
            pass
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        content_length = _content_length(response.headers)
        return publish_pdf_stream_atomic(
            _iter_reader(response),
            target.parent,
            target.name,
            content_length=content_length,
            max_bytes=max_bytes,
        )


def _download_pdf_stream_mdpi(
    url: str,
    headers: dict[str, str],
    timeout: int,
    target: Path,
    *,
    max_bytes: int,
) -> Path:
    from curl_cffi import requests as cf_requests  # type: ignore

    session = cf_requests.Session(impersonate="chrome124")
    response = session.get(
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=True,
        stream=True,
    )
    try:
        if response.status_code >= 400:
            raise URLError(f"HTTP Error {response.status_code}")
        iterator = iter(response.iter_content(chunk_size=STREAM_CHUNK_SIZE))
        first = next(iterator, b"") or b""
        if bytes(first).lstrip().startswith(b"%PDF-"):
            return publish_pdf_stream_atomic(
                _prepend_chunk(bytes(first), iterator),
                target.parent,
                target.name,
                content_length=_content_length(response.headers),
                max_bytes=max_bytes,
            )

        # MDPI's Akamai challenge is small HTML.  Keep only this non-PDF body
        # bounded; successful PDFs never become one in-memory bytes object.
        html_limit = min(max_bytes, 2 * 1024 * 1024)
        body = bytearray(first)
        for chunk in iterator:
            body.extend(chunk or b"")
            if len(body) > html_limit:
                raise ValueError("not_pdf_response")
        text = bytes(body).decode("utf-8", errors="replace")
        if not _looks_like_mdpi_interstitial(text) or not _solve_mdpi_interstitial(
            session, url, headers, text, timeout
        ):
            raise ValueError("not_pdf_response")
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    retry = session.get(
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=True,
        stream=True,
    )
    try:
        if retry.status_code >= 400:
            raise URLError(f"HTTP Error {retry.status_code}")
        return publish_pdf_stream_atomic(
            retry.iter_content(chunk_size=STREAM_CHUNK_SIZE),
            target.parent,
            target.name,
            content_length=_content_length(retry.headers),
            max_bytes=max_bytes,
        )
    finally:
        close = getattr(retry, "close", None)
        if callable(close):
            close()


def _iter_reader(response) -> Iterator[bytes]:
    while True:
        chunk = response.read(STREAM_CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


def _prepend_chunk(first: bytes, remainder) -> Iterator[bytes]:
    if first:
        yield first
    yield from remainder


def _content_length(headers: object) -> int | None:
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    value = getter("Content-Length") or getter("content-length")
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def expand_download_urls(url: str) -> list[str]:
    """Return ordered URL variants to try (original first)."""
    raw = (url or "").strip()
    if not raw:
        return []
    seen: set[str] = set()
    ordered: list[str] = []

    def add(u: str) -> None:
        key = u.strip()
        if not key or key in seen:
            return
        seen.add(key)
        ordered.append(key)

    add(raw)
    if is_mdpi_url(raw) or _doi_from_url(raw).startswith(_DOI_PREFIX_MDPI):
        for variant in mdpi_url_variants(raw):
            add(variant)
    return ordered


def mdpi_url_variants(url: str) -> list[str]:
    """Build alternate MDPI PDF URLs that often bypass versioned 403s."""
    variants: list[str] = []
    parsed = urlparse(url)
    # Drop tracking/version query.
    if parsed.query:
        clean_q = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() != "version"]
        variants.append(
            urlunparse(
                (
                    parsed.scheme or "https",
                    parsed.netloc,
                    parsed.path,
                    "",
                    urlencode(clean_q),
                    "",
                )
            )
        )
        # Path-only
        variants.append(
            urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path, "", "", ""))
        )

    doi = _doi_from_url(url)
    if doi.startswith(_DOI_PREFIX_MDPI):
        slug = doi  # 10.3390/xxx
        variants.extend(
            [
                f"https://www.mdpi.com/doi/pdf/{slug}",
                f"https://www.mdpi.com/doi/pdf/{slug}?download=1",
                f"https://mdpi.com/doi/pdf/{slug}",
            ]
        )
        # Common article path: /ISSN/vol/issue/article/pdf
        m = re.search(
            r"mdpi\.com/(\d{4}-\d{4})/(\d+)/(\d+)/(\d+)(?:/pdf)?",
            url,
            flags=re.I,
        )
        if m:
            issn, vol, issue, art = m.groups()
            variants.append(f"https://www.mdpi.com/{issn}/{vol}/{issue}/{art}/pdf")
            variants.append(f"https://www.mdpi.com/{issn}/{vol}/{issue}/{art}/pdf?download=1")

    # De-dupe preserving order
    out: list[str] = []
    seen: set[str] = set()
    for item in variants:
        if item not in seen and item != url:
            seen.add(item)
            out.append(item)
    return out


def headers_for_url(url: str) -> dict[str, str]:
    headers = dict(BROWSER_HEADERS)
    if is_mdpi_url(url) or _doi_from_url(url).startswith(_DOI_PREFIX_MDPI):
        doi = _doi_from_url(url)
        if doi.startswith(_DOI_PREFIX_MDPI):
            headers["Referer"] = f"https://www.mdpi.com/doi/{doi}"
        else:
            # Article HTML is usually path without trailing /pdf
            path = urlparse(url).path
            article_path = re.sub(r"/pdf/?$", "", path, flags=re.I)
            headers["Referer"] = f"https://www.mdpi.com{article_path}"
        headers["Accept"] = (
            "application/pdf,text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        )
        headers["Sec-Fetch-Dest"] = "document"
        headers["Sec-Fetch-Mode"] = "navigate"
        headers["Sec-Fetch-Site"] = "same-origin"
        headers["Upgrade-Insecure-Requests"] = "1"
    return headers


def is_mdpi_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return bool(host and _MDPI_HOST_RE.search(host))


def get_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> DownloadResponse:
    hdrs = headers or {}
    # Prefer TLS fingerprint impersonation for MDPI (often blocked with plain urllib).
    if is_mdpi_url(url) or _doi_from_url(url).startswith(_DOI_PREFIX_MDPI):
        try:
            return _get_bytes_mdpi_session(url, hdrs, timeout)
        except Exception:
            # Fall through to urllib; caller may try other URL variants.
            pass
    return _get_bytes_urllib(url, hdrs, timeout)


def _get_bytes_urllib(url: str, headers: dict[str, str], timeout: int) -> DownloadResponse:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        declared = _content_length(response.headers)
        if declared is not None and declared > DEFAULT_PDF_MAX_BYTES:
            raise ValueError("response_too_large")
        content = response.read(DEFAULT_PDF_MAX_BYTES + 1)
        content_type = response.headers.get("Content-Type", "")
        final_url = response.geturl()
    if len(content) > DEFAULT_PDF_MAX_BYTES:
        raise ValueError("response_too_large")
    return DownloadResponse(content, content_type, final_url)


def _get_bytes_mdpi_session(url: str, headers: dict[str, str], timeout: int) -> DownloadResponse:
    """curl_cffi + Akamai interstitial solve for MDPI PDF URLs."""
    from curl_cffi import requests as cf_requests  # type: ignore

    session = cf_requests.Session(impersonate="chrome124")
    response = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    if response.status_code >= 400:
        raise URLError(f"HTTP Error {response.status_code}")
    content = response.content or b""
    if len(content) > DEFAULT_PDF_MAX_BYTES:
        raise ValueError("response_too_large")
    content_type = str(response.headers.get("Content-Type") or "")
    final_url = str(getattr(response, "url", "") or url)

    if is_pdf_bytes(content):
        return DownloadResponse(content, content_type, final_url)

    # Bot interstitial (Akamai) — complete challenge then re-fetch PDF.
    text = ""
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    if _looks_like_mdpi_interstitial(text):
        if _solve_mdpi_interstitial(session, url, headers, text, timeout):
            response2 = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            if response2.status_code >= 400:
                raise URLError(f"HTTP Error {response2.status_code}")
            content2 = response2.content or b""
            if len(content2) > DEFAULT_PDF_MAX_BYTES:
                raise ValueError("response_too_large")
            ctype2 = str(response2.headers.get("Content-Type") or "")
            final2 = str(getattr(response2, "url", "") or url)
            return DownloadResponse(content2, ctype2, final2)

    return DownloadResponse(content, content_type, final_url)


def _looks_like_mdpi_interstitial(html_text: str) -> bool:
    lowered = (html_text or "").lower()
    return any(marker in lowered for marker in _INTERSTITIAL_MARKERS)


def _solve_mdpi_interstitial(
    session: object,
    pdf_url: str,
    headers: dict[str, str],
    html_text: str,
    timeout: int,
) -> bool:
    """Solve MDPI Akamai interstitial (bm-verify + trivial JS pow)."""
    i_match = re.search(r"var\s+i\s*=\s*(\d+)\s*;", html_text)
    num_match = re.search(
        r'Number\(\s*["\'](\d+)["\']\s*\+\s*["\'](\d+)["\']\s*\)',
        html_text,
    )
    bm_match = re.search(r'"bm-verify"\s*:\s*"([^"]+)"', html_text)
    if not (i_match and num_match and bm_match):
        return False
    i_val = int(i_match.group(1))
    pow_val = i_val + int(num_match.group(1) + num_match.group(2))
    bm_verify = bm_match.group(1)
    verify_url = urljoin(pdf_url, "/_sec/verify?provider=interstitial")
    verify_headers = dict(headers)
    verify_headers["Content-Type"] = "application/json"
    verify_headers["Origin"] = "https://www.mdpi.com"
    verify_headers["Referer"] = pdf_url
    payload = json.dumps({"bm-verify": bm_verify, "pow": pow_val})
    try:
        response = session.post(  # type: ignore[attr-defined]
            verify_url,
            headers=verify_headers,
            data=payload,
            timeout=timeout,
        )
    except Exception:
        return False
    if int(getattr(response, "status_code", 0) or 0) >= 400:
        return False
    # Expect {"reload": true} or similar.
    try:
        body = response.text if hasattr(response, "text") else ""
        if body and "reload" not in body.lower() and "location" not in body.lower():
            # Still may be ok; cookies might be set.
            pass
    except Exception:
        pass
    return True


def _is_pdf_response(response: DownloadResponse) -> bool:
    return is_pdf_bytes(response.content)


def _doi_from_url(url: str) -> str:
    text = (url or "").strip()
    m = re.search(r"(10\.\d{4,9}/[^\s?#]+)", text, flags=re.I)
    if not m:
        return ""
    return m.group(1).rstrip("/").lower()


def _is_hard_block_error(message: str) -> bool:
    lowered = (message or "").lower()
    return (
        "403" in lowered
        or "401" in lowered
        or "forbidden" in lowered
        or "unauthorized" in lowered
        or "429" in lowered
        or "404" in lowered
    )
