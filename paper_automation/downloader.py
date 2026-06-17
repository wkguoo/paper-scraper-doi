from __future__ import annotations

import time
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from .models import DownloadResponse, DownloadResult, PdfCandidate


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


def download_pdf(
    candidate: PdfCandidate,
    path: str | Path,
    http_bytes: BytesGetter | None = None,
    overwrite: bool = False,
    retries: int = 2,
    timeout: int = 30,
    delay_seconds: float = 1.0,
) -> DownloadResult:
    target = Path(path)
    if target.exists() and not overwrite:
        return DownloadResult("skipped", str(target), "file_exists")

    getter = http_bytes or get_bytes
    headers = dict(BROWSER_HEADERS)
    last_error = ""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(delay_seconds)
        try:
            response = getter(candidate.url, headers, timeout)
        except Exception as exc:
            last_error = str(exc)
            continue
        if _is_pdf_response(response):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(response.content)
            return DownloadResult("downloaded", str(target), "")
        last_error = "response_not_pdf"

    return DownloadResult("failed", "", last_error or "download_failed")


def get_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> DownloadResponse:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        content = response.read()
        content_type = response.headers.get("Content-Type", "")
        final_url = response.geturl()
    return DownloadResponse(content, content_type, final_url)


def _is_pdf_response(response: DownloadResponse) -> bool:
    content_type = response.content_type.lower()
    return "pdf" in content_type or response.content.startswith(b"%PDF")
