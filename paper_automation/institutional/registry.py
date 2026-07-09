from __future__ import annotations

from .adapters import AaasAdapter, AcsAdapter, AipAdapter, IucrAdapter, SpringerNatureAdapter, TaylorFrancisAdapter
from .models import InstitutionalPaper


UNSUPPORTED_PREFIXES = {
}

ADAPTERS = (
    SpringerNatureAdapter(),
    IucrAdapter(),
    AaasAdapter(),
    TaylorFrancisAdapter(),
    AcsAdapter(),
    AipAdapter(),
)


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
