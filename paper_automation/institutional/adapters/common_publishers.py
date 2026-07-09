from __future__ import annotations

from urllib.parse import urlparse

from ..models import InstitutionalPaper, PageSnapshot, PdfUrlCandidate
from .common import DEFAULT_FETCH_PATTERNS, classify_access_failure, extract_pdf_candidates, unique_candidates


COMMON_AUTH_SIGNALS = (
    "access through your institution",
    "access via your institution",
    "institutional access",
    "sign in through your institution",
    "sign in via your institution",
    "log in through your institution",
    "log in via your institution",
)
COMMON_PAYWALL_SIGNALS = (
    "get access",
    "purchase access",
    "purchase article",
    "rent this article",
    "subscribe to this journal",
    "subscription required",
)
PDF_FETCH_PATTERNS = DEFAULT_FETCH_PATTERNS + ("*doi/pdf*", "*doi/epdf*", "*article-pdf*")


class DirectDoiPdfAdapter:
    name = ""
    doi_prefixes: tuple[str, ...] = ()
    publisher_terms: tuple[str, ...] = ()
    hosts: tuple[str, ...] = ()

    def matches(self, paper: InstitutionalPaper) -> bool:
        doi = (paper.doi or "").lower()
        publisher = (paper.publisher or "").lower()
        host = (urlparse(paper.landing_url).hostname or "").lower()
        return (
            any(doi.startswith(prefix) for prefix in self.doi_prefixes)
            or any(term in publisher for term in self.publisher_terms)
            or any(_host_matches(host, candidate) for candidate in self.hosts)
        )

    def build_pdf_candidates(
        self,
        paper: InstitutionalPaper,
        landing: PageSnapshot,
    ) -> tuple[PdfUrlCandidate, ...]:
        base_url = landing.final_url or landing.requested_url or paper.landing_url
        candidates = list(extract_pdf_candidates(base_url, landing.html))
        candidates.extend(self._direct_pdf_candidates(paper, landing))
        return unique_candidates(candidates)

    def classify_failure(self, landing: PageSnapshot, attempt_notes: tuple[str, ...]) -> tuple[str, str]:
        return classify_access_failure(
            landing.text,
            attempt_notes,
            COMMON_AUTH_SIGNALS,
            COMMON_PAYWALL_SIGNALS,
        )

    def _direct_pdf_candidates(
        self,
        paper: InstitutionalPaper,
        landing: PageSnapshot,
    ) -> tuple[PdfUrlCandidate, ...]:
        return ()


class AaasAdapter(DirectDoiPdfAdapter):
    name = "aaas"
    doi_prefixes = ("10.1126/",)
    publisher_terms = ("aaas", "american association for the advancement of science")
    hosts = ("science.org", "www.science.org")

    def _direct_pdf_candidates(
        self,
        paper: InstitutionalPaper,
        landing: PageSnapshot,
    ) -> tuple[PdfUrlCandidate, ...]:
        doi = paper.doi
        if not doi:
            return ()
        return (
            PdfUrlCandidate("aaas_doi_pdf", f"https://www.science.org/doi/pdf/{doi}", PDF_FETCH_PATTERNS),
            PdfUrlCandidate("aaas_doi_epdf", f"https://www.science.org/doi/epdf/{doi}", PDF_FETCH_PATTERNS),
        )


class TaylorFrancisAdapter(DirectDoiPdfAdapter):
    name = "taylor_francis"
    doi_prefixes = ("10.1080/",)
    publisher_terms = ("taylor & francis", "taylor and francis", "informa uk")
    hosts = ("tandfonline.com", "www.tandfonline.com")

    def _direct_pdf_candidates(
        self,
        paper: InstitutionalPaper,
        landing: PageSnapshot,
    ) -> tuple[PdfUrlCandidate, ...]:
        doi = paper.doi
        if not doi:
            return ()
        return (
            PdfUrlCandidate(
                "taylor_francis_doi_pdf",
                f"https://www.tandfonline.com/doi/pdf/{doi}?download=true",
                PDF_FETCH_PATTERNS,
            ),
        )


class AcsAdapter(DirectDoiPdfAdapter):
    name = "acs"
    doi_prefixes = ("10.1021/",)
    publisher_terms = ("american chemical society", "acs")
    hosts = ("pubs.acs.org",)

    def _direct_pdf_candidates(
        self,
        paper: InstitutionalPaper,
        landing: PageSnapshot,
    ) -> tuple[PdfUrlCandidate, ...]:
        doi = paper.doi
        if not doi:
            return ()
        return (
            PdfUrlCandidate("acs_doi_pdf", f"https://pubs.acs.org/doi/pdf/{doi}", PDF_FETCH_PATTERNS),
            PdfUrlCandidate("acs_doi_epdf", f"https://pubs.acs.org/doi/epdf/{doi}", PDF_FETCH_PATTERNS),
        )


class AipAdapter(DirectDoiPdfAdapter):
    name = "aip"
    doi_prefixes = ("10.1063/",)
    publisher_terms = ("aip publishing", "american institute of physics")
    hosts = ("pubs.aip.org", "aip.scitation.org")

    def _direct_pdf_candidates(
        self,
        paper: InstitutionalPaper,
        landing: PageSnapshot,
    ) -> tuple[PdfUrlCandidate, ...]:
        doi = paper.doi
        if not doi:
            return ()
        base_url = landing.final_url or landing.requested_url or paper.landing_url
        parsed = urlparse(base_url)
        host = parsed.hostname or "pubs.aip.org"
        journal_path = _aip_journal_path(parsed.path)
        return (
            PdfUrlCandidate(
                "aip_article_pdf_by_doi",
                f"https://{host}{journal_path}/article-pdf/doi/{doi}",
                PDF_FETCH_PATTERNS,
            ),
        )


def _host_matches(host: str, candidate: str) -> bool:
    return host == candidate or host.endswith(f".{candidate}")


def _aip_journal_path(path: str) -> str:
    marker = "/article/"
    if marker in path:
        prefix = path.split(marker, 1)[0].rstrip("/")
        if prefix:
            return prefix
    return "/aip/jap"
