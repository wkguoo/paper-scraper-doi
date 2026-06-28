from __future__ import annotations

import hashlib
import html
import os
import re
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse

from doi_batch_utils import SupplementDownloadRecord


SUPPLEMENT_HOSTS = (
    "ars.els-cdn.com",
    "els-cdn.com",
    "sciencedirect.com",
    "sciencedirectassets.com",
)
SUPPLEMENT_MARKERS = (
    "mmc",
    "supplement",
    "supplementary",
    "supplemental",
    "appendix",
    "video",
)
HTML_CONTENT_TYPES = ("text/html", "application/xhtml")
STREAM_CHUNK_SIZE = 8192
HTML_SNIFF_BYTES = 8192
CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "video/mp4": ".mp4",
}
SAFE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".zip",
    ".7z",
    ".rar",
    ".ppt",
    ".pptx",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".mp4",
    ".mov",
    ".avi",
}
TRACKING_OR_SIGNED_QUERY_KEYS = {
    "download",
    "dgcid",
    "cid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
    "x-amz-algorithm",
    "x-amz-credential",
    "x-amz-date",
    "x-amz-expires",
    "x-amz-security-token",
    "x-amz-signature",
    "x-amz-signedheaders",
    "awsaccesskeyid",
    "expires",
    "signature",
    "key-pair-id",
}


@dataclass(frozen=True)
class SupplementCandidate:
    url: str
    title: str = ""


class _SupplementLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._active_href = ""
        self._active_text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.meta_links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "a" and attr.get("href"):
            self._active_href = attr["href"]
            self._active_text = []
        if tag.lower() == "meta":
            name = (attr.get("name") or attr.get("property") or "").lower()
            content = attr.get("content") or ""
            if content and any(marker in name for marker in SUPPLEMENT_MARKERS):
                self.meta_links.append((content, name))

    def handle_data(self, data: str) -> None:
        if self._active_href:
            self._active_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._active_href:
            title = " ".join(part.strip() for part in self._active_text if part.strip())
            self.links.append((self._active_href, title))
            self._active_href = ""
            self._active_text = []


def extract_supplement_candidates(html_text: str, article_url: str) -> list[SupplementCandidate]:
    parser = _SupplementLinkParser()
    try:
        parser.feed(html_text or "")
    except Exception:
        return []

    candidates: list[SupplementCandidate] = []
    seen: set[str] = set()
    for href, title in [*parser.links, *parser.meta_links]:
        url = urljoin(article_url, html.unescape(href or "").strip())
        title = _clean_label(title)
        if not _is_supplement_link(url, title):
            continue
        key = _dedupe_key(url)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(SupplementCandidate(url=url, title=title or _title_from_url(url)))
    return candidates


def make_article_stem(idx: int, article: dict) -> str:
    authors = article.get("authors", "")
    if isinstance(authors, list):
        authors = "; ".join(str(author) for author in authors)
    first_author = "no-author"
    if authors:
        first = str(authors).split(";")[0].strip()
        if first:
            first_author = first.split(",")[0].strip().split()[0]

    year_match = re.search(r"\b(19|20)\d{2}\b", str(article.get("year") or article.get("date") or ""))
    year = year_match.group(0) if year_match else "undated"
    doi = str(article.get("doi") or "").lower().strip()
    pii = str(article.get("pii") or "").strip()
    title = str(article.get("title") or (f"DOI {doi}" if doi else "") or (f"PII {pii}" if pii else "") or "paper")
    safe_title = _sanitize_filename_part(title, max_length=80) or "paper"
    first_author = re.sub(r'[\\/*?:"<>|\s]+', "_", first_author).strip("_") or "no-author"
    hash_source = doi or pii or str(idx)
    doi_hash = hashlib.sha1(hash_source.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{year}_{first_author}_{safe_title}_{doi_hash}"


def make_supplement_filename(index: int, candidate: SupplementCandidate, content_type: str = "") -> str:
    ext = _extension_from_url(candidate.url) or _extension_from_content_type(content_type) or ".bin"
    return f"{_supplement_filename_base(index, candidate)}{ext}"


def download_supplements_for_article(
    *,
    article: dict,
    article_index: int,
    article_file: str,
    article_html: str,
    article_url: str,
    output_dir: str | Path,
    session,
    headers: dict[str, str] | None = None,
) -> list[SupplementDownloadRecord]:
    candidates = extract_supplement_candidates(article_html, article_url)
    if not candidates:
        return [
            SupplementDownloadRecord(
                doi=article.get("doi", ""),
                pii=article.get("pii", ""),
                article_title=article.get("title", ""),
                article_file=article_file,
                supplement_index=0,
                status="not_found",
                reason="未发现补充材料",
            )
        ]

    stem = make_article_stem(article_index, article)
    supplement_dir = Path(output_dir) / "supplements" / stem
    supplement_dir.mkdir(parents=True, exist_ok=True)
    records: list[SupplementDownloadRecord] = []
    request_headers = dict(headers or {})

    for index, candidate in enumerate(candidates, start=1):
        response = None
        content_type = ""
        temp_path: Path | None = None
        try:
            existing_path = _find_existing_supplement_file(supplement_dir, index, candidate, "")
            if existing_path is not None:
                relative_path = Path("supplements") / stem / existing_path.name
                records.append(
                    _record(
                        article,
                        article_file,
                        index,
                        candidate,
                        "skipped",
                        relative_path,
                        "",
                        existing_path.stat().st_size,
                        "文件已存在",
                    )
                )
                continue

            response = session.get(candidate.url, headers=request_headers, allow_redirects=True, timeout=60, stream=True)
            status_code = int(getattr(response, "status_code", 0) or 0)
            content_type = _response_content_type(response)
            filename = make_supplement_filename(index, candidate, content_type)
            relative_path = Path("supplements") / stem / filename
            target_path = supplement_dir / filename

            if target_path.is_file() and target_path.stat().st_size > 0:
                records.append(_record(article, article_file, index, candidate, "skipped", relative_path, content_type, target_path.stat().st_size, "文件已存在"))
                continue
            if status_code < 200 or status_code >= 400:
                records.append(_record(article, article_file, index, candidate, "failed", "", content_type, 0, f"HTTP {status_code}"))
                continue
            if _is_html_content_type(content_type):
                records.append(_record(article, article_file, index, candidate, "failed", "", content_type, 0, "非附件响应或登录页面"))
                continue

            temp_path = _make_unique_temp_path(supplement_dir, target_path)
            size_bytes = _stream_response_to_temp(response, temp_path)
            os.replace(temp_path, target_path)
            temp_path = None
            records.append(_record(article, article_file, index, candidate, "success", relative_path, content_type, size_bytes, ""))
        except Exception as exc:
            records.append(_record(article, article_file, index, candidate, "failed", "", content_type, 0, str(exc)))
        finally:
            if response is not None:
                _close_response(response)
            if temp_path is not None:
                _remove_file(temp_path)
    return records


def supplement_status_counts(records: list[SupplementDownloadRecord]) -> tuple[int, int, int, int]:
    success = sum(1 for record in records if record.status == "success")
    failed = sum(1 for record in records if record.status == "failed")
    skipped = sum(1 for record in records if record.status == "skipped")
    not_found = sum(1 for record in records if record.status == "not_found")
    return success, failed, skipped, not_found


def _record(
    article: dict,
    article_file: str,
    index: int,
    candidate: SupplementCandidate,
    status: str,
    relative_path: str | Path,
    content_type: str,
    size_bytes: int,
    reason: str,
) -> SupplementDownloadRecord:
    return SupplementDownloadRecord(
        doi=article.get("doi", ""),
        pii=article.get("pii", ""),
        article_title=article.get("title", ""),
        article_file=article_file,
        supplement_index=index,
        supplement_title=candidate.title,
        source_url=candidate.url,
        status=status,
        file=str(relative_path) if relative_path else "",
        content_type=content_type,
        size_bytes=size_bytes,
        reason=reason,
    )


def _is_supplement_link(url: str, title: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host or not any(host == allowed or host.endswith("." + allowed) for allowed in SUPPLEMENT_HOSTS):
        return False
    marker_text = f"{unquote(url).lower()} {title.lower()}"
    if "pdfft" in marker_text or "download pdf" in marker_text:
        return False
    return any(marker in marker_text for marker in SUPPLEMENT_MARKERS)


def _dedupe_key(url: str) -> str:
    parsed = urlparse(url)
    path = re.sub(r"/+", "/", parsed.path)
    query_pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        low_key = key.lower()
        if low_key in TRACKING_OR_SIGNED_QUERY_KEYS or low_key.startswith("utm_"):
            continue
        query_pairs.append((key, value))
    query = urlencode(sorted(query_pairs))
    return parsed._replace(netloc=parsed.netloc.lower(), path=path, query=query, fragment="").geturl().lower()


def _clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _sanitize_filename_part(value: str, max_length: int) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', " ", html.unescape(str(value or "")))
    safe = re.sub(r"\s+", " ", safe).strip()
    return safe[:max_length].rstrip(" .")


def _supplement_filename_base(index: int, candidate: SupplementCandidate) -> str:
    title = _sanitize_filename_part(candidate.title or _title_from_url(candidate.url), max_length=70)
    title = title or "Supplementary material"
    return f"S{index:02d}_{title}"


def _find_existing_supplement_file(
    supplement_dir: Path,
    index: int,
    candidate: SupplementCandidate,
    content_type: str,
) -> Path | None:
    filename = make_supplement_filename(index, candidate, content_type)
    target_path = supplement_dir / filename
    if target_path.is_file() and target_path.stat().st_size > 0:
        return target_path

    if _extension_from_url(candidate.url):
        return None

    prefix = _supplement_filename_base(index, candidate) + "."
    matches = sorted(
        path
        for path in supplement_dir.iterdir()
        if path.is_file() and path.stat().st_size > 0 and path.name.startswith(prefix) and not path.name.endswith(".tmp")
    )
    return matches[0] if matches else None


def _make_unique_temp_path(supplement_dir: Path, target_path: Path) -> Path:
    fd, name = tempfile.mkstemp(prefix=f".{target_path.stem}.", suffix=".tmp", dir=str(supplement_dir))
    os.close(fd)
    return Path(name)


def _title_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    name = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", name)
    name = re.sub(r"[-_]+", " ", name)
    return _sanitize_filename_part(name, max_length=70) or "Supplementary material"


def _extension_from_url(url: str) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    if suffix in SAFE_EXTENSIONS:
        return suffix
    return ""


def _extension_from_content_type(content_type: str) -> str:
    value = (content_type or "").split(";", 1)[0].strip().lower()
    return CONTENT_TYPE_EXTENSIONS.get(value, "")


def _response_content_type(response) -> str:
    headers = getattr(response, "headers", {}) or {}
    getter = getattr(headers, "get", None)
    if callable(getter):
        try:
            value = getter("content-type") or getter("Content-Type") or ""
            if value:
                return str(value).split(";", 1)[0].strip().lower()
        except Exception:
            pass
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == "content-type":
                return str(value).split(";", 1)[0].strip().lower()
    return ""


def _is_html_content_type(content_type: str) -> bool:
    low_content_type = (content_type or "").lower()
    return any(value in low_content_type for value in HTML_CONTENT_TYPES)


def _looks_like_html_response(body: bytes, content_type: str) -> bool:
    if _is_html_content_type(content_type):
        return True
    sample = body[:HTML_SNIFF_BYTES].lstrip().lower()
    html_markers = (
        b"<!doctype html",
        b"<html",
        b"<head",
        b"<body",
        b"<script",
        b"<form",
        b"</html>",
        b"</body>",
    )
    auth_markers = (
        b"<title>sign in",
        b"please login",
        b"please log in",
        b"login to continue",
        b"sign in",
        b"access denied",
        b"accessdenied",
        b"captcha",
        b"verify you are human",
        b"not authorized",
        b"unauthorized",
        b"forbidden",
    )
    return any(marker in sample for marker in html_markers) or any(marker in sample for marker in auth_markers)


def _stream_response_to_temp(response, temp_path: Path) -> int:
    pending = bytearray()
    sniff_done = False
    size_bytes = 0

    with temp_path.open("wb") as f:
        for chunk in response.iter_content(chunk_size=STREAM_CHUNK_SIZE):
            if not chunk:
                continue
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8", errors="ignore")
            if not sniff_done:
                remaining = HTML_SNIFF_BYTES - len(pending)
                pending.extend(chunk[:remaining])
                if _looks_like_html_response(bytes(pending), ""):
                    raise ValueError("非附件响应或登录页面")
                if len(pending) >= HTML_SNIFF_BYTES:
                    sniff_done = True
                    f.write(pending)
                    size_bytes += len(pending)
                    pending.clear()
                    rest = chunk[remaining:]
                    if rest:
                        f.write(rest)
                        size_bytes += len(rest)
                continue
            f.write(chunk)
            size_bytes += len(chunk)

        if not sniff_done:
            if not pending:
                raise ValueError("空响应")
            if _looks_like_html_response(bytes(pending), ""):
                raise ValueError("非附件响应或登录页面")
            f.write(pending)
            size_bytes += len(pending)

    return size_bytes


def _close_response(response) -> None:
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
