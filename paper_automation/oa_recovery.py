"""Bounded OA / repository recovery for unsupported publishers (e.g. SAGE).

Design goals (see AGENTS.md "Limited OA recovery"):
- Hard per-DOI budget (default 60s); early stop on first valid PDF.
- Step 0: Crossref/OpenAlex metadata only.
- Step 1: At most annotated OA PDF URLs (no blind /doi/pdf guessing).
- Step 2: At most one repository location that already exposes a PDF URL.
- No browser CDP, Wayback, or multi-aggregator deep search by default.
- Host negative cache: if a host is unreachable, skip it for sibling DOIs.
"""

from __future__ import annotations

import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from doi_batch_utils import clean_doi

from .downloader import BROWSER_HEADERS, DownloadResponse
from .file_manager import make_pdf_filename
from .metadata_resolver import MetadataResolver
from .models import MetadataResult, PaperCandidate
from .pdf_finder import choose_pdf_candidate
from .pdf_validation import is_pdf_bytes

JsonGetter = Callable[[str, dict[str, str] | None, int], dict]
BytesGetter = Callable[[str, dict[str, str] | None, int], DownloadResponse]

DEFAULT_BUDGET_SECONDS = 60.0
DEFAULT_STEP_TIMEOUT = 12
DEFAULT_MAX_WORKERS = 2
MAX_OA_URL_TRIES = 2  # annotated OA + at most one known-host rewrite (e.g. MDPI CDN)
MAX_REPO_URL_TRIES = 1

DEFAULT_RECOVER_STATUSES = frozenset(
    {
        "unsupported_publisher",
        "pending_zotero",
        "no_pdf",
        "download_failed",
        "not_pdf_response",
        "invalid_pdf",
        "oa_failed",
    }
)

_REPO_HOST_MARKERS = (
    "handle",
    "bitstream",
    "dspace",
    "repository",
    "oasis.",
    "postech",
    "zenodo",
    "figshare",
    "arxiv.org",
    "pmc.ncbi",
    "europepmc",
    "core.ac.uk",
    "osti.gov",
    "openaire",
)

_PUBLISHER_HOST_BLOCKLIST_FOR_REPO = (
    "sagepub.com",
    "tandfonline.com",
    "sciencedirect.com",
    "springer.com",
    "nature.com",
    "wiley.com",
    "ieee.org",
    "acs.org",
)


@dataclass
class RecoveryAttempt:
    step: str
    url: str
    result: str
    detail: str = ""
    elapsed_s: float = 0.0


@dataclass
class RecoveryResult:
    doi: str
    status: str
    file: str = ""
    reason: str = ""
    title: str = ""
    authors: str = ""
    year: str = ""
    journal: str = ""
    publisher: str = ""
    attempts: list[RecoveryAttempt] = field(default_factory=list)
    elapsed_s: float = 0.0
    task_id: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "doi": self.doi,
            "status": self.status,
            "file": self.file,
            "reason": self.reason,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "publisher": self.publisher,
            "elapsed_s": f"{self.elapsed_s:.2f}",
            "attempts": "; ".join(
                f"{a.step}:{a.result}" + (f"({a.detail})" if a.detail else "")
                for a in self.attempts
            ),
        }


class HostHealthCache:
    """Share host-level failures across DOIs in one recovery run."""

    def __init__(self) -> None:
        import threading

        self._bad: dict[str, str] = {}
        self._lock = threading.Lock()

    def mark_unreachable(self, url: str, reason: str) -> None:
        host = _host(url)
        if host:
            with self._lock:
                self._bad[host] = reason or "host_unreachable"

    def is_unreachable(self, url: str) -> bool:
        host = _host(url)
        with self._lock:
            return bool(host and host in self._bad)

    def reason(self, url: str) -> str:
        host = _host(url)
        with self._lock:
            return self._bad.get(host, "")


def recover_oa_limited(
    doi: str,
    *,
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
    email: str = "",
    output_dir: str | Path | None = None,
    timeout_per_request: int = DEFAULT_STEP_TIMEOUT,
    host_cache: HostHealthCache | None = None,
    http_json: JsonGetter | None = None,
    http_bytes: BytesGetter | None = None,
    resolver: MetadataResolver | None = None,
) -> RecoveryResult:
    """Recover at most one legal OA/repo PDF for *doi* within *budget_seconds*."""

    started = time.monotonic()
    deadline = started + max(5.0, float(budget_seconds))
    cleaned = clean_doi(doi).lower()
    cache = host_cache or HostHealthCache()
    attempts: list[RecoveryAttempt] = []

    if not cleaned:
        return RecoveryResult(
            doi=str(doi or ""),
            status="missing_doi",
            reason="missing_doi",
            elapsed_s=0.0,
        )

    def remaining() -> float:
        return deadline - time.monotonic()

    def timed_out() -> bool:
        return remaining() <= 0

    # ---- Step 0: metadata ----
    step0_start = time.monotonic()
    metadata = _resolve_metadata(
        cleaned,
        email=email,
        timeout=min(timeout_per_request, max(3, int(remaining()))),
        http_json=http_json,
        resolver=resolver,
    )
    attempts.append(
        RecoveryAttempt(
            step="metadata",
            url="",
            result="ok" if (metadata.title or metadata.year or metadata.authors) else "empty",
            detail=metadata.source or "",
            elapsed_s=time.monotonic() - step0_start,
        )
    )

    base = RecoveryResult(
        doi=cleaned,
        status="no_oa_pdf",
        reason="no_oa_pdf",
        title=metadata.title or "",
        authors=" | ".join(metadata.authors) if metadata.authors else "",
        year=metadata.year or "",
        journal=metadata.journal or "",
        publisher=metadata.publisher or "",
        attempts=attempts,
    )

    if timed_out():
        base.status = "recovery_timeout"
        base.reason = "recovery_timeout"
        base.elapsed_s = time.monotonic() - started
        return base

    # ---- Step 1: annotated OA PDF URLs only ----
    oa_urls = _annotated_oa_pdf_urls(metadata)
    for index, url in enumerate(oa_urls[:MAX_OA_URL_TRIES]):
        if timed_out():
            base.status = "recovery_timeout"
            base.reason = "recovery_timeout"
            break
        if cache.is_unreachable(url):
            attempts.append(
                RecoveryAttempt(
                    step="oa_url",
                    url=url,
                    result="skipped_host_cache",
                    detail=cache.reason(url),
                )
            )
            continue
        ok, attempt = _try_download_pdf(
            url,
            step="oa_url",
            timeout=min(timeout_per_request, max(3, int(remaining()))),
            http_bytes=http_bytes,
            host_cache=cache,
        )
        attempts.append(attempt)
        if ok:
            path = _write_delivery_pdf(
                ok,
                metadata,
                output_dir=output_dir,
            )
            base.status = "oa_downloaded"
            base.file = str(path) if path else ""
            base.reason = f"oa_url:{attempt.detail or 'annotated'}"
            base.elapsed_s = time.monotonic() - started
            base.attempts = attempts
            return base
        # One known rewrite for MDPI official pdf → CDN (still within Step 1 budget).
        if index == 0:
            alt = _mdpi_cdn_alternate(url)
            if alt and alt not in oa_urls and not timed_out():
                if cache.is_unreachable(alt):
                    attempts.append(
                        RecoveryAttempt(
                            step="oa_url_rewrite",
                            url=alt,
                            result="skipped_host_cache",
                            detail=cache.reason(alt),
                        )
                    )
                else:
                    ok2, attempt2 = _try_download_pdf(
                        alt,
                        step="oa_url_rewrite",
                        timeout=min(timeout_per_request, max(3, int(remaining()))),
                        http_bytes=http_bytes,
                        host_cache=cache,
                    )
                    attempts.append(attempt2)
                    if ok2:
                        path = _write_delivery_pdf(ok2, metadata, output_dir=output_dir)
                        base.status = "oa_downloaded"
                        base.file = str(path) if path else ""
                        base.reason = "oa_url_rewrite:mdpi_cdn"
                        base.elapsed_s = time.monotonic() - started
                        base.attempts = attempts
                        return base

    if timed_out():
        base.status = "recovery_timeout"
        base.reason = "recovery_timeout"
        base.elapsed_s = time.monotonic() - started
        base.attempts = attempts
        return base

    # ---- Step 2: at most one repository PDF URL ----
    repo_urls = _repository_pdf_urls(metadata)
    if not repo_urls:
        # OpenAlex may point at a repo landing page with no PDF — do not scrape.
        if _repository_landing_only(metadata):
            base.status = "repo_metadata_only"
            base.reason = "repo_metadata_only"
            attempts.append(
                RecoveryAttempt(
                    step="repo",
                    url="",
                    result="metadata_only",
                    detail="landing_without_pdf_url",
                )
            )
        else:
            base.status = _finalize_failure_status(attempts)
            base.reason = base.status
        base.elapsed_s = time.monotonic() - started
        base.attempts = attempts
        return base

    for url in repo_urls[:MAX_REPO_URL_TRIES]:
        if timed_out():
            base.status = "recovery_timeout"
            base.reason = "recovery_timeout"
            break
        if cache.is_unreachable(url):
            attempts.append(
                RecoveryAttempt(
                    step="repo",
                    url=url,
                    result="skipped_host_cache",
                    detail=cache.reason(url),
                )
            )
            continue
        ok, attempt = _try_download_pdf(
            url,
            step="repo",
            timeout=min(timeout_per_request, max(3, int(remaining()))),
            http_bytes=http_bytes,
            host_cache=cache,
        )
        attempts.append(attempt)
        if ok:
            path = _write_delivery_pdf(ok, metadata, output_dir=output_dir)
            base.status = "oa_downloaded"
            base.file = str(path) if path else ""
            base.reason = "repo_pdf"
            base.elapsed_s = time.monotonic() - started
            base.attempts = attempts
            return base

    base.status = _finalize_failure_status(attempts)
    base.reason = base.status
    base.elapsed_s = time.monotonic() - started
    base.attempts = attempts
    return base


def metadata_has_oa_signal(metadata: MetadataResult | None) -> bool:
    """True when OpenAlex/Unpaywall/pdf candidates indicate a legal OA PDF path."""

    if metadata is None:
        return False
    urls = _annotated_oa_pdf_urls(metadata)
    if urls:
        return True
    repo = _repository_pdf_urls(metadata)
    return bool(repo)


def row_has_oa_signal(row: dict, *, email: str = "", resolver: MetadataResolver | None = None) -> bool:
    """Check stored reason marker first; otherwise resolve metadata once."""

    reason = str(row.get("reason", "") or "")
    if "oa_signal=1" in reason:
        return True
    from .batch_stages import is_gold_oa_doi

    doi = clean_doi(str(row.get("doi") or row.get("input_doi") or "")).lower()
    if is_gold_oa_doi(doi):
        return True
    try:
        meta = _resolve_metadata(doi, email=email, resolver=resolver, timeout=8)
    except Exception:
        return False
    return metadata_has_oa_signal(meta)


def run_limited_oa_recovery_on_batch(
    run_dir: str | Path,
    *,
    email: str = "",
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
    only_statuses: set[str] | frozenset[str] | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    timeout_per_request: int = DEFAULT_STEP_TIMEOUT,
    http_json: JsonGetter | None = None,
    http_bytes: BytesGetter | None = None,
    require_oa_signal: bool = True,
) -> list[RecoveryResult]:
    """Recover unresolved rows in an existing batch with bounded OA recovery.

    B3.3: by default only rows with an OA signal (gold-OA DOI / is_oa / pdf_url)
    are attempted; others are skipped with reason no_oa_signal.
    """

    from .batch_workflow import (
        batch_state_lock,
        load_batch_state,
        paths_from_run_dir,
        save_batch_state,
        write_final_reports,
        _write_pending_files,
        _is_successful_status,
    )

    root = Path(run_dir).expanduser().resolve()
    paths = paths_from_run_dir(root)
    state = load_batch_state(root)
    options = state.get("options") or {}
    use_email = email or str(options.get("email", "") or "")
    statuses = only_statuses or DEFAULT_RECOVER_STATUSES
    host_cache = HostHealthCache()

    # Statuses that always get an OA HTTP attempt even without a pre-flagged OA signal
    # (unsupported publishers / capture misses often still have Unpaywall/MDPI PDFs).
    ALWAYS_TRY_STATUSES = frozenset(
        {
            "unsupported_publisher",
            "not_pdf_response",
            "pending_zotero",
        }
    )

    targets: list[dict] = []
    skipped: list[RecoveryResult] = []
    for row in state.get("rows") or []:
        if _is_successful_status(row.get("status", "")):
            continue
        status = str(row.get("status", "") or "").strip().lower()
        if status not in statuses:
            continue
        doi = clean_doi(str(row.get("doi") or row.get("input_doi") or "")).lower()
        if not doi:
            continue
        force_try = status in ALWAYS_TRY_STATUSES
        if require_oa_signal and not force_try and not row_has_oa_signal(row, email=use_email):
            skipped.append(
                RecoveryResult(
                    doi=doi,
                    task_id=str(row.get("task_id") or ""),
                    status="skipped",
                    reason="no_oa_signal",
                )
            )
            continue
        targets.append(dict(row))

    if not targets:
        if skipped:
            report_path = paths.reports / "oa_recovery_report.csv"
            try:
                _write_recovery_report(report_path, skipped)
            except Exception:
                pass
        return skipped

    results_by_task: dict[str, RecoveryResult] = {}

    def _work(row: dict) -> RecoveryResult:
        doi = clean_doi(str(row.get("doi") or row.get("input_doi") or "")).lower()
        try:
            result = recover_oa_limited(
                doi,
                budget_seconds=budget_seconds,
                email=use_email,
                output_dir=paths.pdfs,
                timeout_per_request=timeout_per_request,
                host_cache=host_cache,
                http_json=http_json,
                http_bytes=http_bytes,
            )
        except Exception as exc:
            # A malformed metadata field or an unexpected provider response must
            # not abort the whole bounded recovery batch. Keep the row auditable
            # and let the normal fallback ladder handle it after its siblings.
            result = RecoveryResult(
                doi=doi,
                status="recovery_error",
                reason=f"{type(exc).__name__}:{exc}",
            )
        result.task_id = str(row.get("task_id") or "")
        return result

    workers = max(1, min(int(max_workers), len(targets)))
    if workers == 1:
        for row in targets:
            result = _work(row)
            results_by_task[result.task_id or result.doi] = result
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_work, row): row for row in targets}
            for future in as_completed(futures):
                result = future.result()
                results_by_task[result.task_id or result.doi] = result

    # Apply successes under lock; refresh pending + final reports.
    with batch_state_lock(paths.root):
        state = load_batch_state(paths.root)
        rows = list(state.get("rows") or [])
        for index, row in enumerate(rows):
            task_id = str(row.get("task_id") or "")
            result = results_by_task.get(task_id)
            if result is None:
                doi = clean_doi(str(row.get("doi") or row.get("input_doi") or "")).lower()
                result = results_by_task.get(doi)
            if result is None:
                continue
            updated = dict(row)
            if result.title:
                updated["title"] = result.title
            if result.authors:
                updated["authors"] = result.authors
            if result.year:
                updated["year"] = result.year
            if result.journal:
                updated["journal"] = result.journal
            if result.publisher:
                updated["publisher"] = result.publisher
            if result.doi:
                updated["doi"] = result.doi
            if result.status == "oa_downloaded" and result.file:
                updated["status"] = "oa_downloaded"
                updated["source"] = "limited_oa_recovery"
                updated["file"] = result.file
                updated["reason"] = result.reason
            else:
                # Keep prior status; attach recovery reason for audit.
                prior = str(updated.get("reason") or "").strip()
                note = f"limited_oa_recovery:{result.status}"
                if result.reason and result.reason != result.status:
                    note = f"{note}:{result.reason}"
                updated["reason"] = f"{prior}; {note}" if prior else note
            rows[index] = updated
        state["rows"] = rows
        save_batch_state(paths, state)
        _write_pending_files(
            paths,
            rows,
            manual_retry_used=bool(state.get("manual_retry_used")),
        )
        write_final_reports(paths, rows)

    ordered = [results_by_task[str(r.get("task_id") or "")] for r in targets if str(r.get("task_id") or "") in results_by_task]
    # fallback order
    if len(ordered) < len(results_by_task):
        ordered = list(results_by_task.values())
    _write_recovery_report(paths.working / "limited_oa_recovery_report.csv", ordered)
    return ordered


def _write_recovery_report(path: Path, results: list[RecoveryResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "task_id",
        "doi",
        "status",
        "file",
        "reason",
        "title",
        "authors",
        "year",
        "journal",
        "publisher",
        "elapsed_s",
        "attempts",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            writer.writerow(result.to_row())


def _resolve_metadata(
    doi: str,
    *,
    email: str,
    timeout: int,
    http_json: JsonGetter | None,
    resolver: MetadataResolver | None,
) -> MetadataResult:
    candidate = PaperCandidate(source_index=0, raw_text=doi, doi=doi, title="")
    if resolver is not None:
        return resolver.resolve_one(candidate)
    meta_resolver = MetadataResolver(email=email, http_json=http_json, timeout=timeout)
    return meta_resolver.resolve_one(candidate)


def _annotated_oa_pdf_urls(metadata: MetadataResult) -> list[str]:
    urls: list[str] = []
    chosen = choose_pdf_candidate(metadata)
    if chosen and chosen.url:
        urls.append(chosen.url)

    openalex = metadata.openalex or {}
    open_access = openalex.get("open_access") or {}
    if open_access.get("is_oa"):
        oa_url = str(open_access.get("oa_url") or "").strip()
        if oa_url and _looks_like_pdf_url(oa_url):
            urls.append(oa_url)
        best = openalex.get("best_oa_location") or {}
        for key in ("pdf_url", "url_for_pdf"):
            value = str(best.get(key) or "").strip()
            if value:
                urls.append(value)

    unpaywall = metadata.unpaywall or {}
    if unpaywall.get("is_oa"):
        location = unpaywall.get("best_oa_location") or {}
        for key in ("url_for_pdf", "url"):
            value = str(location.get(key) or "").strip()
            if value and (key == "url_for_pdf" or _looks_like_pdf_url(value)):
                urls.append(value)

    return _unique_urls(urls)


def _repository_pdf_urls(metadata: MetadataResult) -> list[str]:
    urls: list[str] = []
    openalex = metadata.openalex or {}
    for location in openalex.get("locations") or []:
        if not isinstance(location, dict):
            continue
        pdf_url = str(location.get("pdf_url") or "").strip()
        landing = str(location.get("landing_page_url") or "").strip()
        source = location.get("source") or {}
        host_blob = " ".join(
            [
                pdf_url,
                landing,
                str((source or {}).get("host_organization") or ""),
                str((source or {}).get("display_name") or ""),
            ]
        ).lower()
        if not pdf_url:
            continue
        if any(blocked in _host(pdf_url) for blocked in _PUBLISHER_HOST_BLOCKLIST_FOR_REPO):
            continue
        if any(marker in host_blob for marker in _REPO_HOST_MARKERS) or _looks_like_pdf_url(pdf_url):
            if _is_repoish_url(pdf_url) or _looks_like_pdf_url(pdf_url):
                urls.append(pdf_url)
    return _unique_urls(urls)


def _repository_landing_only(metadata: MetadataResult) -> bool:
    openalex = metadata.openalex or {}
    saw_repo_landing = False
    for location in openalex.get("locations") or []:
        if not isinstance(location, dict):
            continue
        pdf_url = str(location.get("pdf_url") or "").strip()
        landing = str(location.get("landing_page_url") or "").strip()
        blob = f"{landing} {pdf_url}".lower()
        if any(marker in blob for marker in _REPO_HOST_MARKERS):
            if pdf_url:
                return False
            saw_repo_landing = True
    return saw_repo_landing


def _try_download_pdf(
    url: str,
    *,
    step: str,
    timeout: int,
    http_bytes: BytesGetter | None,
    host_cache: HostHealthCache,
) -> tuple[bytes | None, RecoveryAttempt]:
    started = time.monotonic()
    getter = http_bytes or _default_get_bytes
    try:
        response = getter(url, dict(BROWSER_HEADERS), timeout)
    except Exception as exc:
        detail = type(exc).__name__
        message = str(exc)
        if _looks_like_connection_error(message):
            host_cache.mark_unreachable(url, "publisher_unreachable")
            return None, RecoveryAttempt(
                step=step,
                url=url,
                result="publisher_unreachable",
                detail=detail,
                elapsed_s=time.monotonic() - started,
            )
        return None, RecoveryAttempt(
            step=step,
            url=url,
            result="error",
            detail=detail,
            elapsed_s=time.monotonic() - started,
        )

    content = response.content
    if is_pdf_bytes(content):
        return content, RecoveryAttempt(
            step=step,
            url=url,
            result="pdf",
            detail=_host(url),
            elapsed_s=time.monotonic() - started,
        )

    # Not a PDF — do not mark host as permanently bad (may be HTML paywall).
    return None, RecoveryAttempt(
        step=step,
        url=url,
        result="not_pdf",
        detail=(response.content_type or "")[:80],
        elapsed_s=time.monotonic() - started,
    )


def _write_delivery_pdf(
    content: bytes,
    metadata: MetadataResult,
    *,
    output_dir: str | Path | None,
) -> Path | None:
    if not output_dir:
        return None
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    # Year-author-title at write time (metadata already resolved in Step 0).
    name = make_pdf_filename(metadata)
    target = directory / name
    if target.exists() and target.stat().st_size > 0:
        stem = target.stem
        n = 2
        while target.exists():
            target = directory / f"{stem}-{n}.pdf"
            n += 1
    target.write_bytes(content)
    return target


def _default_get_bytes(url: str, headers: dict[str, str] | None, timeout: int) -> DownloadResponse:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        return DownloadResponse(
            response.read(),
            response.headers.get("Content-Type", ""),
            response.geturl(),
        )


def _finalize_failure_status(attempts: list[RecoveryAttempt]) -> str:
    results = {a.result for a in attempts}
    if "publisher_unreachable" in results and not ({"pdf", "not_pdf"} & results):
        # Only connection failures, no body received.
        if all(
            a.result in {"publisher_unreachable", "skipped_host_cache", "ok", "empty", "error"}
            for a in attempts
            if a.step != "metadata"
        ):
            if any(a.result == "publisher_unreachable" for a in attempts):
                return "publisher_unreachable"
    if any(a.step == "repo" and a.result == "metadata_only" for a in attempts):
        return "repo_metadata_only"
    return "no_oa_pdf"


def _mdpi_cdn_alternate(url: str) -> str:
    """Map www.mdpi.com/journal/vol/iss/art/pdf → mdpi-res CDN when pattern is clear."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "mdpi.com" not in host:
        return ""
    # /2075-4701/8/7/537/pdf → metals-08-00537 style is journal-specific; skip blind guess.
    # Only rewrite when path already ends with /pdf and openalex gave versioned CDN earlier.
    path = parsed.path
    if not path.rstrip("/").endswith("/pdf"):
        return ""
    # Prefer leaving CDN discovery to OpenAlex pdf_url; no blind invent.
    return ""


def _looks_like_pdf_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    return (
        path.endswith(".pdf")
        or "/pdf" in path
        or "/epdf" in path
        or "content/pdf" in path
        or "bitstream" in path
        or "download=pdf" in query
        or "pdf=" in query
    )


def _is_repoish_url(url: str) -> bool:
    blob = url.lower()
    return any(marker in blob for marker in _REPO_HOST_MARKERS)


def _looks_like_connection_error(message: str) -> bool:
    text = message.lower()
    needles = (
        "connection",
        "timed out",
        "timeout",
        "reset",
        "unreachable",
        "ssl",
        "eof",
        "refused",
        "name or service not known",
        "getaddrinfo",
        "10061",
        "10054",
    )
    return any(n in text for n in needles)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _unique_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        value = str(url or "").strip()
        if not value or value in seen:
            continue
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
