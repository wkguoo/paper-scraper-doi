from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from ..models import InstitutionalPaper, PageSnapshot, PdfUrlCandidate
from .common import DEFAULT_FETCH_PATTERNS, classify_access_failure, extract_pdf_candidates, unique_candidates


SPRINGER_PREFIX = "10.1007/"
NATURE_PREFIX = "10.1038/"
SPRINGER_HOSTS = ("link.springer.com",)
NATURE_HOSTS = ("nature.com", "www.nature.com")
AUTH_SIGNALS = (
    "access via your institution",
    "access through your institution",
    "sign in via an institution",
    "sign in through your institution",
    "log in via an institution",
    "institutional access",
)
PAYWALL_SIGNALS = (
    "buy article pdf",
    "purchase article",
    "purchase pdf",
    "subscription will be required",
    "access options",
)


@dataclass(frozen=True)
class SpringerNatureAdapter:
    name: str = "springer_nature"

    def matches(self, paper: InstitutionalPaper) -> bool:
        doi = paper.doi.lower()
        publisher = paper.publisher.lower()
        host = urlparse(paper.landing_url).hostname or ""
        return (
            doi.startswith(SPRINGER_PREFIX)
            or doi.startswith(NATURE_PREFIX)
            or "springer" in publisher
            or "nature" in publisher
            or host.lower() in SPRINGER_HOSTS + NATURE_HOSTS
        )

    def build_pdf_candidates(
        self,
        paper: InstitutionalPaper,
        landing: PageSnapshot,
    ) -> tuple[PdfUrlCandidate, ...]:
        candidates = list(extract_pdf_candidates(landing.final_url or landing.requested_url, landing.html))
        doi = paper.doi
        if doi.lower().startswith(SPRINGER_PREFIX):
            candidates.append(
                PdfUrlCandidate(
                    "springer_content_pdf",
                    f"https://link.springer.com/content/pdf/{doi}.pdf",
                    DEFAULT_FETCH_PATTERNS,
                )
            )
        final_url = landing.final_url or landing.requested_url
        parsed = urlparse(final_url)
        host = (parsed.hostname or "").lower()
        if host in NATURE_HOSTS:
            slug = parsed.path.strip("/").split("/")
            if len(slug) >= 2 and slug[0] == "articles":
                candidates.append(
                    PdfUrlCandidate(
                        "nature_article_pdf",
                        f"https://www.nature.com/articles/{slug[1]}.pdf",
                        DEFAULT_FETCH_PATTERNS,
                    )
                )
        if host in SPRINGER_HOSTS and doi:
            candidates.append(
                PdfUrlCandidate(
                    "springer_fallback_pdf",
                    f"https://link.springer.com/content/pdf/{doi}.pdf",
                    DEFAULT_FETCH_PATTERNS,
                )
            )
        return unique_candidates(candidates)

    def classify_failure(self, landing: PageSnapshot, attempt_notes: tuple[str, ...]) -> tuple[str, str]:
        return classify_access_failure(landing.text, attempt_notes, AUTH_SIGNALS, PAYWALL_SIGNALS)
