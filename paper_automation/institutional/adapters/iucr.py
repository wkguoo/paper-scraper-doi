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
            candidates.extend(
                (
                    PdfUrlCandidate("iucr_pdf_suffix", _join_suffix(base_url, "pdf"), DEFAULT_FETCH_PATTERNS),
                    PdfUrlCandidate("iucr_download_pdf", _replace_query(base_url, {"download": "pdf"}), DEFAULT_FETCH_PATTERNS),
                    PdfUrlCandidate("iucr_download_one", _replace_query(base_url, {"download": "1"}), DEFAULT_FETCH_PATTERNS),
                )
            )
        return unique_candidates(candidates)

    def classify_failure(self, landing: PageSnapshot, attempt_notes: tuple[str, ...]) -> tuple[str, str]:
        return classify_access_failure(landing.text, attempt_notes, AUTH_SIGNALS, PAYWALL_SIGNALS)


def _join_suffix(url: str, suffix: str) -> str:
    return f"{url.rstrip('/')}/{suffix}"


def _replace_query(url: str, params: dict[str, str]) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params), parsed.fragment))
