from __future__ import annotations

from .adapters import IucrAdapter, SpringerNatureAdapter
from .models import InstitutionalPaper


UNSUPPORTED_PREFIXES = {
    "10.1126/": "AAAS",
    "10.1080/": "Taylor & Francis",
    "10.1021/": "ACS",
    "10.1063/": "AIP",
}

ADAPTERS = (SpringerNatureAdapter(), IucrAdapter())


def select_adapter(paper: InstitutionalPaper):
    for adapter in ADAPTERS:
        if adapter.matches(paper):
            return adapter
    return None


def unsupported_reason(paper: InstitutionalPaper) -> str:
    lowered = paper.doi.lower()
    for prefix, label in UNSUPPORTED_PREFIXES.items():
        if lowered.startswith(prefix):
            return label
    if not paper.doi:
        return "missing_doi"
    return "unknown_publisher"
