from __future__ import annotations

import json
import os
import re
from typing import Callable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from doi_batch_utils import clean_doi

from .deduplicator import title_similarity
from .models import MetadataResult, PaperCandidate


JsonGetter = Callable[[str, dict[str, str] | None, int], dict]
SearchProvider = Callable[[str, int], list[dict[str, object]]]


class MetadataResolver:
    def __init__(
        self,
        email: str = "",
        http_json: JsonGetter | None = None,
        timeout: int = 20,
        search_provider: SearchProvider | None = None,
        max_search_candidates: int = 5,
    ) -> None:
        self.email = email or os.environ.get("PAPER_SKILL_EMAIL", "")
        self.http_json = http_json or get_json
        self.timeout = timeout
        self.search_provider = search_provider
        self.max_search_candidates = max(1, max_search_candidates)

    def resolve_one(self, candidate: PaperCandidate) -> MetadataResult:
        doi = clean_doi(candidate.doi).lower()
        result = MetadataResult(candidate.source_index, candidate.title, doi=doi, title=candidate.title)

        citation_match = False
        crossref = self._query_crossref_by_doi(doi) if doi else self._query_crossref_by_title(candidate.title)
        if not crossref and not doi and candidate.raw_text:
            crossref = self._query_crossref_by_citation(candidate.raw_text)
            citation_match = bool(crossref)
        if not crossref and not doi and self.search_provider:
            crossref = self._query_crossref_by_search_provider(candidate)
            if crossref:
                citation_match = False
        if crossref:
            result = _metadata_from_crossref(candidate, crossref)
            result.crossref = crossref
            if citation_match:
                result.confidence = max(result.confidence, 0.9)
                result.match_basis = "citation_fingerprint"

        if result.doi:
            unpaywall = self._query_unpaywall(result.doi)
            if unpaywall:
                result.unpaywall = unpaywall
                result.is_oa = bool(unpaywall.get("is_oa")) or result.is_oa
            openalex = self._query_openalex_by_doi(result.doi)
        else:
            openalex = self._query_openalex_by_title(candidate.title)

        if openalex:
            result.openalex = openalex
            if not result.title:
                result = _merge_openalex(result, openalex)
            open_access = openalex.get("open_access") or {}
            result.is_oa = bool(open_access.get("is_oa")) or result.is_oa

        if not result.title and candidate.title:
            result.title = candidate.title
            result.confidence = max(result.confidence, 0.4)
            result.reason = "metadata_not_found"

        return result

    def _query_crossref_by_doi(self, doi: str) -> dict:
        if not doi:
            return {}
        url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
        data = _safe_json(self.http_json, url, self._headers(), self.timeout)
        return data.get("message") or {}

    def _query_crossref_by_title(self, title: str) -> dict:
        if not title:
            return {}
        params = urlencode({"query.bibliographic": title, "rows": "3"})
        data = _safe_json(self.http_json, f"https://api.crossref.org/works?{params}", self._headers(), self.timeout)
        items = (data.get("message") or {}).get("items") or []
        return _best_crossref_item(title, items)

    def _query_crossref_by_citation(self, citation_text: str) -> dict:
        if not citation_text:
            return {}
        params = urlencode({"query.bibliographic": citation_text, "rows": "5"})
        data = _safe_json(self.http_json, f"https://api.crossref.org/works?{params}", self._headers(), self.timeout)
        items = (data.get("message") or {}).get("items") or []
        return _best_crossref_citation_item(citation_text, items)

    def _query_crossref_by_search_provider(self, candidate: PaperCandidate) -> dict:
        query = candidate.raw_text or candidate.title
        if not query or not self.search_provider:
            return {}
        for item in self.search_provider(query, self.max_search_candidates):
            doi = _search_item_doi(item)
            if not doi:
                continue
            crossref = self._query_crossref_by_doi(doi)
            if not crossref:
                continue
            if _search_candidate_matches(candidate, item, crossref):
                crossref = dict(crossref)
                crossref["_paper_skill_match_basis"] = "semantic_scholar_crossref_verified"
                return crossref
        return {}

    def _query_openalex_by_doi(self, doi: str) -> dict:
        if not doi:
            return {}
        doi_url = f"https://doi.org/{doi}"
        params = urlencode({"filter": f"doi:{doi_url}", "per-page": "1"})
        data = _safe_json(self.http_json, f"https://api.openalex.org/works?{params}", self._headers(), self.timeout)
        results = data.get("results") or []
        return results[0] if results else {}

    def _query_openalex_by_title(self, title: str) -> dict:
        if not title:
            return {}
        params = urlencode({"search": title, "per-page": "3"})
        data = _safe_json(self.http_json, f"https://api.openalex.org/works?{params}", self._headers(), self.timeout)
        results = data.get("results") or []
        return _best_openalex_item(title, results)

    def _query_unpaywall(self, doi: str) -> dict:
        if not doi or not self.email:
            return {}
        params = urlencode({"email": self.email})
        url = f"https://api.unpaywall.org/v2/{quote(doi, safe='')}?{params}"
        return _safe_json(self.http_json, url, self._headers(), self.timeout)

    def _headers(self) -> dict[str, str]:
        mailto = f" mailto:{self.email}" if self.email else ""
        return {"User-Agent": f"paper-scraper-doi-oa/0.1{mailto}"}


def get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def _safe_json(getter: JsonGetter, url: str, headers: dict[str, str], timeout: int) -> dict:
    try:
        data = getter(url, headers, timeout)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _metadata_from_crossref(candidate: PaperCandidate, item: dict) -> MetadataResult:
    title = _first(item.get("title")) or candidate.title
    doi = clean_doi(item.get("DOI") or candidate.doi).lower()
    authors = _crossref_authors(item.get("author") or [])
    year = _crossref_year(item)
    match_basis = str(item.get("_paper_skill_match_basis") or "")
    confidence = 0.95 if doi and candidate.doi and clean_doi(candidate.doi).lower() == doi else title_similarity(candidate.title, title)
    if match_basis == "semantic_scholar_crossref_verified":
        confidence = max(confidence, 0.9)
    return MetadataResult(
        source_index=candidate.source_index,
        query_title=candidate.title,
        doi=doi,
        title=title,
        authors=authors,
        journal=_first(item.get("container-title")),
        year=year,
        publisher=str(item.get("publisher") or ""),
        url=str(item.get("URL") or ""),
        confidence=confidence,
        source="semantic_scholar+crossref" if match_basis else "crossref",
        match_basis=match_basis or ("input_doi" if candidate.doi else "title_similarity"),
    )


def _merge_openalex(result: MetadataResult, item: dict) -> MetadataResult:
    result.title = str(item.get("title") or result.title)
    result.doi = clean_doi(str(item.get("doi") or result.doi)).lower()
    result.year = str(item.get("publication_year") or result.year)
    result.url = str(item.get("doi") or result.url)
    result.confidence = max(result.confidence, title_similarity(result.query_title, result.title))
    result.source = result.source or "openalex"
    return result


def _best_crossref_item(title: str, items: list[dict]) -> dict:
    best: tuple[dict, float] | None = None
    for item in items:
        score = title_similarity(title, _first(item.get("title")))
        if not best or score > best[1]:
            best = (item, score)
    return best[0] if best and best[1] >= 0.65 else {}


def _best_crossref_citation_item(citation_text: str, items: list[dict]) -> dict:
    for item in items:
        if _citation_fingerprint_matches(citation_text, item):
            return item
    return {}


def _best_openalex_item(title: str, items: list[dict]) -> dict:
    best: tuple[dict, float] | None = None
    for item in items:
        score = title_similarity(title, str(item.get("title") or ""))
        if not best or score > best[1]:
            best = (item, score)
    return best[0] if best and best[1] >= 0.65 else {}


def semantic_scholar_search_provider(
    http_json: JsonGetter | None = None,
    email: str = "",
    timeout: int = 20,
) -> SearchProvider:
    getter = http_json or get_json

    def search(query: str, max_results: int) -> list[dict[str, object]]:
        params = urlencode({
            "query": query,
            "limit": str(max(1, max_results)),
            "fields": "title,year,venue,externalIds,authors,url,publicationVenue",
        })
        headers = {"User-Agent": f"paper-scraper-doi-search/0.1{f' mailto:{email}' if email else ''}"}
        data = _safe_json(getter, f"https://api.semanticscholar.org/graph/v1/paper/search?{params}", headers, timeout)
        rows = data.get("data") or []
        return [row for row in rows if isinstance(row, dict)]

    return search


def _first(values: object) -> str:
    if isinstance(values, list) and values:
        return str(values[0] or "")
    return str(values or "")


def _search_item_doi(item: dict[str, object]) -> str:
    external_ids = item.get("externalIds")
    if isinstance(external_ids, dict):
        doi = external_ids.get("DOI") or external_ids.get("doi")
        if doi:
            return clean_doi(doi).lower()
    return clean_doi(item.get("doi", "")).lower()


def _search_candidate_matches(candidate: PaperCandidate, search_item: dict[str, object], crossref_item: dict) -> bool:
    search_title = str(search_item.get("title") or "")
    crossref_title = _first(crossref_item.get("title"))
    query_title = candidate.title or candidate.raw_text
    if _citation_fingerprint_matches(candidate.raw_text, crossref_item):
        return True
    if title_similarity(query_title, crossref_title) >= 0.65:
        return True
    if (
        search_title
        and title_similarity(search_title, crossref_title) >= 0.85
        and title_similarity(query_title, search_title) >= 0.65
    ):
        return True
    return False


def _crossref_authors(authors: list[dict]) -> list[str]:
    names: list[str] = []
    for author in authors:
        family = str(author.get("family") or "").strip()
        given = str(author.get("given") or "").strip()
        name = " ".join(part for part in [family, given] if part)
        if name:
            names.append(name)
    return names


def _crossref_year(item: dict) -> str:
    for key in ("published-print", "published-online", "published", "created", "issued"):
        date = item.get(key) or {}
        parts = date.get("date-parts") or []
        if parts and parts[0]:
            return str(parts[0][0])
    return ""


def _citation_fingerprint_matches(citation_text: str, item: dict) -> bool:
    query = _citation_parts_from_text(citation_text)
    candidate = _citation_parts_from_crossref(item)
    if not _page_matches(query["pages"], candidate["pages"]):
        return False
    if query["years"] and candidate["years"] and not query["years"].intersection(candidate["years"]):
        return False
    if not query["years"] or not candidate["years"]:
        return False

    context_matches = 0
    if query["journals"] and candidate["journals"]:
        if query["journals"].intersection(candidate["journals"]):
            context_matches += 1
        else:
            return False
    if query["volumes"] and candidate["volumes"]:
        if query["volumes"].intersection(candidate["volumes"]):
            context_matches += 1
        else:
            return False
    return context_matches >= 1


def _citation_parts_from_text(text: str) -> dict[str, set[str]]:
    value = str(text or "")
    return {
        "journals": _journal_keys(value),
        "volumes": _volume_candidates(value),
        "pages": _page_ranges(value),
        "years": set(re.findall(r"\b(?:19|20)\d{2}\b", value)),
    }


def _citation_parts_from_crossref(item: dict) -> dict[str, set[str]]:
    page = str(item.get("page") or "")
    return {
        "journals": _journal_keys(_first(item.get("container-title"))),
        "volumes": {str(item.get("volume") or "").strip()} - {""},
        "pages": _page_ranges(page),
        "years": {_crossref_year(item)} - {""},
    }


def _journal_keys(text: str) -> set[str]:
    normalized = re.sub(r"[^a-z]+", " ", str(text or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    keys: set[str] = set()
    if "scripta materialia" in normalized or "scripta mater" in normalized:
        keys.add("scripta materialia")
    if "acta materialia" in normalized or "acta mater" in normalized:
        keys.add("acta materialia")
    return keys


def _volume_candidates(text: str) -> set[str]:
    values: set[str] = set()
    for pattern in (
        r"\b(?:Scripta\s+Mater(?:ialia)?\.?|Acta\s+Mater(?:ialia)?\.?)\s*,?\s*(\d{1,4})\b",
        r"\b(?:vol\.?|volume)\s*(\d{1,4})\b",
    ):
        values.update(match.group(1) for match in re.finditer(pattern, str(text or ""), flags=re.I))
    return values


def _page_ranges(text: str) -> set[str]:
    pages: set[str] = set()
    for match in re.finditer(r"\b(\d{1,5})\s*[\-\u2010-\u2015]\s*(\d{1,5})\b", str(text or "")):
        pages.add(f"{int(match.group(1))}-{int(match.group(2))}")
    return pages


def _page_matches(query_pages: set[str], candidate_pages: set[str]) -> bool:
    return bool(query_pages and candidate_pages and query_pages.intersection(candidate_pages))
