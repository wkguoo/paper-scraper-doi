from __future__ import annotations

import re

from doi_batch_utils import clean_doi

from .models import PaperCandidate


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"'<>\]\}]+", re.I)
LEADING_MARKER_RE = re.compile(r"^\s*(?:\[\d+\]|\(?\d+[\).\]]|[•*#-])\s*")
NOISE_RE = re.compile(
    r"^(download pdf|view article|abstract|full text|references?|related articles?|"
    r"export citation|save to|share|cookie|sign in|log in)(?:\b|[\s|])",
    re.I,
)


def extract_dois(text: object) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for match in DOI_PATTERN.finditer(str(text or "")):
        doi = clean_doi(match.group(0)).lower()
        if doi and doi not in seen:
            seen.add(doi)
            values.append(doi)
    return values


def parse_mixed_text(text: str) -> list[PaperCandidate]:
    candidates: list[PaperCandidate] = []
    source_index = 0

    for original_line in str(text or "").splitlines():
        cleaned = _clean_line(original_line)
        if not cleaned:
            continue
        if _is_noise(cleaned):
            continue

        source_index += 1
        dois = extract_dois(cleaned)
        if dois:
            title = _extract_title_candidate(cleaned)
            if len(dois) == 1:
                candidates.append(PaperCandidate(source_index, cleaned, dois[0], title))
            else:
                for doi in dois:
                    candidates.append(PaperCandidate(source_index, cleaned, doi, title))
            continue

        title, confidence = _title_from_line(cleaned)
        if confidence >= 0.72:
            candidates.append(PaperCandidate(source_index, cleaned, "", title))
        else:
            candidates.append(PaperCandidate(source_index, cleaned, "", title, "needs_review", "ambiguous_text"))

    return candidates


def _clean_line(line: str) -> str:
    value = str(line or "").strip()
    value = value.replace("\u3000", " ")
    value = re.sub(r"\s+", " ", value)
    if not DOI_PATTERN.match(value):
        value = LEADING_MARKER_RE.sub("", value).strip()
    return value.strip(" ;,")


def _is_noise(line: str) -> bool:
    if DOI_PATTERN.search(line):
        return False
    if NOISE_RE.search(line.strip()):
        return True
    if "|" in line and len(line) < 80 and not _has_enough_words(line):
        return True
    return False


def _extract_title_candidate(line: str) -> str:
    without_url = re.sub(r"https?://(?:dx\.)?doi\.org/\S+", "", line, flags=re.I)
    without_doi = DOI_PATTERN.sub("", without_url)
    without_doi = re.sub(r"\bdoi\s*:\s*", "", without_doi, flags=re.I)
    without_doi = re.sub(r"\s+", " ", without_doi).strip(" .;,")
    title, confidence = _title_from_line(without_doi)
    return title if confidence >= 0.45 else ""


def _title_from_line(line: str) -> tuple[str, float]:
    value = re.sub(r"\(\d{4}[a-z]?\)", "", line, flags=re.I).strip()
    parts = [part.strip(" .;,") for part in re.split(r"\.\s+", value) if part.strip(" .;,")]
    if len(parts) >= 2 and _looks_like_author_segment(parts[0]):
        value = parts[1]
    elif len(parts) >= 2 and len(parts[0]) < 45 and "," in parts[0]:
        value = parts[1]
    else:
        value = parts[0] if parts else value

    value = _strip_trailing_journal_bits(value)
    value = re.sub(r"\s+", " ", value).strip(" .;,")
    if not value:
        return "", 0.0
    if DOI_PATTERN.fullmatch(value):
        return "", 0.0

    word_count = len(re.findall(r"[A-Za-z][A-Za-z\-]+|[\u4e00-\u9fff]{2,}", value))
    if 12 <= len(value) <= 260 and word_count >= 4:
        return value, 0.9
    if 8 <= len(value) <= 180 and word_count >= 2:
        return value, 0.55
    return value, 0.25


def _has_enough_words(line: str) -> bool:
    return len(re.findall(r"[A-Za-z][A-Za-z\-]+|[\u4e00-\u9fff]{2,}", line)) >= 4


def _looks_like_author_segment(segment: str) -> bool:
    if "," not in segment:
        return False
    names = [part.strip() for part in segment.split(",")]
    if len(names) > 8:
        return False
    return all(re.search(r"[A-Za-z\u4e00-\u9fff]", name) for name in names[:2])


def _strip_trailing_journal_bits(value: str) -> str:
    return re.sub(r"\b(?:Acta Materialia|Nature|Science|Elsevier|Springer)\b.*$", "", value).strip()
