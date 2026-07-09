from __future__ import annotations


def url_looks_like_pdf(url: str) -> bool:
    lowered = (url or "").lower()
    return (
        ".pdf" in lowered
        or "/pdf" in lowered
        or "pdf=" in lowered
        or "download=pdf" in lowered
        or "content/pdf" in lowered
    )


def content_type_looks_like_pdf(content_type: str) -> bool:
    lowered = (content_type or "").lower()
    return "application/pdf" in lowered or lowered.endswith("/pdf")


def bytes_look_like_pdf(content: bytes) -> bool:
    return bytes(content[:4]) == b"%PDF"
