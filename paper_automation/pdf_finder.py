from __future__ import annotations

from urllib.parse import urlparse

from .models import MetadataResult, PdfCandidate


def choose_pdf_candidate(metadata: MetadataResult) -> PdfCandidate | None:
    unpaywall = metadata.unpaywall or {}
    if unpaywall.get("is_oa"):
        location = unpaywall.get("best_oa_location") or {}
        url = _location_pdf_url(location)
        if _allowed_url(url):
            return PdfCandidate(
                url=url,
                source="unpaywall",
                license=str(location.get("license") or unpaywall.get("license") or ""),
                host_type=str(location.get("host_type") or ""),
                evidence="unpaywall_is_oa",
            )

    openalex = metadata.openalex or {}
    open_access = openalex.get("open_access") or {}
    if open_access.get("is_oa"):
        location = openalex.get("best_oa_location") or {}
        url = str(location.get("pdf_url") or "")
        if _allowed_url(url) and _looks_like_pdf_url(url):
            return PdfCandidate(
                url=url,
                source="openalex",
                license=str(location.get("license") or ""),
                host_type=str(location.get("host_type") or ""),
                evidence="openalex_is_oa",
            )

    if _crossref_has_open_license(metadata.crossref):
        for link in metadata.crossref.get("link") or []:
            url = str(link.get("URL") or "")
            content_type = str(link.get("content-type") or "")
            if _allowed_url(url) and ("pdf" in content_type.lower() or url.lower().endswith(".pdf")):
                return PdfCandidate(url=url, source="crossref", evidence="crossref_open_license_pdf_link")

    return None


def _location_pdf_url(location: dict) -> str:
    return str(location.get("url_for_pdf") or location.get("url") or "")


def _allowed_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"}


def _looks_like_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    return path.endswith(".pdf") or "/pdf" in path or "pdf" in query


def _crossref_has_open_license(crossref: dict) -> bool:
    for license_item in crossref.get("license") or []:
        url = str(license_item.get("URL") or "").lower()
        if "creativecommons.org" in url or "open-access" in url:
            return True
    return False
