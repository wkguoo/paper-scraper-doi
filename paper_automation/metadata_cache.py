from __future__ import annotations

import errno
import json
import math
import os
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

from doi_batch_utils import clean_doi

if os.name == "nt":
    import msvcrt
else:
    import fcntl


LOOKUP_STATUSES = frozenset(
    {"ok", "not_found", "timeout", "rate_limited", "network_error", "invalid_response"}
)
LONG_TTL_SECONDS = 30 * 24 * 60 * 60
TRANSIENT_TTL_SECONDS = 5 * 60
DEFAULT_METADATA_MAX_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class LookupOutcome:
    provider: str
    query_type: str
    query: str
    status: str
    data: dict = field(default_factory=dict)
    detail: str = ""
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def normalize_lookup_query(query_type: str, value: object) -> str:
    raw = str(value or "").strip()
    if "doi" in str(query_type).lower():
        return clean_doi(raw).lower()
    normalized = unicodedata.normalize("NFKC", raw).casefold()
    return " ".join(normalized.split())


class MetadataCache:
    def __init__(
        self,
        path: str | Path,
        *,
        now: Callable[[], float] | None = None,
        lock_timeout: float = 10.0,
        max_record_bytes: int = DEFAULT_METADATA_MAX_BYTES,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.now = now or time.time
        self.lock_timeout = float(lock_timeout)
        self.max_record_bytes = int(max_record_bytes)
        if not math.isfinite(self.lock_timeout) or self.lock_timeout < 0:
            raise ValueError("invalid_metadata_cache_lock_timeout")
        if self.max_record_bytes <= 0:
            raise ValueError("invalid_metadata_cache_max_bytes")

    def get(self, provider: str, query_type: str, query: object) -> LookupOutcome | None:
        key = self._key(provider, query_type, query)
        with _cache_lock(self.lock_path, timeout=self.lock_timeout):
            records = self._read_records_unlocked()
        now = float(self.now())
        for record in reversed(records):
            if (record["provider"], record["query_type"], record["query"]) != key:
                continue
            if float(record["expires_at"]) <= now:
                return None
            return LookupOutcome(
                provider=record["provider"],
                query_type=record["query_type"],
                query=record["query"],
                status=record["status"],
                data=dict(record.get("data") or {}),
                detail=str(record.get("detail") or ""),
                cached=True,
            )
        return None

    def put(self, outcome: LookupOutcome) -> LookupOutcome:
        provider, query_type, query = self._key(
            outcome.provider, outcome.query_type, outcome.query
        )
        status = str(outcome.status)
        if status not in LOOKUP_STATUSES or not isinstance(outcome.data, dict):
            raise ValueError("invalid_lookup_outcome")
        stored_at = float(self.now())
        ttl = LONG_TTL_SECONDS if status in {"ok", "not_found"} else TRANSIENT_TTL_SECONDS
        record = {
            "version": 1,
            "provider": provider,
            "query_type": query_type,
            "query": query,
            "status": status,
            "data": outcome.data,
            "detail": str(outcome.detail or "")[:1000],
            "stored_at": stored_at,
            "expires_at": stored_at + ttl,
        }
        encoded = (
            json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            + "\n"
        ).encode("utf-8")
        if len(encoded) > self.max_record_bytes:
            raise ValueError("metadata_response_too_large")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _cache_lock(self.lock_path, timeout=self.lock_timeout):
            # Validate all existing durable records before appending.  This keeps
            # corruption visible instead of silently building on top of it.
            self._discard_trailing_partial_unlocked()
            self._read_records_unlocked()
            with self.path.open("ab", buffering=0) as handle:
                written = handle.write(encoded)
                if written != len(encoded):
                    raise OSError("metadata_cache_short_write")
                os.fsync(handle.fileno())
        return LookupOutcome(
            provider=provider,
            query_type=query_type,
            query=query,
            status=status,
            data=dict(outcome.data),
            detail=str(outcome.detail or "")[:1000],
            cached=False,
        )

    def _key(self, provider: object, query_type: object, query: object) -> tuple[str, str, str]:
        provider_value = str(provider or "").strip().lower()
        type_value = str(query_type or "").strip().lower()
        query_value = normalize_lookup_query(type_value, query)
        if not provider_value or not type_value or not query_value:
            raise ValueError("invalid_metadata_cache_key")
        return provider_value, type_value, query_value

    def _read_records_unlocked(self) -> list[dict]:
        if not self.path.exists():
            return []
        raw = self.path.read_bytes()
        if not raw:
            return []
        lines = raw.splitlines(keepends=True)
        if lines and not lines[-1].endswith((b"\n", b"\r")):
            lines = lines[:-1]
        records: list[dict] = []
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                raise ValueError(f"metadata_cache_corrupt:line={index}")
            try:
                record = json.loads(line.decode("utf-8"))
                self._validate_record(record)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
                raise ValueError(f"metadata_cache_corrupt:line={index}") from exc
            records.append(record)
        return records

    def _discard_trailing_partial_unlocked(self) -> None:
        if not self.path.exists():
            return
        raw = self.path.read_bytes()
        if not raw or raw.endswith((b"\n", b"\r")):
            return
        newline = raw.rfind(b"\n")
        keep = newline + 1 if newline >= 0 else 0
        with self.path.open("r+b") as handle:
            handle.truncate(keep)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _validate_record(record: object) -> None:
        if not isinstance(record, dict) or record.get("version") != 1:
            raise ValueError("invalid_metadata_cache_record")
        if record.get("status") not in LOOKUP_STATUSES or not isinstance(record.get("data"), dict):
            raise ValueError("invalid_metadata_cache_record")
        for key in ("provider", "query_type", "query", "detail"):
            if not isinstance(record.get(key), str):
                raise ValueError("invalid_metadata_cache_record")
        for key in ("stored_at", "expires_at"):
            value = record.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError("invalid_metadata_cache_record")
        if float(record["expires_at"]) <= float(record["stored_at"]):
            raise ValueError("invalid_metadata_cache_record")


def _try_lock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _cache_lock(path: Path, *, timeout: float) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                _try_lock(handle)
            except OSError as exc:
                contention = (
                    isinstance(exc, BlockingIOError)
                    or exc.errno in {errno.EACCES, errno.EAGAIN}
                    or getattr(exc, "winerror", None) in {32, 33}
                )
                if not contention:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("metadata_cache_lock_timeout") from exc
                time.sleep(min(0.05, remaining))
            else:
                acquired = True
                break
        yield
    finally:
        try:
            if acquired:
                _unlock(handle)
        finally:
            handle.close()
