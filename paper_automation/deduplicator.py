from __future__ import annotations

import re
from difflib import SequenceMatcher

from doi_batch_utils import clean_doi

from .models import DeduplicationResult, DuplicateMapping, PaperCandidate


GREEK_MAP = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "κ": "kappa",
    "λ": "lambda",
    "μ": "mu",
    "π": "pi",
    "σ": "sigma",
    "τ": "tau",
    "φ": "phi",
    "ω": "omega",
}


def normalize_title(title: object) -> str:
    value = str(title or "").lower()
    for symbol, word in GREEK_MAP.items():
        value = value.replace(symbol, f" {word} ")
    value = value.replace("behaviour", "behavior")
    value = value.replace("behaviours", "behaviors")
    value = re.sub(r"[\u2010-\u2015\-_/]+", " ", value)
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def title_similarity(left: str, right: str) -> float:
    normalized_left = normalize_title(left)
    normalized_right = normalize_title(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def deduplicate_candidates(
    candidates: list[PaperCandidate],
    title_threshold: float = 0.88,
    uncertain_threshold: float = 0.78,
) -> DeduplicationResult:
    unique: list[PaperCandidate] = []
    duplicates: list[DuplicateMapping] = []
    doi_owner: dict[str, int] = {}

    for candidate in candidates:
        doi_key = _doi_key(candidate.doi)
        if doi_key and doi_key in doi_owner:
            duplicates.append(DuplicateMapping(candidate.source_index, doi_owner[doi_key], "duplicate_doi", 1.0))
            continue

        if not doi_key:
            title_match = _find_title_match(candidate, unique)
            if title_match and title_match[1] >= title_threshold:
                owner, score = title_match
                duplicates.append(DuplicateMapping(candidate.source_index, owner.source_index, "duplicate_title", score))
                continue
            if title_match and title_match[1] >= uncertain_threshold:
                owner, score = title_match
                duplicates.append(DuplicateMapping(candidate.source_index, owner.source_index, "possible_duplicate_title", score))
                continue

        unique.append(candidate)
        if doi_key:
            doi_owner[doi_key] = candidate.source_index

    return DeduplicationResult(unique, duplicates)


def _doi_key(doi: str) -> str:
    return clean_doi(doi).lower()


def _find_title_match(
    candidate: PaperCandidate,
    unique: list[PaperCandidate],
) -> tuple[PaperCandidate, float] | None:
    if not candidate.title:
        return None
    best: tuple[PaperCandidate, float] | None = None
    for existing in unique:
        if not existing.title:
            continue
        score = title_similarity(candidate.title, existing.title)
        if not best or score > best[1]:
            best = (existing, score)
    return best

