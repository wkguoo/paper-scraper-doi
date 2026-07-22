from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence, TextIO

from paper_automation.batch_workflow import (
    BatchRunResult,
    NORMALIZED_FIELDS,
    ZOTERO_INPUT_STATUSES,
    ZOTERO_RESULT_FIELDS,
    finalize_batch,
    load_batch_state,
    paths_from_run_dir,
    result_from_state,
    _write_latest_state_outputs,
)

BRIDGE_SCHEMA_VERSION = 1
MAX_ITEMS_PER_JOB = 100
MAX_TEXT_LENGTH = 4096
JOB_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
REQUEST_FIELDS = {
    "schema_version", "job_id", "payload_sha256", "created_at", "expires_at",
    "run_id", "library_id", "collection_name", "chunk_index", "chunk_count", "items",
}
ITEM_FIELDS = {"task_id", "doi", "title", "authors", "year"}
MANIFEST_FIELDS = {
    "schema_version", "run_id", "library_id", "collection_name", "created_at",
    "expires_at", "jobs", "manifest_sha256",
}
MANIFEST_JOB_FIELDS = {
    "job_id", "payload_sha256", "chunk_index", "chunk_count", "task_ids",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RESULT_FIELDS = {
    "schema_version", "job_id", "payload_sha256", "plugin_version",
    "zotero_version", "started_at", "finished_at", "rows",
}
RESULT_ROW_FIELDS = set(ZOTERO_RESULT_FIELDS)


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


@dataclass(frozen=True)
class BridgeRunResult:
    status: str
    bridge: BridgeBatch | None
    zotero_results: Path | None
    batch_result: BatchRunResult | None


def default_bridge_root(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    local = str(values.get("LOCALAPPDATA", "")).strip()
    if not local:
        raise ValueError("bridge_localappdata_missing")
    return Path(local) / "PaperScraperDOI" / "zotero-bridge" / "v1"


# Plugin heartbeat: refreshed by whichever open Zotero currently holds the lease.
ACTIVE_INSTANCE_MAX_AGE_SECONDS = 90


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


def _parse_bridge_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not UTC_TIMESTAMP_RE.fullmatch(value):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def read_active_bridge_instance(
    bridge_root: str | Path | None = None,
    *,
    max_age_seconds: int = ACTIVE_INSTANCE_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> dict[str, str] | None:
    """Return the open Zotero instance currently advertising as the bridge target.

    The plugin writes ``active-instance.json`` for the lease holder only. This is
    whichever Zotero is open and consuming the queue — not a fixed test profile.
    """

    paths = get_bridge_paths(bridge_root)
    marker = paths.root / "active-instance.json"
    if not marker.is_file():
        return None
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict):
        return None
    updated = _parse_bridge_utc(payload.get("updated_at"))
    if updated is None:
        return None
    clock = now if now is not None else datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    age = (clock.astimezone(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()
    if age < 0 or age > max_age_seconds:
        return None
    instance_id = str(payload.get("instance_id") or "").strip()
    if not instance_id:
        return None
    return {
        "instance_id": instance_id,
        "data_dir": str(payload.get("data_dir") or "").strip(),
        "profile_dir": str(payload.get("profile_dir") or "").strip(),
        "profile_name": str(payload.get("profile_name") or "").strip(),
        "zotero_version": str(payload.get("zotero_version") or "").strip(),
        "plugin_version": str(payload.get("plugin_version") or "").strip(),
        "updated_at": str(payload.get("updated_at") or "").strip(),
    }


def format_active_bridge_target(instance: Mapping[str, str] | None) -> str:
    if not instance:
        return (
            "未检测到正在运行的桥接插件。"
            "请打开任意已安装「文献下载桥接」的 Zotero（跟随当前打开的实例，不固定测试配置）。"
        )
    profile = instance.get("profile_name") or instance.get("profile_dir") or "未知配置"
    data_dir = instance.get("data_dir") or "未知数据目录"
    return f"桥接目标 = 当前打开的 Zotero — 配置={profile}；数据目录={data_dir}"


def _iso(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_timestamp(value: str) -> datetime:
    if not UTC_TIMESTAMP_RE.fullmatch(value):
        raise ValueError("bridge_request_time_invalid")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("bridge_request_time_invalid")
    return parsed.astimezone(timezone.utc)


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


def _state_row(row: object) -> dict[str, str]:
    if not isinstance(row, Mapping):
        raise ValueError("bridge_state_rows_invalid")
    if any(field not in row for field in NORMALIZED_FIELDS):
        raise ValueError("bridge_state_rows_invalid")
    return {
        field: str(row[field] or "").strip()
        for field in NORMALIZED_FIELDS
    }


def _validated_fallback_rows(root: Path) -> list[dict[str, str]]:
    state = load_batch_state(root)
    state_rows = state.get("rows") if isinstance(state, dict) else None
    if not isinstance(state_rows, list):
        raise ValueError("bridge_state_rows_invalid")
    normalized_state_rows = [_state_row(row) for row in state_rows]
    state_ids = [row["task_id"] for row in normalized_state_rows]
    if not state_ids or "" in state_ids or len(set(state_ids)) != len(state_ids):
        raise ValueError("bridge_state_task_invalid")
    state_positions = {task_id: index for index, task_id in enumerate(state_ids)}
    rows = _fallback_rows(root)
    if not rows:
        raise ValueError("bridge_fallback_empty")
    if len({row["task_id"] for row in rows}) != len(rows):
        raise ValueError("bridge_fallback_task_duplicate")
    previous_state_position = -1
    for row in rows:
        task_id = row["task_id"]
        if task_id not in state_positions:
            raise ValueError("bridge_fallback_task_unknown")
        state_position = state_positions[task_id]
        if (
            state_position <= previous_state_position
            or row != normalized_state_rows[state_position]
        ):
            raise ValueError("bridge_fallback_state_mismatch")
        previous_state_position = state_position
    return rows


def _validated_request_rows(
    root: Path,
    rows: Sequence[dict[str, str]] | None,
    *,
    chunk_index: int,
    chunk_count: int,
) -> list[dict[str, str]]:
    fallback_rows = _validated_fallback_rows(root)
    if (
        type(chunk_index) is not int
        or type(chunk_count) is not int
        or not 1 <= chunk_index <= chunk_count
    ):
        raise ValueError("bridge_chunk_index_invalid")
    expected_chunk_count = (
        len(fallback_rows) + MAX_ITEMS_PER_JOB - 1
    ) // MAX_ITEMS_PER_JOB
    if chunk_count != expected_chunk_count:
        raise ValueError("bridge_chunk_count_invalid")
    start = (chunk_index - 1) * MAX_ITEMS_PER_JOB
    expected_rows = fallback_rows[start:start + MAX_ITEMS_PER_JOB]
    if rows is None:
        return expected_rows
    try:
        supplied_rows = list(rows)
    except TypeError as exc:
        raise ValueError("bridge_request_rows_invalid") from exc
    if any(
        not isinstance(row, dict)
        or set(row) != set(NORMALIZED_FIELDS)
        or any(not isinstance(row[field], str) for field in NORMALIZED_FIELDS)
        for row in supplied_rows
    ):
        raise ValueError("bridge_request_rows_invalid")
    normalized_supplied_rows = [
        {field: row[field] for field in NORMALIZED_FIELDS}
        for row in supplied_rows
    ]
    if normalized_supplied_rows != expected_rows:
        raise ValueError("bridge_request_rows_invalid")
    return expected_rows


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
    selected = _validated_request_rows(
        root,
        rows,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
    )
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
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("bridge_job_id_duplicate")
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
    if type(request["schema_version"]) is not int or request["schema_version"] != BRIDGE_SCHEMA_VERSION:
        raise ValueError("bridge_schema_version_invalid")
    if not isinstance(request["job_id"], str) or not JOB_ID_RE.fullmatch(request["job_id"]):
        raise ValueError("bridge_job_id_invalid")
    scalar_fields = ("payload_sha256", "created_at", "expires_at", "run_id", "collection_name")
    if any(not isinstance(request[field], str) or not request[field] or len(request[field]) > MAX_TEXT_LENGTH for field in scalar_fields):
        raise ValueError("bridge_request_value_invalid")
    try:
        created_at = _parse_utc_timestamp(request["created_at"])
        expires_at = _parse_utc_timestamp(request["expires_at"])
    except ValueError as exc:
        raise ValueError("bridge_request_time_invalid") from exc
    if expires_at <= created_at:
        raise ValueError("bridge_request_time_invalid")
    if type(request["library_id"]) is not int or request["library_id"] <= 0:
        raise ValueError("bridge_library_id_invalid")
    if type(request["chunk_index"]) is not int or type(request["chunk_count"]) is not int:
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


def _canonical_manifest(manifest: dict) -> bytes:
    payload = {
        key: manifest[key]
        for key in sorted(MANIFEST_FIELDS - {"manifest_sha256"})
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _manifest_digest(manifest: dict) -> str:
    return hashlib.sha256(_canonical_manifest(manifest)).hexdigest()


def _manifest_path(run_dir: Path) -> Path:
    return run_dir / "working" / "zotero_bridge_jobs.json"


def _request_filename(job_id: str) -> str:
    return f"{job_id}.json"


def _result_filename(job_id: str) -> str:
    return f"{job_id}.result.json"


def _shared_request_values(requests: Sequence[dict]) -> tuple[dict, int]:
    if not requests:
        raise ValueError("bridge_manifest_jobs_invalid")
    first = requests[0]
    chunk_count = first["chunk_count"]
    expected_indexes = list(range(1, chunk_count + 1))
    if len(requests) != chunk_count or [request["chunk_index"] for request in requests] != expected_indexes:
        raise ValueError("bridge_manifest_chunks_invalid")
    shared_fields = (
        "run_id", "library_id", "collection_name", "created_at", "expires_at", "chunk_count",
    )
    if any(
        any(request[field] != first[field] for field in shared_fields)
        for request in requests[1:]
    ):
        raise ValueError("bridge_manifest_shared_values_invalid")
    return first, chunk_count


def build_bridge_manifest(requests: Sequence[dict]) -> dict:
    validated = [validate_bridge_request(request) for request in requests]
    first, _ = _shared_request_values(validated)
    task_ids: set[str] = set()
    jobs = []
    for request in validated:
        request_task_ids = [item["task_id"] for item in request["items"]]
        if task_ids.intersection(request_task_ids):
            raise ValueError("bridge_manifest_task_duplicate")
        task_ids.update(request_task_ids)
        jobs.append({
            "job_id": request["job_id"],
            "payload_sha256": request["payload_sha256"],
            "chunk_index": request["chunk_index"],
            "chunk_count": request["chunk_count"],
            "task_ids": request_task_ids,
        })
    manifest = {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "run_id": first["run_id"],
        "library_id": first["library_id"],
        "collection_name": first["collection_name"],
        "created_at": first["created_at"],
        "expires_at": first["expires_at"],
        "jobs": jobs,
        "manifest_sha256": "",
    }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    return validate_bridge_manifest(manifest)


def validate_bridge_manifest(manifest: object) -> dict:
    if not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS:
        raise ValueError("bridge_manifest_fields_invalid")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != BRIDGE_SCHEMA_VERSION:
        raise ValueError("bridge_manifest_schema_version_invalid")
    scalar_fields = ("run_id", "collection_name", "created_at", "expires_at", "manifest_sha256")
    if any(
        not isinstance(manifest[field], str)
        or not manifest[field]
        or len(manifest[field]) > MAX_TEXT_LENGTH
        for field in scalar_fields
    ):
        raise ValueError("bridge_manifest_value_invalid")
    if type(manifest["library_id"]) is not int or manifest["library_id"] <= 0:
        raise ValueError("bridge_manifest_library_id_invalid")
    try:
        created_at = _parse_utc_timestamp(manifest["created_at"])
        expires_at = _parse_utc_timestamp(manifest["expires_at"])
    except ValueError as exc:
        raise ValueError("bridge_manifest_time_invalid") from exc
    if expires_at <= created_at:
        raise ValueError("bridge_manifest_time_invalid")
    jobs = manifest["jobs"]
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("bridge_manifest_jobs_invalid")
    job_ids: set[str] = set()
    task_ids: set[str] = set()
    chunk_counts: set[int] = set()
    chunk_indexes: list[int] = []
    for job in jobs:
        if not isinstance(job, dict) or set(job) != MANIFEST_JOB_FIELDS:
            raise ValueError("bridge_manifest_job_fields_invalid")
        if not isinstance(job["job_id"], str) or not JOB_ID_RE.fullmatch(job["job_id"]):
            raise ValueError("bridge_manifest_job_id_invalid")
        if job["job_id"] in job_ids:
            raise ValueError("bridge_manifest_job_id_duplicate")
        job_ids.add(job["job_id"])
        if not isinstance(job["payload_sha256"], str) or not SHA256_RE.fullmatch(job["payload_sha256"]):
            raise ValueError("bridge_manifest_payload_hash_invalid")
        if type(job["chunk_index"]) is not int or type(job["chunk_count"]) is not int:
            raise ValueError("bridge_manifest_chunks_invalid")
        if not 1 <= job["chunk_index"] <= job["chunk_count"]:
            raise ValueError("bridge_manifest_chunks_invalid")
        chunk_counts.add(job["chunk_count"])
        chunk_indexes.append(job["chunk_index"])
        job_task_ids = job["task_ids"]
        if not isinstance(job_task_ids, list) or not 1 <= len(job_task_ids) <= MAX_ITEMS_PER_JOB:
            raise ValueError("bridge_manifest_task_ids_invalid")
        for task_id in job_task_ids:
            if not isinstance(task_id, str) or not task_id or len(task_id) > MAX_TEXT_LENGTH:
                raise ValueError("bridge_manifest_task_ids_invalid")
            if task_id in task_ids:
                raise ValueError("bridge_manifest_task_duplicate")
            task_ids.add(task_id)
    if len(chunk_counts) != 1:
        raise ValueError("bridge_manifest_chunks_invalid")
    chunk_count = next(iter(chunk_counts))
    if len(jobs) != chunk_count or chunk_indexes != list(range(1, chunk_count + 1)):
        raise ValueError("bridge_manifest_chunks_invalid")
    if not SHA256_RE.fullmatch(manifest["manifest_sha256"]):
        raise ValueError("bridge_manifest_hash_invalid")
    if manifest["manifest_sha256"] != _manifest_digest(manifest):
        raise ValueError("bridge_manifest_hash_invalid")
    return manifest


def _write_atomic_exclusive(
    path: Path,
    write_content: Callable[[TextIO], None],
    *,
    encoding: str,
    newline: str,
) -> None:
    descriptor, name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding=encoding, newline=newline) as handle:
            write_content(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json_atomic_exclusive(path: Path, payload: dict) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"

    def write_json(handle: TextIO) -> None:
        handle.write(serialized)

    _write_atomic_exclusive(
        path,
        write_json,
        encoding="utf-8",
        newline="\n",
    )


def _load_existing_request(paths: BridgePaths, job_id: str) -> tuple[Path, dict] | None:
    for path in (
        paths.inbox / _request_filename(job_id),
        paths.processing / _request_filename(job_id),
        paths.archive / _request_filename(job_id),
    ):
        if path.is_file():
            return path, validate_bridge_request(json.loads(path.read_text(encoding="utf-8")))
    return None


def _publish_or_reuse_request(paths: BridgePaths, root: Path, request: dict) -> BridgeJob:
    validated = validate_bridge_request(request)
    existing = _load_existing_request(paths, validated["job_id"])
    if existing is None:
        request_path = paths.inbox / _request_filename(validated["job_id"])
        try:
            _write_json_atomic_exclusive(request_path, validated)
        except FileExistsError:
            existing = _load_existing_request(paths, validated["job_id"])
            if existing is None:
                raise ValueError("bridge_job_id_conflict")
        else:
            existing = (request_path, validated)
    request_path, existing_request = existing
    if existing_request["payload_sha256"] != validated["payload_sha256"]:
        raise ValueError("bridge_job_id_conflict")
    return BridgeJob(
        job_id=validated["job_id"],
        payload_sha256=validated["payload_sha256"],
        request_path=request_path,
        result_path=paths.outbox / _result_filename(validated["job_id"]),
        run_dir=root,
        chunk_index=validated["chunk_index"],
        chunk_count=validated["chunk_count"],
    )


def _read_manifest(path: Path) -> dict:
    try:
        return validate_bridge_manifest(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("bridge_manifest_invalid") from exc


def _rebuild_requests_from_manifest(root: Path, library_id: int, manifest: dict) -> list[dict]:
    if manifest["run_id"] != root.name or library_id != manifest["library_id"]:
        raise ValueError("bridge_batch_manifest_conflict")
    job_ids = tuple(job["job_id"] for job in manifest["jobs"])
    try:
        requests = build_bridge_requests(
            root,
            library_id=library_id,
            job_ids=job_ids,
            now=_parse_utc_timestamp(manifest["created_at"]),
            collection_name=manifest["collection_name"],
        )
    except ValueError as exc:
        raise ValueError("bridge_batch_manifest_conflict") from exc
    try:
        if (
            [request["payload_sha256"] for request in requests]
            != [job["payload_sha256"] for job in manifest["jobs"]]
            or any(request["created_at"] != manifest["created_at"] for request in requests)
            or any(request["expires_at"] != manifest["expires_at"] for request in requests)
            or any(request["collection_name"] != manifest["collection_name"] for request in requests)
            or any(
                [item["task_id"] for item in request["items"]] != job["task_ids"]
                for request, job in zip(requests, manifest["jobs"], strict=True)
            )
        ):
            raise ValueError("bridge_batch_manifest_conflict")
    except ValueError:
        raise
    return requests


def queue_bridge_jobs(
    run_dir: str | Path,
    *,
    library_id: int = 1,
    bridge_root: str | Path | None = None,
    job_ids: Sequence[str] | None = None,
    now: datetime | None = None,
) -> BridgeBatch:
    root = Path(run_dir).expanduser().resolve()
    paths = get_bridge_paths(bridge_root, create=True)
    record = _manifest_path(root)
    if record.is_file():
        manifest = _read_manifest(record)
        requests = _rebuild_requests_from_manifest(root, library_id, manifest)
    else:
        requests = build_bridge_requests(
            root,
            library_id=library_id,
            job_ids=job_ids,
            now=now,
        )
        manifest = build_bridge_manifest(requests)
        try:
            _write_json_atomic_exclusive(record, manifest)
        except FileExistsError:
            manifest = _read_manifest(record)
            requests = _rebuild_requests_from_manifest(root, library_id, manifest)
    jobs = tuple(_publish_or_reuse_request(paths, root, request) for request in requests)
    return BridgeBatch(run_id=manifest["run_id"], manifest_path=record, jobs=jobs)


def _validated_bridge_batch(bridge: object) -> tuple[Path, tuple[BridgeJob, ...]]:
    if not isinstance(bridge, BridgeBatch) or not isinstance(bridge.jobs, tuple) or not bridge.jobs:
        raise ValueError("bridge_batch_jobs_invalid")
    if any(not isinstance(job, BridgeJob) for job in bridge.jobs):
        raise ValueError("bridge_batch_jobs_invalid")

    root = Path(bridge.jobs[0].run_dir).expanduser().resolve()
    record = _manifest_path(root)
    if (
        not isinstance(bridge.run_id, str)
        or bridge.run_id != root.name
        or Path(bridge.manifest_path).expanduser().resolve() != record
    ):
        raise ValueError("bridge_batch_identity_invalid")

    manifest = _read_manifest(record)
    if manifest["run_id"] != bridge.run_id or len(manifest["jobs"]) != len(bridge.jobs):
        raise ValueError("bridge_batch_identity_invalid")

    for job, manifest_job in zip(bridge.jobs, manifest["jobs"], strict=True):
        request_path = Path(job.request_path).expanduser()
        result_path = Path(job.result_path).expanduser()
        if (
            Path(job.run_dir).expanduser().resolve() != root
            or job.job_id != manifest_job["job_id"]
            or job.payload_sha256 != manifest_job["payload_sha256"]
            or job.chunk_index != manifest_job["chunk_index"]
            or job.chunk_count != manifest_job["chunk_count"]
            or request_path.name != _request_filename(job.job_id)
            or request_path.parent.name not in {"inbox", "processing", "archive"}
            or result_path.name != _result_filename(job.job_id)
            or result_path.parent.name != "outbox"
        ):
            raise ValueError("bridge_batch_identity_invalid")
    return root, bridge.jobs


def validate_bridge_result(
    result: object,
    job: BridgeJob,
    expected_ids: set[str],
) -> dict:
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        raise ValueError("bridge_result_fields_invalid")
    if type(result["schema_version"]) is not int or result["schema_version"] != BRIDGE_SCHEMA_VERSION:
        raise ValueError("bridge_schema_version_invalid")
    if result["job_id"] != job.job_id or result["payload_sha256"] != job.payload_sha256:
        raise ValueError("bridge_result_identity_invalid")
    if (
        not isinstance(expected_ids, set)
        or not expected_ids
        or any(not isinstance(task_id, str) or not task_id for task_id in expected_ids)
    ):
        raise ValueError("bridge_result_expected_tasks_invalid")
    scalar_fields = ("plugin_version", "zotero_version", "started_at", "finished_at")
    if any(
        not isinstance(result[field], str)
        or not result[field]
        or len(result[field]) > MAX_TEXT_LENGTH
        for field in scalar_fields
    ):
        raise ValueError("bridge_result_value_invalid")
    try:
        started_at = _parse_utc_timestamp(result["started_at"])
        finished_at = _parse_utc_timestamp(result["finished_at"])
    except ValueError as exc:
        raise ValueError("bridge_result_time_invalid") from exc
    if finished_at < started_at:
        raise ValueError("bridge_result_time_invalid")

    rows = result["rows"]
    if not isinstance(rows, list) or len(rows) != len(expected_ids):
        raise ValueError("bridge_result_count_invalid")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != RESULT_ROW_FIELDS:
            raise ValueError("bridge_result_row_fields_invalid")
        if any(
            not isinstance(row[field], str) or len(row[field]) > MAX_TEXT_LENGTH
            for field in RESULT_ROW_FIELDS
        ):
            raise ValueError("bridge_result_row_value_invalid")
        task_id = row["task_id"]
        if task_id in seen:
            raise ValueError("bridge_result_task_duplicate")
        if task_id not in expected_ids:
            raise ValueError("bridge_result_task_unknown")
        if row["status"] not in ZOTERO_INPUT_STATUSES:
            raise ValueError("bridge_result_status_invalid")
        if row["status"] in {"existing_pdf", "downloaded"} and not row["zotero_item_id"]:
            raise ValueError("bridge_result_item_id_missing")
        seen.add(task_id)
    if seen != expected_ids:
        raise ValueError("bridge_result_tasks_missing")
    return result


def _read_request_for_job(job: BridgeJob) -> dict:
    request_path = Path(job.request_path).expanduser()
    if (
        request_path.name != _request_filename(job.job_id)
        or request_path.parent.name not in {"inbox", "processing", "archive"}
    ):
        raise ValueError("bridge_request_identity_invalid")
    try:
        paths = get_bridge_paths(request_path.parent.parent)
        existing = _load_existing_request(paths, job.job_id)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("bridge_request_invalid") from exc
    if existing is None:
        raise ValueError("bridge_request_missing")
    _, request = existing
    if request["job_id"] != job.job_id or request["payload_sha256"] != job.payload_sha256:
        raise ValueError("bridge_request_identity_invalid")
    return request


def _validated_rows_for_job(job: BridgeJob) -> tuple[list[str], list[dict[str, str]]]:
    request = _read_request_for_job(job)
    expected_ids = [item["task_id"] for item in request["items"]]
    result_path = Path(job.result_path)
    if not result_path.is_file():
        raise ValueError("bridge_result_missing")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("bridge_result_invalid") from exc
    validated = validate_bridge_result(result, job, set(expected_ids))
    return expected_ids, validated["rows"]


def _write_csv_atomic_exclusive(path: Path, rows: Sequence[dict[str, str]]) -> None:
    def write_csv(handle: TextIO) -> None:
        writer = csv.writer(handle)
        writer.writerow(ZOTERO_RESULT_FIELDS)
        for row in rows:
            writer.writerow([row[field] for field in ZOTERO_RESULT_FIELDS])

    _write_atomic_exclusive(
        path,
        write_csv,
        encoding="utf-8-sig",
        newline="",
    )


def _write_result_csv_exclusive(
    run_dir: Path,
    rows: Sequence[dict[str, str]],
    now: datetime | None = None,
) -> Path:
    working = run_dir / "working"
    if not working.is_dir():
        raise ValueError("bridge_working_missing")
    canonical = working / "zotero_results.csv"
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    candidates = [canonical]
    candidates.extend(
        working / f"zotero_results_retry_{stamp}{'' if number == 1 else '_' + str(number)}.csv"
        for number in range(1, 10000)
    )
    for candidate in candidates:
        try:
            _write_csv_atomic_exclusive(candidate, rows)
        except FileExistsError:
            continue
        return candidate
    raise OSError("bridge_result_filename_exhausted")


def publish_zotero_results_csv(
    run_dir: str | Path,
    rows: Sequence[dict[str, str]],
    *,
    now: datetime | None = None,
) -> Path:
    """Publish already-validated Zotero rows without overwriting an existing CSV."""

    root = Path(run_dir).expanduser().resolve()
    return _write_result_csv_exclusive(root, rows, now=now)


def consume_bridge_batch(bridge: BridgeBatch, *, now: datetime | None = None) -> Path:
    root, jobs = _validated_bridge_batch(bridge)
    rows_by_task: dict[str, dict[str, str]] = {}
    ordered_ids: list[str] = []
    for job in jobs:
        expected_ids, rows = _validated_rows_for_job(job)
        ordered_ids.extend(expected_ids)
        for row in rows:
            if row["task_id"] in rows_by_task:
                raise ValueError("bridge_result_task_duplicate")
            rows_by_task[row["task_id"]] = row
    if len(set(ordered_ids)) != len(ordered_ids) or set(rows_by_task) != set(ordered_ids):
        raise ValueError("bridge_result_tasks_missing")
    ordered_rows = [rows_by_task[task_id] for task_id in ordered_ids]
    return publish_zotero_results_csv(root, ordered_rows, now=now)


def _archive_completed_manifest(bridge: BridgeBatch) -> None:
    root, _ = _validated_bridge_batch(bridge)
    record = _manifest_path(root)
    manifest = _read_manifest(record)
    history = record.parent / "zotero_bridge_history"
    history.mkdir(parents=True, exist_ok=True)
    archived = history / f"{manifest['manifest_sha256']}.json"
    try:
        os.link(record, archived)
    except FileExistsError:
        if _read_manifest(archived)["manifest_sha256"] != manifest["manifest_sha256"]:
            raise ValueError("bridge_manifest_invalid")
    record.unlink()


def run_zotero_bridge(
    run_dir: str | Path,
    *,
    library_id: int = 1,
    wait_seconds: int = 0,
    poll_seconds: float = 1.0,
    bridge_root: str | Path | None = None,
) -> BridgeRunResult:
    """Queue or resume one Zotero bridge batch without rerunning download stages."""

    if type(wait_seconds) is not int or not 0 <= wait_seconds <= 86400:
        raise ValueError("bridge_wait_seconds_invalid")
    if (
        isinstance(poll_seconds, bool)
        or not isinstance(poll_seconds, (int, float))
        or not 0 < poll_seconds < float("inf")
    ):
        raise ValueError("bridge_poll_seconds_invalid")

    root = Path(run_dir).expanduser().resolve()
    try:
        fallback_rows = _fallback_rows(root)
    except OSError as exc:
        raise ValueError("bridge_fallback_file_missing") from exc
    if not fallback_rows:
        paths = paths_from_run_dir(root)
        state = load_batch_state(paths.root)
        initial_result = result_from_state(paths, state)
        if initial_result.zotero_fallback_count:
            raise ValueError("bridge_fallback_state_mismatch")
        _write_latest_state_outputs(
            paths,
            state,
            pending_manual_retry_used=bool(state.get("manual_retry_used")),
        )
        batch_result = result_from_state(paths, state)
        return BridgeRunResult("no_fallback", None, None, batch_result)

    bridge = queue_bridge_jobs(root, library_id=library_id, bridge_root=bridge_root)
    try:
        print(format_active_bridge_target(read_active_bridge_instance(bridge_root)))
    except Exception:
        # Target discovery is advisory only; never block queueing on it.
        print(format_active_bridge_target(None))
    deadline = time.monotonic() + wait_seconds
    while any(not job.result_path.is_file() for job in bridge.jobs):
        if time.monotonic() >= deadline:
            return BridgeRunResult("awaiting_confirmation", bridge, None, None)
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))

    selected = consume_bridge_batch(bridge)
    batch_result = finalize_batch(root, selected)
    _archive_completed_manifest(bridge)
    return BridgeRunResult("finalized", bridge, selected, batch_result)
