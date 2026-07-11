from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from paper_automation.batch_workflow import (
    NORMALIZED_FIELDS,
    ZOTERO_RESULT_FIELDS,
    load_batch_state,
)

BRIDGE_SCHEMA_VERSION = 1
MAX_ITEMS_PER_JOB = 100
MAX_TEXT_LENGTH = 4096
JOB_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
REQUEST_FIELDS = {
    "schema_version", "job_id", "payload_sha256", "created_at", "expires_at",
    "run_id", "library_id", "collection_name", "chunk_index", "chunk_count", "items",
}
ITEM_FIELDS = {"task_id", "doi", "title", "authors", "year"}


@dataclass(frozen=True)
class BridgePaths:
    root: Path
    inbox: Path
    processing: Path
    outbox: Path
    archive: Path
    state: Path


@dataclass(frozen=True)
class BridgeJob:
    job_id: str
    payload_sha256: str
    request_path: Path
    result_path: Path
    run_dir: Path
    chunk_index: int
    chunk_count: int


@dataclass(frozen=True)
class BridgeBatch:
    run_id: str
    manifest_path: Path
    jobs: tuple[BridgeJob, ...]


def default_bridge_root(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    local = str(values.get("LOCALAPPDATA", "")).strip()
    if not local:
        raise ValueError("bridge_localappdata_missing")
    return Path(local) / "PaperScraperDOI" / "zotero-bridge" / "v1"


def get_bridge_paths(root: str | Path | None = None, *, create: bool = False) -> BridgePaths:
    base = Path(root) if root is not None else default_bridge_root()
    paths = BridgePaths(
        root=base, inbox=base / "inbox", processing=base / "processing",
        outbox=base / "outbox", archive=base / "archive", state=base / "plugin-state.json",
    )
    if create:
        for path in (paths.inbox, paths.processing, paths.outbox, paths.archive):
            path.mkdir(parents=True, exist_ok=True)
    return paths


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_payload(request: dict) -> bytes:
    payload = {key: request[key] for key in sorted(REQUEST_FIELDS - {"payload_sha256"})}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(request: dict) -> str:
    return hashlib.sha256(_canonical_payload(request)).hexdigest()


def _fallback_rows(run_dir: Path) -> list[dict[str, str]]:
    path = run_dir / "working" / "zotero_fallback.csv"
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != NORMALIZED_FIELDS:
            raise ValueError("bridge_fallback_fields_invalid")
        return [{key: str(value or "").strip() for key, value in row.items()} for row in reader]


def _validated_fallback_rows(root: Path) -> list[dict[str, str]]:
    state = load_batch_state(root)
    state_ids = {str(row.get("task_id", "")) for row in state["rows"]}
    rows = _fallback_rows(root)
    if not rows:
        raise ValueError("bridge_fallback_empty")
    if any(row["task_id"] not in state_ids for row in rows):
        raise ValueError("bridge_fallback_task_unknown")
    if len({row["task_id"] for row in rows}) != len(rows):
        raise ValueError("bridge_fallback_task_duplicate")
    return rows


def _request_items(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return [{
        "task_id": row["task_id"],
        "doi": row["doi"].strip().lower(),
        "title": row["title"],
        "authors": row["authors"],
        "year": row["year"],
    } for row in rows]


def build_bridge_request(
    run_dir: str | Path,
    *,
    library_id: int,
    job_id: str | None = None,
    now: datetime | None = None,
    rows: Sequence[dict[str, str]] | None = None,
    collection_name: str | None = None,
    chunk_index: int = 1,
    chunk_count: int = 1,
) -> dict:
    root = Path(run_dir).expanduser().resolve()
    selected = list(rows) if rows is not None else _validated_fallback_rows(root)
    instant = now or datetime.now(timezone.utc)
    request = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "job_id": job_id or str(uuid.uuid4()),
        "payload_sha256": "",
        "created_at": _iso(instant),
        "expires_at": _iso(instant + timedelta(hours=24)),
        "run_id": root.name,
        "library_id": library_id,
        "collection_name": collection_name or "Codex下载回退_" + instant.astimezone().strftime("%Y%m%d_%H%M%S"),
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "items": _request_items(selected),
    }
    request["payload_sha256"] = _digest(request)
    return validate_bridge_request(request)


def build_bridge_requests(
    run_dir: str | Path,
    *,
    library_id: int,
    job_ids: Sequence[str] | None = None,
    now: datetime | None = None,
    collection_name: str | None = None,
) -> list[dict]:
    root = Path(run_dir).expanduser().resolve()
    rows = _validated_fallback_rows(root)
    chunk_count = (len(rows) + MAX_ITEMS_PER_JOB - 1) // MAX_ITEMS_PER_JOB
    identifiers = tuple(job_ids) if job_ids is not None else tuple(str(uuid.uuid4()) for _ in range(chunk_count))
    if len(identifiers) != chunk_count:
        raise ValueError("bridge_job_count_invalid")
    instant = now or datetime.now(timezone.utc)
    shared_collection_name = collection_name or "Codex下载回退_" + instant.astimezone().strftime("%Y%m%d_%H%M%S")
    return [
        build_bridge_request(
            root,
            library_id=library_id,
            job_id=identifiers[index - 1],
            now=instant,
            rows=rows[(index - 1) * MAX_ITEMS_PER_JOB:index * MAX_ITEMS_PER_JOB],
            collection_name=shared_collection_name,
            chunk_index=index,
            chunk_count=chunk_count,
        )
        for index in range(1, chunk_count + 1)
    ]


def validate_bridge_request(request: object) -> dict:
    if not isinstance(request, dict) or set(request) != REQUEST_FIELDS:
        raise ValueError("bridge_request_fields_invalid")
    if request["schema_version"] != BRIDGE_SCHEMA_VERSION:
        raise ValueError("bridge_schema_version_invalid")
    if not isinstance(request["job_id"], str) or not JOB_ID_RE.fullmatch(request["job_id"]):
        raise ValueError("bridge_job_id_invalid")
    scalar_fields = ("payload_sha256", "created_at", "expires_at", "run_id", "collection_name")
    if any(not isinstance(request[field], str) or not request[field] or len(request[field]) > MAX_TEXT_LENGTH for field in scalar_fields):
        raise ValueError("bridge_request_value_invalid")
    if not isinstance(request["library_id"], int) or request["library_id"] <= 0:
        raise ValueError("bridge_library_id_invalid")
    if not isinstance(request["chunk_index"], int) or not isinstance(request["chunk_count"], int):
        raise ValueError("bridge_chunk_index_invalid")
    if not 1 <= request["chunk_index"] <= request["chunk_count"]:
        raise ValueError("bridge_chunk_index_invalid")
    items = request["items"]
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS_PER_JOB:
        raise ValueError("bridge_item_count_invalid")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != ITEM_FIELDS:
            raise ValueError("bridge_item_fields_invalid")
        if any(not isinstance(item[field], str) or len(item[field]) > MAX_TEXT_LENGTH for field in ITEM_FIELDS):
            raise ValueError("bridge_item_value_invalid")
        task_id = item["task_id"]
        if not task_id:
            raise ValueError("bridge_task_id_missing")
        if task_id in seen:
            raise ValueError("bridge_task_id_duplicate")
        seen.add(task_id)
    if request["payload_sha256"] != _digest(request):
        raise ValueError("bridge_payload_hash_invalid")
    return request
