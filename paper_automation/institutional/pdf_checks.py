from __future__ import annotations

from paper_automation.pdf_validation import is_pdf_bytes


def url_looks_like_pdf(url: str) -> bool:
    lowered = (url or "").lower()
    return (
        ".pdf" in lowered
        or "/pdf" in lowered
        or "/epdf" in lowered
        or "article-pdf" in lowered
        or "pdf=" in lowered
        or "download=pdf" in lowered
        or "content/pdf" in lowered
    )


def content_type_looks_like_pdf(content_type: str) -> bool:
    lowered = (content_type or "").lower()
    return "application/pdf" in lowered or lowered.endswith("/pdf")


def bytes_look_like_pdf(content: bytes) -> bool:
    return is_pdf_bytes(content)
