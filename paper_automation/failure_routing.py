"""Central failure classification for batch next-hop routing.

Keeps download-stage, retry-failed, and Zotero fallback decisions consistent.
Elsevier/ScienceDirect stage logic is intentionally not owned here.
"""
from __future__ import annotations

from doi_batch_utils import clean_doi

# Statuses that may enter Zotero bridge (must still have a non-empty DOI).
ZOTERO_ELIGIBLE_STATUSES = frozenset(
    {
        "unsupported_publisher",
        "not_pdf_response",
        "error",
        "auth_required",
        "login_required",
        "captcha",
        "oa_failed",
        "institutional_failed",
        "no_open_pdf",
        "plugin_error",
        "no_pdf",
        "not_found",
        "no_attachment",
        "download_failed",
        "zotero_unavailable",
        "zotero_api_unavailable",
        "job_expired",
        "job_id_conflict",
    }
)

# Never re-queue these as Zotero fallback (audit / success / no DOI work).
# Note: plugin_error / no_pdf / download_failed remain re-queueable so a partial
# bridge batch can resume remaining DOI-bearing failures.
ZOTERO_EXCLUDED_STATUSES = frozenset(
    {
        "metadata_uncertain",
        "needs_review",
        "duplicate",
        "empty",
        "invalid",
        "user_cancelled",
        "zotero_downloaded",
        "zotero_existing_pdf",
        "oa_downloaded",
        "institutional_downloaded",
    }
)

# retry-failed default whitelist (network / capture flakiness).
RETRY_ELIGIBLE_STATUSES = frozenset(
    {
        "not_pdf_response",
        "error",
    }
)

RETRY_REASON_TOKENS = (
    "urlopen",
    "timeout",
    "timed out",
    "network",
    "connection",
    "winerror",
    "temporarily",
    "reset by peer",
    "10061",
    "10054",
    "not_pdf_response",
    "network_pdf_not_captured",
    "browser_debug_port",
    "circuit_breaker",
    "rate_limited",
    "api_circuit_open",
)

RETRY_EXCLUDED_STATUSES = frozenset(
    {
        "unsupported_publisher",
        "metadata_uncertain",
        "needs_review",
        "plugin_error",
        "duplicate",
        "invalid",
        "empty",
        "oa_downloaded",
        "institutional_downloaded",
        "zotero_downloaded",
        "zotero_existing_pdf",
    }
)


def has_doi(row_or_doi: object) -> bool:
    if isinstance(row_or_doi, dict):
        doi = row_or_doi.get("doi") or row_or_doi.get("input_doi") or ""
    else:
        doi = row_or_doi
    return bool(clean_doi(str(doi or "")).strip())


def is_zotero_eligible(status: object, reason: object = "", *, doi: object = "") -> bool:
    """True when a failed row should enter zotero_fallback.csv."""

    status_value = str(status or "").strip().lower()
    reason_value = str(reason or "").strip().lower()
    if not has_doi(doi):
        return False
    if status_value in {"metadata_uncertain", "needs_review", "invalid", "empty", "duplicate"}:
        return False
    if status_value in ZOTERO_ELIGIBLE_STATUSES:
        return True
    # Auth-ish failures sometimes only appear in reason text.
    if any(token in f"{status_value} {reason_value}" for token in ("auth_required", "captcha", "login_required", "turnstile")):
        return True
    # Generic non-success with DOI that completed a download attempt.
    if status_value and status_value not in ZOTERO_EXCLUDED_STATUSES:
        if status_value not in {
            "oa_downloaded",
            "institutional_downloaded",
            "zotero_downloaded",
            "zotero_existing_pdf",
            "pending",
        }:
            return True
    return False


def is_retry_eligible(status: object, reason: object = "", *, retry_all: bool = False) -> bool:
    """True when retry-failed should re-run institutional download for this row."""

    status_value = str(status or "").strip().lower()
    reason_value = str(reason or "").strip().lower()
    success_or_duplicate = {
        "oa_downloaded",
        "institutional_downloaded",
        "zotero_downloaded",
        "zotero_existing_pdf",
        "duplicate",
    }
    if status_value in success_or_duplicate:
        return False
    if retry_all:
        # Broad mode still skips pure review rows with no download attempt value.
        if status_value in {"metadata_uncertain", "needs_review", "empty", "invalid"}:
            return False
        return True
    if status_value in RETRY_EXCLUDED_STATUSES:
        return False
    if status_value in RETRY_ELIGIBLE_STATUSES:
        return True
    blob = f"{status_value} {reason_value}"
    return any(token in blob for token in RETRY_REASON_TOKENS)


def is_noise_title_line(title: object, reason: object = "") -> bool:
    """Section headers / notes that must not become download tasks."""

    text = str(title or "").strip()
    reason_value = str(reason or "").strip().lower()
    if not text:
        return True
    if text.startswith("#"):
        return True
    if reason_value in {"not_probable_title", "insufficient_bibliographic_context"}:
        # Keep real paper titles that only lack context when title-mode is on;
        # pure notes still filtered by patterns below.
        pass
    lowered = text.lower()
    noise_prefixes = (
        "题名检索",
        "旧刊 doi",
        "待补文献",
        "可能相关",
        "推荐理由",
        "备注",
        "说明",
        "注释",
        "doi:",
        "https://doi.org",
    )
    if any(lowered.startswith(prefix) for prefix in noise_prefixes):
        return True
    # Section labels like "A · 必补" / "B · 强烈建议" / "C · …"
    if len(text) <= 40 and ("·" in text or "•" in text) and any(
        token in text for token in ("必补", "建议", "可选", "理论", "相关")
    ):
        return True
    if text in {"A", "B", "C", "D"}:
        return True
    return False


def classify_failure_next_hop(
    status: object,
    reason: object = "",
    *,
    doi: object = "",
    retry_all: bool = False,
) -> str:
    """Return one of: success, review, retry, zotero, drop."""

    status_value = str(status or "").strip().lower()
    if status_value in {
        "oa_downloaded",
        "institutional_downloaded",
        "zotero_downloaded",
        "zotero_existing_pdf",
        "pdf_downloaded",
    }:
        return "success"
    if status_value in {"metadata_uncertain", "needs_review", "invalid", "empty"}:
        return "review"
    if not has_doi(doi):
        return "drop"
    if is_retry_eligible(status_value, reason, retry_all=retry_all):
        return "retry"
    if is_zotero_eligible(status_value, reason, doi=doi):
        return "zotero"
    return "review"
