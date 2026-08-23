"""Safe Elsevier Article/Object Retrieval API client.

The client owns HTTP/XML handling and returns structured results.  It never
chooses a batch status, writes a delivery file, or logs credential values.
"""

from __future__ import annotations

import os
import socket
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from doi_batch_utils import clean_doi

from .pdf_validation import is_pdf_bytes


API_ROOT = "https://api.elsevier.com"
API_HOST = "api.elsevier.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
SNIFF_BYTES = 8192
SENSITIVE_HEADERS = ("X-ELS-APIKey", "X-ELS-Insttoken")
ELSEVIER_API_STATUSES = frozenset(
    {
        "success",
        "api_key_missing",
        "unauthorized",
        "not_entitled",
        "not_found",
        "rate_limited",
        "no_main_pdf",
        "invalid_pdf",
        "network_error",
    }
)
_SUPPLEMENT_MARKERS = ("mmc", "supplement", "supplementary", "supplemental", "appendix")
_SUPPLEMENT_TYPES = {"APPLICATION", "AUDIO", "VIDEO", "VIDEO-FLASH"}
_EXCLUDED_ATTACHMENT_TYPES = (
    "THUMBNAIL",
    "DOWNSAMPLED",
    "HIGH-RES",
    "WEB-PDF",
    "ALTIMG",
)
_ENV_SENTINEL = object()


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes = b""
    url: str = ""


@dataclass(frozen=True)
class StreamHttpResponse:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)
    size_bytes: int = 0
    url: str = ""
    invalid_content: bool = False


@dataclass(frozen=True)
class ElsevierAttachment:
    eid: str
    filename: str = ""
    mime_type: str = ""
    attachment_type: str = ""
    ref: str = ""
    size_bytes: int = 0

    @property
    def api_url(self) -> str:
        return f"{API_ROOT}/content/object/eid/{quote(self.eid, safe='')}"


@dataclass(frozen=True)
class ElsevierObjectResult:
    status: str
    http_status: int | None = None
    content_type: str = ""
    size_bytes: int = 0
    reason: str = ""


@dataclass(frozen=True)
class ElsevierSupplementListResult:
    status: str
    attachments: tuple[ElsevierAttachment, ...] = ()
    http_status: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class ElsevierApiResult:
    status: str
    doi: str
    http_status: int | None = None
    pii: str = ""
    attachment_eid: str = ""
    pdf_bytes: bytes = b""
    reason: str = ""
    full_xml_received: bool = False
    title: str = ""
    authors: tuple[str, ...] = ()
    journal: str = ""
    year: str = ""
    supplements: tuple[ElsevierAttachment, ...] = ()
    supplement_status: str = "not_requested"
    supplement_http_status: int | None = None
    supplement_reason: str = ""


@dataclass(frozen=True)
class ElsevierXmlResult:
    """Raw Elsevier Article Retrieval XML plus filename metadata."""

    status: str
    identifier_type: str
    identifier: str
    http_status: int | None = None
    content_type: str = ""
    xml_bytes: bytes = b""
    reason: str = ""
    doi: str = ""
    scopus_id: str = ""
    pii: str = ""
    title: str = ""
    authors: tuple[str, ...] = ()
    journal: str = ""
    year: str = ""


Transport = Callable[[str, Mapping[str, str], float], HttpResponse]
StreamTransport = Callable[[str, Mapping[str, str], float, BinaryIO], StreamHttpResponse]


class _CredentialSafeRedirectHandler(HTTPRedirectHandler):
    """Keep TLS and never forward Elsevier credentials to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        parsed = urlparse(newurl)
        if parsed.scheme.lower() != "https":
            raise URLError("insecure_redirect")
        if (parsed.hostname or "").lower() != API_HOST:
            sensitive = {header.casefold() for header in SENSITIVE_HEADERS}
            # urllib normalises header casing (for example APIKey -> Apikey),
            # so remove by case-insensitive comparison from both stores.
            for header_store in (redirected.headers, redirected.unredirected_hdrs):
                for header in list(header_store):
                    if str(header).casefold() in sensitive:
                        del header_store[header]
        return redirected


def _normalise_headers(headers: object) -> dict[str, str]:
    try:
        return {str(key): str(value) for key, value in dict(headers or {}).items()}
    except Exception:
        return {}


def _default_transport(url: str, headers: Mapping[str, str], timeout: float) -> HttpResponse:
    request = Request(url, headers=dict(headers), method="GET")
    opener = build_opener(_CredentialSafeRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            return HttpResponse(
                status=int(response.getcode() or 200),
                headers=_normalise_headers(response.headers),
                body=response.read(),
                url=str(response.geturl() or url),
            )
    except HTTPError as exc:
        try:
            body = exc.read(SNIFF_BYTES)
        except Exception:
            body = b""
        return HttpResponse(
            status=int(exc.code or 0),
            headers=_normalise_headers(exc.headers),
            body=body,
            url=str(exc.geturl() or url),
        )


def _default_stream_transport(
    url: str,
    headers: Mapping[str, str],
    timeout: float,
    sink: BinaryIO,
) -> StreamHttpResponse:
    request = Request(url, headers=dict(headers), method="GET")
    opener = build_opener(_CredentialSafeRedirectHandler())
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as exc:
        try:
            exc.close()
        except Exception:
            pass
        return StreamHttpResponse(
            status=int(exc.code or 0),
            headers=_normalise_headers(exc.headers),
            url=str(exc.geturl() or url),
        )

    with response:
        response_headers = _normalise_headers(response.headers)
        first = response.read(SNIFF_BYTES)
        content_type = _content_type(response_headers)
        if not first or _looks_like_html(first, content_type):
            return StreamHttpResponse(
                status=int(response.getcode() or 200),
                headers=response_headers,
                url=str(response.geturl() or url),
                invalid_content=True,
            )
        sink.write(first)
        size = len(first)
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            sink.write(chunk)
            size += len(chunk)
        return StreamHttpResponse(
            status=int(response.getcode() or 200),
            headers=response_headers,
            size_bytes=size,
            url=str(response.geturl() or url),
        )


class ElsevierApiClient:
    def __init__(
        self,
        *,
        api_key: str | object = _ENV_SENTINEL,
        insttoken: str | object = _ENV_SENTINEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: Transport | None = None,
        stream_transport: StreamTransport | None = None,
    ) -> None:
        self.api_key = (
            str(os.environ.get("ELSEVIER_API_KEY", "")).strip()
            if api_key is _ENV_SENTINEL
            else str(api_key or "").strip()
        )
        self.insttoken = (
            str(os.environ.get("ELSEVIER_INSTTOKEN", "")).strip()
            if insttoken is _ENV_SENTINEL
            else str(insttoken or "").strip()
        )
        self.timeout_seconds = float(timeout_seconds)
        self._transport = transport or _default_transport
        self._stream_transport = stream_transport

    @property
    def auth_mode(self) -> str:
        return "api_key+insttoken" if self.insttoken else "api_key"

    def retrieve_article_xml(
        self,
        identifier: str,
        *,
        identifier_type: str = "doi",
    ) -> ElsevierXmlResult:
        """Retrieve one raw ``view=FULL`` XML response without requesting a PDF."""

        kind = str(identifier_type or "").strip().lower()
        value = str(identifier or "").strip()
        if kind == "doi":
            value = clean_doi(value)
        elif kind == "scopus_id":
            if value.upper().startswith("SCOPUS_ID:"):
                value = value.split(":", 1)[1].strip()
            if value.lower().startswith("2-s2.0-"):
                value = value[len("2-s2.0-") :].strip()
        else:
            return ElsevierXmlResult(
                status="invalid_identifier",
                identifier_type=kind,
                identifier=value,
                reason="unsupported_identifier_type",
            )
        if not value:
            return ElsevierXmlResult(
                status="invalid_identifier",
                identifier_type=kind,
                identifier=value,
                reason="identifier_missing",
            )
        if not self.api_key:
            return ElsevierXmlResult(
                status="api_key_missing",
                identifier_type=kind,
                identifier=value,
                reason="api_key_missing",
            )

        article_url = (
            f"{API_ROOT}/content/article/{kind}/{quote(value, safe='')}?view=FULL"
        )
        response, error = self._request(article_url, accept="text/xml")
        if error:
            return ElsevierXmlResult(
                status=error[0],
                identifier_type=kind,
                identifier=value,
                http_status=error[1],
                reason=error[2],
                doi=value if kind == "doi" else "",
                scopus_id=value if kind == "scopus_id" else "",
            )
        assert response is not None

        content_type = _content_type(response.headers)
        if is_pdf_bytes(response.body):
            reason = "article_response_pdf"
        elif _looks_like_html(response.body, content_type):
            reason = "article_response_html"
        else:
            root = parse_full_text_xml(response.body)
            if root is not None:
                response_doi = _first_text(root, "doi")
                response_scopus_id = _first_text(root, "scopus-id")
                return ElsevierXmlResult(
                    status="success",
                    identifier_type=kind,
                    identifier=value,
                    http_status=response.status,
                    content_type=content_type,
                    xml_bytes=response.body,
                    doi=(value if kind == "doi" else response_doi),
                    scopus_id=(value if kind == "scopus_id" else response_scopus_id),
                    pii=_first_text(root, "pii"),
                    title=_first_text(root, "title"),
                    authors=_authors_from_xml(root),
                    journal=_first_text(root, "publicationName"),
                    year=_year_from_text(
                        _first_text(root, "coverDate")
                        or _first_text(root, "cover-date-year")
                    ),
                )
            reason = "article_response_invalid_xml"
        return ElsevierXmlResult(
            status="invalid_xml",
            identifier_type=kind,
            identifier=value,
            http_status=response.status,
            content_type=content_type,
            reason=reason,
            doi=value if kind == "doi" else "",
            scopus_id=value if kind == "scopus_id" else "",
        )

    def download_article(self, doi: str, *, include_supplements: bool = True) -> ElsevierApiResult:
        cleaned_doi = clean_doi(doi)
        if not self.api_key:
            return ElsevierApiResult(
                status="api_key_missing",
                doi=cleaned_doi,
                reason="api_key_missing",
            )

        article_url = f"{API_ROOT}/content/article/doi/{quote(cleaned_doi, safe='')}?view=FULL"
        response, error = self._request(article_url, accept="text/xml")
        if error:
            return ElsevierApiResult(status=error[0], doi=cleaned_doi, http_status=error[1], reason=error[2])
        assert response is not None

        if is_pdf_bytes(response.body):
            supplement_result = (
                self.list_supplements(cleaned_doi) if include_supplements else ElsevierSupplementListResult("not_requested")
            )
            return ElsevierApiResult(
                status="success",
                doi=cleaned_doi,
                http_status=response.status,
                pdf_bytes=response.body,
                reason="article_endpoint_returned_pdf",
                supplements=supplement_result.attachments,
                supplement_status=supplement_result.status,
                supplement_http_status=supplement_result.http_status,
                supplement_reason=supplement_result.reason,
            )

        content_type = _content_type(response.headers)
        if _looks_like_html(response.body, content_type):
            return ElsevierApiResult(
                status="invalid_pdf",
                doi=cleaned_doi,
                http_status=response.status,
                reason="article_response_html",
            )
        root = _parse_xml(response.body)
        if root is None:
            return ElsevierApiResult(
                status="invalid_pdf",
                doi=cleaned_doi,
                http_status=response.status,
                reason="article_response_invalid_xml",
            )

        pii = _first_text(root, "pii")
        title = _first_text(root, "title")
        journal = _first_text(root, "publicationName")
        year = _year_from_text(_first_text(root, "coverDate") or _first_text(root, "cover-date-year"))
        authors = _authors_from_xml(root)
        main_eid = find_main_pdf_eid(root)
        if not main_eid:
            return ElsevierApiResult(
                status="no_main_pdf",
                doi=cleaned_doi,
                http_status=response.status,
                pii=pii,
                reason="main_pdf_eid_missing",
                full_xml_received=True,
                title=title,
                authors=authors,
                journal=journal,
                year=year,
            )

        object_url = f"{API_ROOT}/content/object/eid/{quote(main_eid, safe='')}"
        pdf_response, pdf_error = self._request(object_url, accept="application/pdf")
        if pdf_error:
            return ElsevierApiResult(
                status=pdf_error[0],
                doi=cleaned_doi,
                http_status=pdf_error[1],
                pii=pii,
                attachment_eid=main_eid,
                reason=pdf_error[2],
                full_xml_received=True,
                title=title,
                authors=authors,
                journal=journal,
                year=year,
            )
        assert pdf_response is not None
        if not is_pdf_bytes(pdf_response.body):
            return ElsevierApiResult(
                status="invalid_pdf",
                doi=cleaned_doi,
                http_status=pdf_response.status,
                pii=pii,
                attachment_eid=main_eid,
                reason="object_response_invalid_pdf",
                full_xml_received=True,
                title=title,
                authors=authors,
                journal=journal,
                year=year,
            )

        supplement_result = (
            self.list_supplements(cleaned_doi, main_eid=main_eid)
            if include_supplements
            else ElsevierSupplementListResult("not_requested")
        )
        return ElsevierApiResult(
            status="success",
            doi=cleaned_doi,
            http_status=pdf_response.status,
            pii=pii,
            attachment_eid=main_eid,
            pdf_bytes=pdf_response.body,
            full_xml_received=True,
            title=title,
            authors=authors,
            journal=journal,
            year=year,
            supplements=supplement_result.attachments,
            supplement_status=supplement_result.status,
            supplement_http_status=supplement_result.http_status,
            supplement_reason=supplement_result.reason,
        )

    def list_supplements(self, doi: str, *, main_eid: str = "") -> ElsevierSupplementListResult:
        cleaned_doi = clean_doi(doi)
        if not self.api_key:
            return ElsevierSupplementListResult("api_key_missing", reason="api_key_missing")
        url = f"{API_ROOT}/content/object/doi/{quote(cleaned_doi, safe='')}?view=META"
        response, error = self._request(url, accept="text/xml")
        if error:
            return ElsevierSupplementListResult(error[0], http_status=error[1], reason=error[2])
        assert response is not None
        if _looks_like_html(response.body, _content_type(response.headers)):
            return ElsevierSupplementListResult(
                "invalid_pdf", http_status=response.status, reason="object_metadata_response_html"
            )
        root = _parse_xml(response.body)
        if root is None:
            return ElsevierSupplementListResult(
                "invalid_pdf", http_status=response.status, reason="object_metadata_invalid_xml"
            )
        attachments = tuple(_supplement_attachments(root, main_eid=main_eid))
        return ElsevierSupplementListResult(
            "success",
            attachments=attachments,
            http_status=response.status,
            reason="" if attachments else "no_supplement_objects",
        )

    def stream_attachment(self, attachment: ElsevierAttachment, sink: BinaryIO) -> ElsevierObjectResult:
        if not self.api_key:
            return ElsevierObjectResult(status="api_key_missing", reason="api_key_missing")
        headers = self._headers(attachment.mime_type or "*/*")
        try:
            if self._stream_transport is not None:
                response = self._stream_transport(
                    attachment.api_url,
                    headers,
                    self.timeout_seconds,
                    sink,
                )
            elif self._transport is not _default_transport:
                byte_response = self._transport(attachment.api_url, headers, self.timeout_seconds)
                invalid = not byte_response.body or _looks_like_html(
                    byte_response.body, _content_type(byte_response.headers)
                )
                if 200 <= byte_response.status < 300 and not invalid:
                    sink.write(byte_response.body)
                response = StreamHttpResponse(
                    status=byte_response.status,
                    headers=byte_response.headers,
                    size_bytes=len(byte_response.body) if not invalid else 0,
                    url=byte_response.url,
                    invalid_content=invalid,
                )
            else:
                response = _default_stream_transport(
                    attachment.api_url,
                    headers,
                    self.timeout_seconds,
                    sink,
                )
        except (TimeoutError, socket.timeout):
            return ElsevierObjectResult(status="network_error", reason="timeout")
        except (URLError, ssl.SSLError, OSError):
            return ElsevierObjectResult(status="network_error", reason="network_error")
        status = _status_for_http(response.status)
        if status != "success":
            return ElsevierObjectResult(
                status=status,
                http_status=response.status,
                content_type=_content_type(response.headers),
                reason=f"http_{response.status}",
            )
        if response.invalid_content or response.size_bytes <= 0:
            return ElsevierObjectResult(
                status="invalid_pdf",
                http_status=response.status,
                content_type=_content_type(response.headers),
                reason="attachment_response_invalid",
            )
        return ElsevierObjectResult(
            status="success",
            http_status=response.status,
            content_type=_content_type(response.headers),
            size_bytes=response.size_bytes,
        )

    def _request(
        self,
        url: str,
        *,
        accept: str,
    ) -> tuple[HttpResponse | None, tuple[str, int | None, str] | None]:
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() != API_HOST:
            return None, ("network_error", None, "unsafe_api_url")
        try:
            response = self._transport(url, self._headers(accept), self.timeout_seconds)
        except (TimeoutError, socket.timeout):
            return None, ("network_error", None, "timeout")
        except (URLError, ssl.SSLError, OSError):
            return None, ("network_error", None, "network_error")
        status = _status_for_http(response.status)
        if status != "success":
            return None, (status, response.status, f"http_{response.status}")
        return response, None

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "X-ELS-APIKey": self.api_key,
            "User-Agent": "paper-scraper-doi/elsevier-api",
        }
        if self.insttoken:
            headers["X-ELS-Insttoken"] = self.insttoken
        return headers


def find_main_pdf_eid(root: ElementTree.Element) -> str:
    candidates: list[tuple[int, str]] = []
    all_pdf_eids: list[str] = []
    for element in root.iter():
        local = _local_name(element.tag)
        if local not in {"web-pdf", "attachment"}:
            continue
        values = _descendant_values(element)
        eid = values.get("attachment-eid") or values.get("eid") or ""
        filename = values.get("filename") or values.get("attachment-filename") or ""
        attachment_type = (values.get("attachment-type") or values.get("type") or "").upper()
        purpose = (values.get("web-pdf-purpose") or "").upper()
        marker_text = f"{eid} {filename}".lower()
        if not eid or not _looks_like_pdf_identifier(eid, filename):
            continue
        if any(marker in marker_text for marker in _SUPPLEMENT_MARKERS):
            continue
        all_pdf_eids.append(eid)
        if local == "web-pdf" and purpose == "MAIN":
            candidates.append((0, eid))
        elif local == "web-pdf" and purpose in {"", "MAIN"}:
            candidates.append((1, eid))
        elif attachment_type in {"IMAGE-WEB-PDF", "AAM-PDF"} and "main" in marker_text:
            candidates.append((2, eid))
        elif eid.lower().endswith("-main.pdf") or filename.lower() == "main.pdf":
            candidates.append((3, eid))
    if candidates:
        best_priority = min(priority for priority, _ in candidates)
        best = list(dict.fromkeys(eid for priority, eid in candidates if priority == best_priority))
        return best[0] if len(best) == 1 else ""
    unique = list(dict.fromkeys(all_pdf_eids))
    return unique[0] if len(unique) == 1 and "main" in unique[0].lower() else ""


def _supplement_attachments(root: ElementTree.Element, *, main_eid: str) -> list[ElsevierAttachment]:
    attachments: list[ElsevierAttachment] = []
    seen: set[str] = set()
    main_key = main_eid.strip().casefold()
    for element in root.iter():
        if _local_name(element.tag) != "attachment":
            continue
        values = _descendant_values(element)
        eid = (values.get("eid") or values.get("attachment-eid") or "").strip()
        if not eid or eid.casefold() == main_key or eid.casefold() in seen:
            continue
        filename = (values.get("filename") or values.get("attachment-filename") or Path(eid).name).strip()
        mime_type = (
            values.get("mimetype")
            or values.get("mime-type")
            or values.get("attachment-mime-type")
            or ""
        ).strip().lower()
        attachment_type = (values.get("type") or values.get("attachment-type") or "").strip().upper()
        ref = (values.get("ref") or "").strip()
        marker_text = f"{eid} {filename} {ref}".lower()
        if _looks_like_main_pdf(marker_text, attachment_type):
            continue
        if any(token in attachment_type for token in _EXCLUDED_ATTACHMENT_TYPES):
            continue
        if mime_type in {"application/xml", "text/xml"} or filename.lower().endswith(".xml"):
            continue
        marked = any(marker in marker_text for marker in _SUPPLEMENT_MARKERS)
        media_object = mime_type.startswith(("audio/", "video/")) or attachment_type.startswith(("AUDIO", "VIDEO"))
        if attachment_type not in _SUPPLEMENT_TYPES and not media_object and not marked:
            continue
        try:
            size_bytes = int(
                values.get("size")
                or values.get("filesize")
                or values.get("attachment-size")
                or 0
            )
        except (TypeError, ValueError):
            size_bytes = 0
        attachments.append(
            ElsevierAttachment(
                eid=eid,
                filename=filename,
                mime_type=mime_type,
                attachment_type=attachment_type,
                ref=ref,
                size_bytes=max(0, size_bytes),
            )
        )
        seen.add(eid.casefold())
    return attachments


def _parse_xml(body: bytes) -> ElementTree.Element | None:
    sample = bytes(body or b"")
    upper = sample[:4096].upper()
    if not sample or b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        return None
    try:
        return ElementTree.fromstring(sample)
    except ElementTree.ParseError:
        return None


def parse_full_text_xml(body: bytes) -> ElementTree.Element | None:
    """Return the root only for a valid Article Retrieval full-text response."""

    root = _parse_xml(body)
    if root is None or _local_name(root.tag) != "full-text-retrieval-response":
        return None
    return root


def _local_name(tag: object) -> str:
    return str(tag or "").rsplit("}", 1)[-1].split(":", 1)[-1]


def _descendant_values(element: ElementTree.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element.iter():
        for name, raw_value in child.attrib.items():
            value = str(raw_value or "").strip()
            if value:
                values.setdefault(_local_name(name), value)
        text = " ".join(part.strip() for part in child.itertext() if part.strip()).strip()
        if text:
            values.setdefault(_local_name(child.tag), text)
    return values


def _first_text(root: ElementTree.Element, local_name: str) -> str:
    for element in root.iter():
        if _local_name(element.tag) != local_name:
            continue
        text = " ".join(part.strip() for part in element.itertext() if part.strip()).strip()
        if text:
            return text
    return ""


def _authors_from_xml(root: ElementTree.Element) -> tuple[str, ...]:
    authors: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) != "author":
            continue
        values = _descendant_values(element)
        surname = values.get("surname") or values.get("family-name") or ""
        given = values.get("given-name") or values.get("given-names") or ""
        name = " ".join(part for part in (surname, given) if part).strip()
        if name and name not in authors:
            authors.append(name)
    if authors:
        return tuple(authors)
    creators = []
    for element in root.iter():
        if _local_name(element.tag) != "creator":
            continue
        text = " ".join(part.strip() for part in element.itertext() if part.strip()).strip()
        if text and text not in creators:
            creators.append(text)
    return tuple(creators)


def _year_from_text(value: str) -> str:
    text = str(value or "")
    for index in range(max(0, len(text) - 3)):
        candidate = text[index : index + 4]
        if candidate.isdigit() and candidate.startswith(("19", "20")):
            return candidate
    return ""


def _looks_like_pdf_identifier(eid: str, filename: str) -> bool:
    return str(eid or "").lower().endswith(".pdf") or str(filename or "").lower().endswith(".pdf")


def _looks_like_main_pdf(marker_text: str, attachment_type: str) -> bool:
    return (
        attachment_type in {"IMAGE-WEB-PDF", "AAM-PDF"}
        or marker_text.endswith("main.pdf")
        or "-main.pdf" in marker_text
    )


def _content_type(headers: Mapping[str, str]) -> str:
    for key, value in dict(headers or {}).items():
        if str(key).lower() == "content-type":
            return str(value).split(";", 1)[0].strip().lower()
    return ""


def _looks_like_html(body: bytes, content_type: str) -> bool:
    if "text/html" in content_type.lower() or "application/xhtml" in content_type.lower():
        return True
    sample = bytes(body or b"")[:SNIFF_BYTES].lstrip().lower()
    return any(
        marker in sample
        for marker in (
            b"<!doctype html",
            b"<html",
            b"<head",
            b"<body",
            b"<form",
            b"sign in",
            b"login to continue",
            b"access denied",
            b"captcha",
        )
    )


def _status_for_http(status_code: int) -> str:
    if 200 <= int(status_code or 0) < 300:
        return "success"
    return {
        401: "unauthorized",
        403: "not_entitled",
        404: "not_found",
        429: "rate_limited",
    }.get(int(status_code or 0), "network_error")
