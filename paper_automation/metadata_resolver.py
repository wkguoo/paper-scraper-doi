from __future__ import annotations

import json
import os
from typing import Callable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from doi_batch_utils import clean_doi

from .deduplicator import title_similarity
from .models import MetadataResult, PaperCandidate


JsonGetter = Callable[[str, dict[str, str] | None, int], dict]


class MetadataResolver:
    def __init__(
        self,
        email: str = "",
        http_json: JsonGetter | None = None,
        timeout: int = 20,
    ) -> None:
        self.email = email or os.environ.get("PAPER_SKILL_EMAIL", "")
        self.http_json = http_json or get_json
        self.timeout = timeout

    def resolve_one(self, candidate: PaperCandidate) -> MetadataResult:
        doi = clean_doi(candidate.doi).lower()
        result = MetadataResult(candidate.source_index, candidate.title, doi=doi, title=candidate.title)

        crossref = self._query_crossref_by_doi(doi) if doi else self._query_crossref_by_title(candidate.title)
        if crossref:
            result = _metadata_from_crossref(candidate, crossref)
            result.crossref = crossref

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
    confidence = 0.95 if doi and candidate.doi and clean_doi(candidate.doi).lower() == doi else title_similarity(candidate.title, title)
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
        source="crossref",
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


def _best_openalex_item(title: str, items: list[dict]) -> dict:
    best: tuple[dict, float] | None = None
    for item in items:
        score = title_similarity(title, str(item.get("title") or ""))
        if not best or score > best[1]:
            best = (item, score)
    return best[0] if best and best[1] >= 0.65 else {}


def _first(values: object) -> str:
    if isinstance(values, list) and values:
        return str(values[0] or "")
    return str(values or "")


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

