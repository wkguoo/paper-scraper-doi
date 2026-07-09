from __future__ import annotations

import html
import re
from typing import Iterable
from urllib.parse import urljoin

from ..models import PdfUrlCandidate
from ..pdf_checks import url_looks_like_pdf


META_PDF_RE = re.compile(
    r"""<meta[^>]+name=["']citation_pdf_url["'][^>]+content=["']([^"']+)["']""",
    flags=re.IGNORECASE,
)
HREF_RE = re.compile(r"""href=["']([^"']+)["']""", flags=re.IGNORECASE)
DEFAULT_FETCH_PATTERNS = ("*pdf*", "*download*", "*content/pdf*", "*article-pdf*")


def extract_pdf_candidates(base_url: str, html_text: str) -> tuple[PdfUrlCandidate, ...]:
    candidates: list[PdfUrlCandidate] = []
    for raw_url in META_PDF_RE.findall(html_text or ""):
        resolved = urljoin(base_url, html.unescape(raw_url))
        if url_looks_like_pdf(resolved):
            candidates.append(PdfUrlCandidate("citation_pdf_url", resolved, DEFAULT_FETCH_PATTERNS))
    for raw_url in HREF_RE.findall(html_text or ""):
        resolved = urljoin(base_url, html.unescape(raw_url))
        if url_looks_like_pdf(resolved):
            candidates.append(PdfUrlCandidate("page_link", resolved, DEFAULT_FETCH_PATTERNS))
    return unique_candidates(candidates)


def unique_candidates(candidates: Iterable[PdfUrlCandidate]) -> tuple[PdfUrlCandidate, ...]:
    unique: list[PdfUrlCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.url.strip().lower()
        if not key or key in seen:
            continue
        unique.append(candidate)
        seen.add(key)
    return tuple(unique)


def classify_access_failure(
    page_text: str,
    attempt_notes: Iterable[str],
    auth_signals: tuple[str, ...],
    paywall_signals: tuple[str, ...],
) -> tuple[str, str]:
    normalized = " ".join((page_text or "").lower().split())
    notes = [note for note in attempt_notes if note]
    blocked_note = next((note for note in notes if note.startswith("blocked:")), "")
    if blocked_note:
        return "publisher_blocked", blocked_note

    auth_signal = next((signal for signal in auth_signals if signal in normalized), "")
    if auth_signal:
        return "auth_required", auth_signal

    paywall_signal = next((signal for signal in paywall_signals if signal in normalized), "")
    if paywall_signal:
        return "no_entitlement_or_blocked", paywall_signal

    if "network_pdf_not_captured" in notes:
        return "not_pdf_response", "network_pdf_not_captured"

    if notes:
        return "error", notes[-1]

    return "not_pdf_response", "no_pdf_candidate_detected"
