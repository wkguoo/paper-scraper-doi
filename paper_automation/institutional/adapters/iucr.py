from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

from ..models import InstitutionalPaper, PageSnapshot, PdfUrlCandidate
from .common import DEFAULT_FETCH_PATTERNS, classify_access_failure, extract_pdf_candidates, unique_candidates


IUCR_PREFIX = "10.1107/"
IUCR_HOSTS = (
    "journals.iucr.org",
    "scripts.iucr.org",
    "iucr.org",
    "www.iucr.org",
)
AUTH_SIGNALS = (
    "access through your institution",
    "institutional login",
    "log in via your institution",
    "sign in through your institution",
)
PAYWALL_SIGNALS = (
    "purchase article",
    "buy article",
    "access options",
    "get access",
    "subscription required",
)
IUCR_FETCH_PATTERNS = DEFAULT_FETCH_PATTERNS + ("*journals.iucr.org/*.pdf*", "*scripts.iucr.org/cgi-bin/paper*")


@dataclass(frozen=True)
class IucrAdapter:
    name: str = "iucr"

    def matches(self, paper: InstitutionalPaper) -> bool:
        doi = paper.doi.lower()
        publisher = paper.publisher.lower()
        host = (urlparse(paper.landing_url).hostname or "").lower()
        return doi.startswith(IUCR_PREFIX) or "iucr" in publisher or host in IUCR_HOSTS

    def build_pdf_candidates(
        self,
        paper: InstitutionalPaper,
        landing: PageSnapshot,
    ) -> tuple[PdfUrlCandidate, ...]:
        base_url = landing.final_url or landing.requested_url
        candidates = list(extract_pdf_candidates(base_url, landing.html))
        if base_url:
            candidates.extend(_article_code_pdf_candidates(base_url))
            candidates.extend(_scripts_pdf_candidates(paper.doi))
            candidates.extend(
                (
                    PdfUrlCandidate("iucr_pdf_suffix", _join_suffix(base_url, "pdf"), IUCR_FETCH_PATTERNS),
                    PdfUrlCandidate("iucr_download_pdf", _add_query_params(base_url, {"download": "pdf"}), IUCR_FETCH_PATTERNS),
                    PdfUrlCandidate("iucr_download_one", _add_query_params(base_url, {"download": "1"}), IUCR_FETCH_PATTERNS),
                )
            )
        return unique_candidates(candidates)

    def classify_failure(self, landing: PageSnapshot, attempt_notes: tuple[str, ...]) -> tuple[str, str]:
        return classify_access_failure(landing.text, attempt_notes, AUTH_SIGNALS, PAYWALL_SIGNALS)


def _join_suffix(url: str, suffix: str) -> str:
    parsed = urlsplit(url)
    path = f"{parsed.path.rstrip('/')}/{suffix}"
    return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))


def _add_query_params(url: str, params: dict[str, str]) -> str:
    parsed = urlsplit(url)
    extra = urlencode(params)
    query = f"{parsed.query}&{extra}" if parsed.query else extra
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment))


def _article_code_pdf_candidates(url: str) -> tuple[PdfUrlCandidate, ...]:
    parsed = urlsplit(url)
    if "journals.iucr.org" not in (parsed.netloc or "").lower():
        return ()
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if not parts:
        return ()
    article_code = ""
    base_parts = parts
    if parts[-1].lower() == "index.html" and len(parts) >= 2:
        article_code = parts[-2]
        base_parts = parts[:-1]
    elif "." not in parts[-1]:
        article_code = parts[-1]
    if not article_code:
        return ()
    pdf_path = "/" + "/".join(base_parts + [f"{article_code}.pdf"])
    pdf_url = urlunsplit((parsed.scheme, parsed.netloc, pdf_path, "", ""))
    return (PdfUrlCandidate("iucr_article_code_pdf", pdf_url, IUCR_FETCH_PATTERNS),)


def _scripts_pdf_candidates(doi: str) -> tuple[PdfUrlCandidate, ...]:
    suffix = (doi or "").rsplit("/", 1)[-1].upper()
    if not suffix.startswith("S"):
        return ()
    return (
        PdfUrlCandidate(
            "iucr_scripts_doi_pdf",
            f"https://scripts.iucr.org/cgi-bin/paper?{suffix}&download=pdf",
            IUCR_FETCH_PATTERNS,
        ),
    )
