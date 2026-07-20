from __future__ import annotations

from .adapters import (
    AaasAdapter,
    AcsAdapter,
    AipAdapter,
    ApsAdapter,
    EcsAdapter,
    IeeeAdapter,
    IopAdapter,
    IucrAdapter,
    MdpiAdapter,
    MrsAdapter,
    RscAdapter,
    SpringerNatureAdapter,
    TaylorFrancisAdapter,
    WileyAdapter,
)
from .models import InstitutionalPaper


UNSUPPORTED_PREFIXES = {
}

ADAPTERS = (
    # Materials P0 platforms first so DOI-specific routes win over host-wide publishers.
    ApsAdapter(),
    EcsAdapter(),
    MrsAdapter(),
    SpringerNatureAdapter(),
    IucrAdapter(),
    AaasAdapter(),
    TaylorFrancisAdapter(),
    AcsAdapter(),
    AipAdapter(),
    WileyAdapter(),
    IeeeAdapter(),
    RscAdapter(),
    IopAdapter(),
    # Gold-OA MDPI: often 403 on plain HTTP; adapter enables browser capture candidates.
    MdpiAdapter(),
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
