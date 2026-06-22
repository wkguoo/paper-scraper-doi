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
SECTION_OR_NOTE_RE = re.compile(
    r"^(?:#+\s*)?(?:可能相关|边界|排除参考|排除|高度相关|明确相关|需确认|待确认|"
    r"推荐理由|备注|说明|注释|note|notes?|remark|remarks?|comment|comments?|unclear)\b|"
    r"^(?:p\d+|[a-z]\d+)\s*[:：].*(?:是否|可能|需要|需|建议|确认|包含|相关|排除)|"
    r"(?:是否|可能相关|边界|排除参考|推荐理由|文献信息不足|without enough bibliographic information)",
    re.I,
)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b", re.I)
AUTHOR_RE = re.compile(
    r"\b(?:[A-Z][a-zA-Z'`-]+(?:\s+[A-Z]\.?)?(?:\s+et\s+al\.?)?|"
    r"[A-Z]\.\s*[A-Z][a-zA-Z'`-]+)\b(?:\s*,\s*|\s+and\s+)"
    r"(?:[A-Z][a-zA-Z'`-]+|[A-Z]\.)",
    re.I,
)
JOURNAL_RE = re.compile(
    r"\b(?:Acta Materialia|Scripta Materialia|Materials Science and Engineering|"
    r"Journal of [A-Z][A-Za-z &-]+|Nature(?: Materials| Communications)?|Science|"
    r"Advanced Materials|Materials Today|Intermetallics|Metallurgical and Materials Transactions|"
    r"Additive Manufacturing|Corrosion Science|Surface and Coatings Technology)\b",
    re.I,
)
VOLUME_PAGE_RE = re.compile(
    r"\b(?:vol\.?|volume|issue|no\.?|pp\.?|pages?)\s*\d+|\b\d{1,4}\s*[:(]\s*\d{1,5}|\b\d{2,6}\s*[-–]\s*\d{2,6}\b",
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
    lines = []

    for original_line in str(text or "").splitlines():
        cleaned = _clean_line(original_line)
        if not cleaned:
            continue
        if _is_noise(cleaned):
            continue
        lines.append(cleaned)

    idx = 0
    while idx < len(lines):
        cleaned = lines[idx]
        source_index += 1
        dois = extract_dois(cleaned)
        if dois:
            title = _extract_title_candidate(cleaned)
            if len(dois) == 1:
                candidates.append(PaperCandidate(source_index, cleaned, dois[0], title))
            else:
                for doi in dois:
                    candidates.append(PaperCandidate(source_index, cleaned, doi, title))
            idx += 1
            continue

        title, confidence = _title_from_line(cleaned)
        if _is_non_title_note(cleaned) or confidence < 0.72:
            candidates.append(PaperCandidate(source_index, cleaned, "", title, "needs_review", "not_probable_title"))
            idx += 1
            continue

        combined = cleaned
        consumed_next = False
        if not has_extra_bibliographic_signal(cleaned, title) and idx + 1 < len(lines):
            next_line = lines[idx + 1]
            if not extract_dois(next_line) and _is_metadata_context_line(next_line):
                combined = f"{cleaned}. {next_line}"
                consumed_next = True

        if has_extra_bibliographic_signal(combined, title):
            candidates.append(PaperCandidate(source_index, cleaned, "", title))
        else:
            candidates.append(PaperCandidate(source_index, cleaned, "", title, "needs_review", "insufficient_bibliographic_context"))

        idx += 2 if consumed_next else 1

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


def _is_non_title_note(line: str) -> bool:
    value = line.strip()
    if not value:
        return True
    if SECTION_OR_NOTE_RE.search(value):
        return True
    if value.startswith("|") and value.endswith("|"):
        cells = [cell.strip() for cell in value.strip("|").split("|")]
        if any(cell.lower() in {"title", "doi", "authors", "year", "notes", "remarks", "标题", "题名", "备注", "说明"} for cell in cells):
            return True
    if len(value) < 12:
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
    if _is_non_title_note(value):
        return value, 0.0

    word_count = len(re.findall(r"[A-Za-z][A-Za-z\-]+|[\u4e00-\u9fff]{2,}", value))
    if 12 <= len(value) <= 260 and word_count >= 4:
        return value, 0.9
    if 8 <= len(value) <= 180 and word_count >= 2:
        return value, 0.55
    return value, 0.25


def _has_enough_words(line: str) -> bool:
    return len(re.findall(r"[A-Za-z][A-Za-z\-]+|[\u4e00-\u9fff]{2,}", line)) >= 4


def has_extra_bibliographic_signal(text: str, title: str = "") -> bool:
    value = str(text or "")
    title_value = str(title or "").strip()
    context = value.replace(title_value, " ", 1) if title_value else value
    return bibliographic_signal_count(context) >= 1


def is_probable_paper_title(text: str) -> bool:
    _title, confidence = _title_from_line(text)
    return confidence >= 0.72


def bibliographic_signal_count(text: str) -> int:
    value = str(text or "")
    signals = 0
    if YEAR_RE.search(value):
        signals += 1
    if AUTHOR_RE.search(value):
        signals += 1
    if JOURNAL_RE.search(value):
        signals += 1
    if VOLUME_PAGE_RE.search(value):
        signals += 1
    return signals


def _is_metadata_context_line(line: str) -> bool:
    if _is_non_title_note(line):
        return False
    return bibliographic_signal_count(line) >= 1


def _looks_like_author_segment(segment: str) -> bool:
    if "," not in segment:
        return False
    names = [part.strip() for part in segment.split(",")]
    if len(names) > 8:
        return False
    return all(re.search(r"[A-Za-z\u4e00-\u9fff]", name) for name in names[:2])


def _strip_trailing_journal_bits(value: str) -> str:
    return re.sub(
        r"\b(?:Acta Materialia|Scripta Materialia|Materials Science and Engineering|"
        r"Journal of [A-Z][A-Za-z &-]+|Nature|Science|Elsevier|Springer)\b.*$",
        "",
        value,
    ).strip()
