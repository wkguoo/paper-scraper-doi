# Zotero 9 Project Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe, resumable project-side file-queue bridge that sends only `zotero_fallback.csv` rows to Zotero and automatically reconciles validated results through the existing finalization pipeline.

**Architecture:** `paper_automation.zotero_bridge` owns the fixed LocalAppData queue, strict JSON contracts, atomic publication, idempotency, polling, and exclusive result-CSV creation. `paper_batch.py zotero` is a thin beginner-facing CLI that queues or resumes one batch and invokes existing `finalize_batch()` only after a fully valid bridge result. The module never writes Zotero data and never trusts attachment paths without the existing finalizer checks.

**Tech Stack:** Python 3, `pathlib`, `dataclasses`, `json`, `csv`, `hashlib`, `uuid`, `datetime`, `unittest`; existing `paper_automation.batch_workflow` state and PDF validation.

## Global Constraints

- Target Windows, Zotero 9.0.6, and Python 3.
- Use `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1` by default; do not listen on a network port.
- Only rows currently present in `working\zotero_fallback.csv` may enter a bridge request.
- Every request/result uses `schema_version: 1`, a lowercase UUID job ID, a SHA-256 payload digest, and strict known fields.
- A logical fallback set containing more than `MAX_ITEMS_PER_JOB` rows is split in original CSV order into ordered subjobs of at most 100 rows. Every subjob for the same batch carries the same `run_id`, `collection_name`, `created_at`, and `expires_at`, plus one-based `chunk_index` and shared `chunk_count`.
- The plugin must not show a confirmation for a multi-job `run_id` until it has received every chunk index from `1` through `chunk_count`; a partially published batch is only `awaiting_chunks`.
- Persist the ordered batch identity at `working\zotero_bridge_jobs.json`. Its manifest lists every job ID, payload digest, chunk position, and task ID before the project treats the queue as resumable; replay validates the whole manifest and never derives a new collection name or new IDs.
- Publish JSON and CSV atomically or with exclusive creation; never overwrite an existing request, result, retry CSV, input, PDF, or Zotero attachment.
- Keep original project downloads and the one-`resume` rule unchanged.
- Do not accept arbitrary code, commands, output paths, or URLs from bridge payloads.
- Never log Cookie values, passwords, API keys, or institutional session content.
- Do not use Sci-Hub, Anna's Archive, LibGen, or any other shadow source; do not bypass CAPTCHA.
- Preserve the current five-column Zotero CSV contract exactly: `task_id,zotero_item_id,attachment_path,status,reason`.
- Do not run the Windows packaging script.
- Append every project change to `CHANGELOG.md` and keep unrelated worktree changes untouched.

---

## File Structure

- Create `paper_automation/zotero_bridge.py`: queue paths, request/result schema, atomic JSON I/O, job reuse, result conversion, and orchestration.
- Create `tests/test_zotero_bridge.py`: isolated LocalAppData fixtures and project-side contract/security tests.
- Modify `paper_automation/batch_workflow.py`: extend accepted Zotero failure states and expose a safe read-only run-path helper.
- Modify `paper_batch.py`: add the `zotero` subcommand and fixed user-facing exit/status messages.
- Modify `tests/test_batch_workflow.py`: CLI contract tests only; bridge internals remain in the focused test module.
- Modify `CHANGELOG.md`: append one entry per completed task.

### Task 1: Define bridge paths and strict request contract

**Files:**
- Create: `paper_automation/zotero_bridge.py`
- Create: `tests/test_zotero_bridge.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `load_batch_state(run_dir) -> dict`, `NORMALIZED_FIELDS`, and `ZOTERO_RESULT_FIELDS` from `paper_automation.batch_workflow`.
- Produces: `BridgePaths`, `BridgeJob`, `BridgeBatch`, `default_bridge_root()`, `get_bridge_paths()`, `build_bridge_request()`, `build_bridge_requests()`, and `validate_bridge_request()`.

- [ ] **Step 1: Write failing path and request tests**

Add this complete initial test module:

```python
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class ZoteroBridgeRequestTests(unittest.TestCase):
    def _run(self, root: Path, fallback_count: int = 1) -> Path:
        from paper_automation.batch_stages import BatchOptions
        from paper_automation.batch_workflow import NORMALIZED_FIELDS, create_batch_paths, save_batch_state

        paths = create_batch_paths(root, now=datetime(2026, 7, 11, 9, 0, 0))
        rows = []
        for number in range(1, fallback_count + 1):
            rows.append({
                field: value
                for field, value in zip(
                    NORMALIZED_FIELDS,
                    [
                        f"paper-{number:04d}", str(number), f"10.1000/{number:04d}", "", f"10.1000/{number:04d}",
                        f"Example Paper {number}", "A. Author", "Journal", "2025", "Publisher",
                        "no_open_pdf", "project", "", "no_legal_open_pdf",
                    ],
                )
            })
        save_batch_state(paths, {
            "version": 1,
            "run_dir": str(paths.root),
            "manual_retry_used": False,
            "options": asdict(BatchOptions()),
            "rows": rows,
        })
        with paths.zotero_fallback.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=NORMALIZED_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return paths.root

    def test_default_root_uses_local_appdata(self) -> None:
        from paper_automation.zotero_bridge import default_bridge_root

        root = default_bridge_root({"LOCALAPPDATA": r"C:\Users\student\AppData\Local"})
        self.assertEqual(
            root,
            Path(r"C:\Users\student\AppData\Local\PaperScraperDOI\zotero-bridge\v1"),
        )

    def test_request_contains_only_current_fallback_metadata(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_request

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run(Path(tmp))
            request = build_bridge_request(
                run_dir,
                library_id=1,
                job_id="11111111-1111-4111-8111-111111111111",
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            )

        self.assertEqual(request["schema_version"], 1)
        self.assertEqual(request["library_id"], 1)
        self.assertEqual(request["run_id"], run_dir.name)
        self.assertEqual(request["chunk_index"], 1)
        self.assertEqual(request["chunk_count"], 1)
        self.assertEqual(request["items"], [{
            "task_id": "paper-0001",
            "doi": "10.1000/0001",
            "title": "Example Paper 1",
            "authors": "A. Author",
            "year": "2025",
        }])
        self.assertRegex(request["payload_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("file", json.dumps(request))
        self.assertNotIn("reason", json.dumps(request))

    def test_unknown_request_field_and_duplicate_task_are_rejected(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_request, validate_bridge_request

        with tempfile.TemporaryDirectory() as tmp:
            request = build_bridge_request(
                self._run(Path(tmp)),
                library_id=1,
                job_id="11111111-1111-4111-8111-111111111111",
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            )
        request["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "^bridge_request_fields_invalid$"):
            validate_bridge_request(request)
        request.pop("unexpected")
        request["items"].append(dict(request["items"][0]))
        with self.assertRaisesRegex(ValueError, "^bridge_task_id_duplicate$"):
            validate_bridge_request(request)

    def test_101_fallback_rows_become_two_stable_chunk_requests(self) -> None:
        from paper_automation.zotero_bridge import build_bridge_requests

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run(Path(tmp), fallback_count=101)
            requests = build_bridge_requests(
                run_dir,
                library_id=1,
                job_ids=(
                    "11111111-1111-4111-8111-111111111111",
                    "22222222-2222-4222-8222-222222222222",
                ),
                now=datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            )

        self.assertEqual([len(value["items"]) for value in requests], [100, 1])
        self.assertEqual([value["chunk_index"] for value in requests], [1, 2])
        self.assertEqual([value["chunk_count"] for value in requests], [2, 2])
        self.assertEqual({value["run_id"] for value in requests}, {run_dir.name})
        self.assertEqual(len({value["collection_name"] for value in requests}), 1)

    def test_rows_job_ids_and_times_cannot_weaken_the_contract(self) -> None:
        from paper_automation.zotero_bridge import (
            _digest,
            build_bridge_request,
            build_bridge_requests,
            validate_bridge_request,
        )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = self._run(Path(tmp), fallback_count=101)
            with self.assertRaisesRegex(ValueError, "^bridge_request_rows_invalid$"):
                build_bridge_request(
                    run_dir, library_id=1, chunk_index=1, chunk_count=2,
                    rows=[{"task_id": "outside", "doi": "10.1/x", "title": "x", "authors": "x", "year": "2025"}],
                )
            with self.assertRaisesRegex(ValueError, "^bridge_job_id_duplicate$"):
                build_bridge_requests(
                    run_dir, library_id=1,
                    job_ids=("11111111-1111-4111-8111-111111111111",) * 2,
                )
            single_run = self._run(Path(tmp) / "single")
            request = build_bridge_request(single_run, library_id=1)
            request["expires_at"] = "2026-07-11T09:00:00Z"
            request["payload_sha256"] = _digest(request)
            with self.assertRaisesRegex(ValueError, "^bridge_request_time_invalid$"):
                validate_bridge_request(request)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the request tests and verify RED**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests -v
```

Expected: `ModuleNotFoundError: No module named 'paper_automation.zotero_bridge'`.

- [ ] **Step 3: Implement paths, dataclasses, canonical serialization, and validation**

Create `paper_automation/zotero_bridge.py` with these public definitions and complete validation boundaries:

```python
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

from paper_automation.batch_workflow import NORMALIZED_FIELDS, load_batch_state

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
```

When `build_bridge_request(..., rows=...)` is used internally by `build_bridge_requests()`, first obtain `_validated_fallback_rows(root)`, calculate the one-based slice `(chunk_index - 1) * MAX_ITEMS_PER_JOB : chunk_index * MAX_ITEMS_PER_JOB`, and require the supplied rows to equal that exact slice after normalizing the five request fields. Any mismatch raises `ValueError("bridge_request_rows_invalid")`; do not let a public optional argument introduce a non-fallback task. In `build_bridge_requests()`, reject duplicate supplied IDs with `ValueError("bridge_job_id_duplicate")` before constructing any request. In `validate_bridge_request()`, parse `created_at` and `expires_at` as canonical UTC `...Z` ISO-8601 timestamps and reject malformed or non-increasing timestamps with `ValueError("bridge_request_time_invalid")` before accepting the digest.

The fixture must persist `options: asdict(BatchOptions())` exactly as shown; do not weaken production state validation or replace it with an empty options dictionary.

- [ ] **Step 4: Run request tests and the existing state tests**

Run:

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests tests.test_batch_workflow.BatchFileTests tests.test_batch_workflow.BatchRunTests -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Append CHANGELOG and commit**

Record inputs, created files, exact test command, outputs, and that no real Zotero/Internet/package action occurred. Then run:

```powershell
git add paper_automation/zotero_bridge.py tests/test_zotero_bridge.py CHANGELOG.md
git commit -m "Add Zotero bridge request contract"
```

### Task 2: Add atomic batch publication and idempotency

**Files:**
- Modify: `paper_automation/zotero_bridge.py`
- Modify: `tests/test_zotero_bridge.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `BridgePaths`, `BridgeJob`, `BridgeBatch`, `build_bridge_requests()`, and `validate_bridge_request()` from Task 1.
- Produces: `queue_bridge_jobs()`; later tasks must consume the ordered `BridgeBatch.jobs` tuple rather than a single job.

- [ ] **Step 1: Add failing atomicity, chunk, and replay tests**

Append these tests to `ZoteroBridgeRequestTests`:

```python
    def test_queue_publishes_a_stable_two_chunk_manifest(self) -> None:
        from paper_automation.zotero_bridge import queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs", fallback_count=101)
            kwargs = {
                "library_id": 1,
                "bridge_root": root / "bridge",
                "job_ids": (
                    "11111111-1111-4111-8111-111111111111",
                    "22222222-2222-4222-8222-222222222222",
                ),
                "now": datetime(2026, 7, 11, 9, 5, tzinfo=timezone.utc),
            }
            first = queue_bridge_jobs(run_dir, **kwargs)
            second = queue_bridge_jobs(run_dir, **kwargs)
            manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
            requests = [json.loads(job.request_path.read_text(encoding="utf-8")) for job in first.jobs]

        self.assertEqual(first, second)
        self.assertEqual([len(value["items"]) for value in requests], [100, 1])
        self.assertEqual([job.chunk_index for job in first.jobs], [1, 2])
        self.assertEqual([job.chunk_count for job in first.jobs], [2, 2])
        self.assertEqual(manifest["jobs"][0]["task_ids"][0], "paper-0001")
        self.assertEqual(manifest["jobs"][1]["task_ids"], ["paper-0101"])
        self.assertEqual(len(list((root / "bridge" / "inbox").glob("*.json"))), 2)

    def test_changed_fallback_after_manifest_fails_closed(self) -> None:
        from paper_automation.zotero_bridge import queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            queue_bridge_jobs(run_dir, bridge_root=root / "bridge", library_id=1)
            fallback = run_dir / "working" / "zotero_fallback.csv"
            fallback.write_text(fallback.read_text(encoding="utf-8-sig").replace("Example Paper 1", "Changed"), encoding="utf-8-sig")
            with self.assertRaisesRegex(ValueError, "^bridge_batch_manifest_conflict$"):
                queue_bridge_jobs(run_dir, bridge_root=root / "bridge", library_id=1)
```

Also add a two-thread test that calls `queue_bridge_jobs()` for a 101-row run. It must prove one manifest, two identical request files, no overwrite, no `.tmp` residue, and no prompt-visible partial confirmation contract: each request has the same `chunk_count=2` and different `chunk_index` values.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests -v
```

Expected: import failures for `queue_bridge_jobs()` and manifest helpers.

- [ ] **Step 3: Implement exclusive manifest-first queue publication**

Add these exact data shapes and helper boundaries to `paper_automation/zotero_bridge.py`:

```python
MANIFEST_FIELDS = {
    "schema_version", "run_id", "library_id", "collection_name", "created_at", "expires_at",
    "jobs", "manifest_sha256",
}
MANIFEST_JOB_FIELDS = {"job_id", "payload_sha256", "chunk_index", "chunk_count", "task_ids"}


def _manifest_path(run_dir: Path) -> Path:
    return run_dir / "working" / "zotero_bridge_jobs.json"


def _request_filename(job_id: str) -> str:
    return f"{job_id}.json"


def _result_filename(job_id: str) -> str:
    return f"{job_id}.result.json"
```

`_write_json_atomic_exclusive(path, payload)` must write UTF-8 JSON to a same-directory `mkstemp()` file, `flush()` and `os.fsync()` it, then publish it with `os.link(temporary, path)`. It must remove only its temporary file in `finally`. Do not use `exists()+replace()`, a process-local lock, or a second non-exclusive write. The manifest has its own canonical SHA-256 over all fields except `manifest_sha256`; validate exact fields, job order, unique UUIDs, all chunk positions `1..chunk_count`, payload hash formats, and unique task IDs globally.

Implement the following sequence exactly:

```python
def queue_bridge_jobs(run_dir, *, library_id=1, bridge_root=None, job_ids=None, now=None) -> BridgeBatch:
    root = Path(run_dir).expanduser().resolve()
    record = _manifest_path(root)
    if record.is_file():
        manifest = validate_bridge_manifest(json.loads(record.read_text(encoding="utf-8")))
        requests = _rebuild_requests_from_manifest(root, library_id, manifest)
    else:
        requests = build_bridge_requests(root, library_id=library_id, job_ids=job_ids, now=now)
        manifest = build_bridge_manifest(requests)
        try:
            _write_json_atomic_exclusive(record, manifest)
        except FileExistsError:
            manifest = validate_bridge_manifest(json.loads(record.read_text(encoding="utf-8")))
            requests = _rebuild_requests_from_manifest(root, library_id, manifest)
    jobs = tuple(_publish_or_reuse_request(paths, root, request) for request in requests)
    return BridgeBatch(run_id=root.name, manifest_path=record, jobs=jobs)
```

`_rebuild_requests_from_manifest()` must call `build_bridge_requests(..., job_ids=manifest_ids, now=parse_iso(manifest["created_at"]), collection_name=manifest["collection_name"])` against the current fallback rows, then compare every request digest, collection name, chunk position, expiry, and ordered task ID list. Any difference raises `ValueError("bridge_batch_manifest_conflict")`. The manifest is written before individual inbox files so a crash can resume the same IDs. Individual files may become visible one at a time; `chunk_index/chunk_count` is the explicit plugin-side barrier that prevents early confirmation. `_publish_or_reuse_request()` must accept an already-existing inbox, processing, or archive request only when its validated payload digest is identical; otherwise raise `bridge_job_id_conflict`.

- [ ] **Step 4: Run focused tests and concurrent stress loop**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests -v
1..50 | ForEach-Object { ..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeRequestTests.test_queue_publishes_a_stable_two_chunk_manifest }
```

Expected: all runs pass, `zotero_bridge_jobs.json` is the only per-run record, and no `.tmp` files remain.

- [ ] **Step 5: Append CHANGELOG and commit**

```powershell
git add paper_automation/zotero_bridge.py tests/test_zotero_bridge.py CHANGELOG.md
git commit -m "Queue Zotero bridge batches atomically"
```

### Task 3: Validate plugin results and publish strict Zotero CSV

**Files:**
- Modify: `paper_automation/zotero_bridge.py`
- Modify: `paper_automation/batch_workflow.py:70-105`
- Modify: `tests/test_zotero_bridge.py`
- Modify: `tests/test_batch_workflow.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: ordered `BridgeBatch`, `ZOTERO_RESULT_FIELDS`, and `finalize_batch(run_dir, zotero_results)`.
- Produces: `validate_bridge_result()`, `publish_zotero_results_csv()`, and `consume_bridge_batch()`.

- [ ] **Step 1: Add failing result-schema, malicious-path handoff, and no-overwrite tests**

Add a helper that creates this exact result shape:

```python
def bridge_result(job, rows):
    return {
        "schema_version": 1,
        "job_id": job.job_id,
        "payload_sha256": job.payload_sha256,
        "plugin_version": "0.1.0",
        "zotero_version": "9.0.6",
        "started_at": "2026-07-11T09:06:00Z",
        "finished_at": "2026-07-11T09:07:00Z",
        "rows": rows,
    }
```

Test all of the following in `ZoteroBridgeResultTests`:

```python
class ZoteroBridgeResultTests(ZoteroBridgeRequestTests):
    def test_valid_one_job_result_publishes_exact_five_column_csv(self) -> None:
        from paper_automation.zotero_bridge import consume_bridge_batch, queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            bridge = queue_bridge_jobs(run_dir, library_id=1, bridge_root=root / "bridge")
            job = bridge.jobs[0]
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF-1.7\nfixture")
            job.result_path.write_text(json.dumps(bridge_result(job, [{
                "task_id": "paper-0001", "zotero_item_id": "304",
                "attachment_path": str(pdf.resolve()), "status": "existing_pdf", "reason": "",
            }])), encoding="utf-8")
            csv_path = consume_bridge_batch(bridge)
            with csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
                records = list(csv.reader(handle, strict=True))

        self.assertEqual(records[0], ["task_id", "zotero_item_id", "attachment_path", "status", "reason"])
        self.assertEqual(records[1][0:2], ["paper-0001", "304"])

    def test_missing_second_chunk_never_publishes_partial_csv(self) -> None:
        from paper_automation.zotero_bridge import consume_bridge_batch, queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs", fallback_count=101)
            bridge = queue_bridge_jobs(run_dir, library_id=1, bridge_root=root / "bridge")
            first, second = bridge.jobs
            first.result_path.write_text(json.dumps(bridge_result(first, [
                {"task_id": f"paper-{number:04d}", "zotero_item_id": "", "attachment_path": "", "status": "no_pdf", "reason": "fixture"}
                for number in range(1, 101)
            ])), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "^bridge_result_missing$"):
                consume_bridge_batch(bridge)
            self.assertFalse((run_dir / "working" / "zotero_results.csv").exists())
            second.result_path.write_text(json.dumps(bridge_result(second, [{
                "task_id": "paper-0101", "zotero_item_id": "", "attachment_path": "", "status": "no_pdf", "reason": "fixture",
            }])), encoding="utf-8")
            selected = consume_bridge_batch(bridge)

        self.assertEqual(len(selected.read_text(encoding="utf-8-sig").splitlines()), 102)

    def test_result_unknown_field_and_existing_canonical_fail_closed(self) -> None:
        from paper_automation.zotero_bridge import consume_bridge_batch, queue_bridge_jobs

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = self._run(root / "runs")
            canonical = run_dir / "working" / "zotero_results.csv"
            canonical.write_bytes(b"original")
            bridge = queue_bridge_jobs(run_dir, bridge_root=root / "bridge", library_id=1)
            job = bridge.jobs[0]
            result = bridge_result(job, [{
                "task_id": "paper-0001", "zotero_item_id": "", "attachment_path": "",
                "status": "no_pdf", "reason": "fixture",
            }])
            result["unexpected"] = True
            job.result_path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "^bridge_result_fields_invalid$"):
                consume_bridge_batch(bridge)
            self.assertEqual(canonical.read_bytes(), b"original")
```

- [ ] **Step 2: Run result tests and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeResultTests -v
```

Expected: missing result functions or unaccepted bridge statuses.

- [ ] **Step 3: Extend the existing whitelist and implement strict result conversion**

Add these statuses to `ZOTERO_FAILURE_STATUSES` in `paper_automation/batch_workflow.py`:

```python
    "user_cancelled",
    "job_expired",
    "job_id_conflict",
    "plugin_error",
```

Add to `paper_automation/zotero_bridge.py`:

```python
from paper_automation.batch_workflow import ZOTERO_INPUT_STATUSES, ZOTERO_RESULT_FIELDS

RESULT_FIELDS = {
    "schema_version", "job_id", "payload_sha256", "plugin_version", "zotero_version",
    "started_at", "finished_at", "rows",
}
RESULT_ROW_FIELDS = set(ZOTERO_RESULT_FIELDS)


def validate_bridge_result(result: object, job: BridgeJob, expected_ids: set[str]) -> dict:
    if not isinstance(result, dict) or set(result) != RESULT_FIELDS:
        raise ValueError("bridge_result_fields_invalid")
    if result["schema_version"] != BRIDGE_SCHEMA_VERSION:
        raise ValueError("bridge_schema_version_invalid")
    if result["job_id"] != job.job_id or result["payload_sha256"] != job.payload_sha256:
        raise ValueError("bridge_result_identity_invalid")
    rows = result["rows"]
    if not isinstance(rows, list) or len(rows) != len(expected_ids):
        raise ValueError("bridge_result_count_invalid")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != RESULT_ROW_FIELDS:
            raise ValueError("bridge_result_row_fields_invalid")
        if any(not isinstance(row[field], str) or len(row[field]) > MAX_TEXT_LENGTH for field in RESULT_ROW_FIELDS):
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


def _write_result_csv_exclusive(
    run_dir: Path,
    rows: list[dict[str, str]],
    now: datetime | None = None,
) -> Path:
    working = run_dir / "working"
    canonical = working / "zotero_results.csv"
    candidates = [canonical]
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    candidates.extend(working / f"zotero_results_retry_{stamp}{'' if n == 1 else '_' + str(n)}.csv" for n in range(1, 10000))
    for candidate in candidates:
        try:
            handle = candidate.open("x", newline="", encoding="utf-8-sig")
        except FileExistsError:
            continue
        try:
            with handle:
                writer = csv.writer(handle)
                writer.writerow(ZOTERO_RESULT_FIELDS)
                for row in rows:
                    writer.writerow([row[field] for field in ZOTERO_RESULT_FIELDS])
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            candidate.unlink(missing_ok=True)
            raise
        return candidate
    raise OSError("bridge_result_filename_exhausted")


def _validated_rows_for_job(job: BridgeJob) -> tuple[list[str], list[dict[str, str]]]:
    request = validate_bridge_request(json.loads(job.request_path.read_text(encoding="utf-8")))
    expected_ids = [item["task_id"] for item in request["items"]]
    if not job.result_path.is_file():
        raise ValueError("bridge_result_missing")
    result = validate_bridge_result(
        json.loads(job.result_path.read_text(encoding="utf-8")), job, set(expected_ids),
    )
    return expected_ids, result["rows"]


def consume_bridge_batch(bridge: BridgeBatch, *, now: datetime | None = None) -> Path:
    rows_by_task: dict[str, dict[str, str]] = {}
    ordered_ids: list[str] = []
    for job in bridge.jobs:
        expected_ids, rows = _validated_rows_for_job(job)
        ordered_ids.extend(expected_ids)
        for row in rows:
            if row["task_id"] in rows_by_task:
                raise ValueError("bridge_result_task_duplicate")
            rows_by_task[row["task_id"]] = row
    if len(set(ordered_ids)) != len(ordered_ids) or set(rows_by_task) != set(ordered_ids):
        raise ValueError("bridge_result_tasks_missing")
    ordered_rows = [rows_by_task[task_id] for task_id in ordered_ids]
    return _write_result_csv_exclusive(bridge.jobs[0].run_dir, ordered_rows, now=now)
```

Use the same exclusive file handle for header and rows, flush it before returning, and add a reader concurrency test that never accepts a partial CSV record. `consume_bridge_batch()` must validate every outbox result before opening any CSV file, and must write exactly one combined CSV only after every manifest job has a complete result. The existing finalizer performs an additional complete CSV validation before any batch state change.

- [ ] **Step 4: Run focused bridge, finalizer, and security tests**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge.ZoteroBridgeResultTests tests.test_batch_workflow.BatchFinalizeTests -v
```

Expected: all pass; malicious attachment paths may enter the five-column handoff but are rejected by `finalize_batch()` before copying, exactly as current finalizer tests require.

- [ ] **Step 5: Append CHANGELOG and commit**

```powershell
git add paper_automation/zotero_bridge.py paper_automation/batch_workflow.py tests/test_zotero_bridge.py tests/test_batch_workflow.py CHANGELOG.md
git commit -m "Validate Zotero bridge results"
```

### Task 4: Add resumable bridge orchestration and `paper_batch.py zotero`

**Files:**
- Modify: `paper_automation/zotero_bridge.py`
- Modify: `paper_batch.py:15-270`
- Modify: `tests/test_zotero_bridge.py`
- Modify: `tests/test_batch_workflow.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `queue_bridge_jobs()`, `consume_bridge_batch()`, and `finalize_batch()`.
- Produces: `BridgeRunResult`, `run_zotero_bridge()`, CLI syntax `paper_batch.py zotero --run-dir <path> [--library-id 1] [--wait-seconds N]`.

- [ ] **Step 1: Add failing orchestration and CLI tests**

Add tests covering these exact outcomes:

```python
def test_run_returns_waiting_without_requeue(self):
    run_dir = self._run(root / "runs", fallback_count=101)
    first = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
    second = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
    self.assertEqual(first.status, "awaiting_confirmation")
    self.assertEqual([job.job_id for job in second.bridge.jobs], [job.job_id for job in first.bridge.jobs])
    self.assertEqual(len(list((bridge_root / "inbox").glob("*.json"))), 2)

def test_run_consumes_result_and_finalizes_once(self):
    run_dir = self._run(root / "runs", fallback_count=101)
    queued = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=0)
    for job in queued.bridge.jobs:
        request = json.loads(job.request_path.read_text(encoding="utf-8"))
        job.result_path.write_text(json.dumps(bridge_result(job, [
            {"task_id": item["task_id"], "zotero_item_id": "", "attachment_path": "", "status": "no_pdf", "reason": "fixture"}
            for item in request["items"]
        ])), encoding="utf-8")
    with patch("paper_automation.zotero_bridge.finalize_batch") as finalize:
        outcome = run_zotero_bridge(run_dir, bridge_root=bridge_root, wait_seconds=1)
    self.assertEqual(outcome.status, "finalized")
    finalize.assert_called_once_with(run_dir.resolve(), outcome.zotero_results)
    self.assertEqual(len(outcome.bridge.jobs), 2)

def test_cli_waiting_returns_three_and_prints_one_action(self):
    with patch("paper_batch.run_zotero_bridge", return_value=waiting_outcome):
        code = main(["zotero", "--run-dir", str(run_dir), "--wait-seconds", "0"])
    self.assertEqual(code, 3)
    self.assertIn("请在 Zotero 中确认一次", stdout.getvalue())
    self.assertNotIn("resume", stdout.getvalue())
```

Also test: empty fallback creates no job and finalizes current reports; expired/cancelled/plugin error produces recoverable final report; an invalid result exits 2 without printing a traceback or result payload; `--wait-seconds` rejects negative values and values over 86400.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge tests.test_batch_workflow.BatchCliTests -v
```

Expected: missing `run_zotero_bridge`, parser command, or status output assertions fail.

- [ ] **Step 3: Implement resumable orchestration**

Add to `paper_automation/zotero_bridge.py`:

```python
import time
from paper_automation.batch_workflow import BatchRunResult, finalize_batch, write_final_reports


@dataclass(frozen=True)
class BridgeRunResult:
    status: str
    bridge: BridgeBatch | None
    zotero_results: Path | None
    batch_result: BatchRunResult | None


def run_zotero_bridge(
    run_dir: str | Path,
    *,
    library_id: int = 1,
    wait_seconds: int = 0,
    poll_seconds: float = 1.0,
    bridge_root: str | Path | None = None,
) -> BridgeRunResult:
    if not 0 <= wait_seconds <= 86400:
        raise ValueError("bridge_wait_seconds_invalid")
    root = Path(run_dir).expanduser().resolve()
    fallback = _fallback_rows(root)
    if not fallback:
        state = load_batch_state(root)
        from paper_automation.batch_workflow import _paths_from_run_dir, _result_from_state
        paths = _paths_from_run_dir(root)
        write_final_reports(paths, state["rows"])
        return BridgeRunResult("no_fallback", None, None, _result_from_state(paths, state))
    bridge = queue_bridge_jobs(root, library_id=library_id, bridge_root=bridge_root)
    deadline = time.monotonic() + wait_seconds
    while any(not job.result_path.is_file() for job in bridge.jobs):
        if time.monotonic() >= deadline:
            return BridgeRunResult("awaiting_confirmation", bridge, None, None)
        time.sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
    selected = consume_bridge_batch(bridge)
    batch = finalize_batch(root, selected)
    return BridgeRunResult("finalized", bridge, selected, batch)
```

Do not create or read the obsolete singular `zotero_bridge_job.json`; the atomically published `zotero_bridge_jobs.json` manifest is the only batch record. Do not leave imports of private `_paths_from_run_dir` or `_result_from_state`. Add public `paths_from_run_dir()` and `result_from_state()` wrappers in `batch_workflow.py`, test them, and import those public names.

- [ ] **Step 4: Add the CLI command and fixed messages**

In `paper_batch.py`, import `run_zotero_bridge`, add:

```python
    zotero = subparsers.add_parser("zotero", help="把项目失败项交给 Zotero 9 本地桥接")
    zotero.add_argument("--run-dir", required=True, help="已有批次目录")
    zotero.add_argument("--library-id", type=int, default=1, help="目标 Zotero 文库 ID（默认：1）")
    zotero.add_argument("--wait-seconds", type=int, default=0, help="等待 Zotero 结果的秒数（0-86400）")
```

Handle it before the existing summary path:

```python
        elif args.command == "zotero":
            bridge = run_zotero_bridge(
                args.run_dir,
                library_id=args.library_id,
                wait_seconds=args.wait_seconds,
            )
            if bridge.status == "awaiting_confirmation":
                print(f"桥接任务：{len(bridge.bridge.jobs)} 个子作业")
                print("请在 Zotero 中确认一次；确认后重新运行同一条命令即可继续。")
                print(f"批次目录：{Path(args.run_dir).expanduser().resolve()}")
                return 3
            if bridge.batch_result is None:
                raise RuntimeError("bridge_batch_result_missing")
            result = bridge.batch_result
```

Add safe `ERROR_HINTS` entries for all bridge validation codes. Unknown exceptions continue to hide payloads and paths containing secrets.

- [ ] **Step 5: Run focused and full project tests**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge tests.test_batch_workflow.BatchCliTests -v
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
..\..\.venv\Scripts\python.exe -m compileall paper_batch.py paper_automation
git diff --check
```

Expected: all tests pass, compileall exits 0, and diff check has no errors.

- [ ] **Step 6: Append CHANGELOG and commit**

```powershell
git add paper_batch.py paper_automation/zotero_bridge.py paper_automation/batch_workflow.py tests/test_zotero_bridge.py tests/test_batch_workflow.py CHANGELOG.md
git commit -m "Add resumable Zotero bridge command"
```

### Task 5: Project-side review gate

**Files:**
- Modify only files needed for review fixes.
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: all project-side interfaces from Tasks 1-4.
- Produces: a reviewed, independently testable project-side bridge ready for the plugin plan.

- [ ] **Step 1: Review against the design contract**

Verify with code evidence that: only fallback rows are queued; request/result fields are exact; more than 100 fallback rows split in stable order; every run has one manifest and shared collection name; `chunk_index/chunk_count` prevent prompt-visible partial batches; every subjob replay is idempotent; the combined CSV is absent until every result validates; attachment paths are not trusted; existing files are never overwritten; waiting does not rerun project stages; secrets are not printed.

- [ ] **Step 2: Run source safety scans**

```powershell
rg -n "subprocess|os\.system|eval\(|exec\(|http://|https://|sqlite|Sci-Hub|scihub|Anna's Archive|LibGen" paper_automation/zotero_bridge.py paper_batch.py
rg -n "zotero_fallback|payload_sha256|open\(\"x\"|replace|fsync|ZOTERO_RESULT_FIELDS" paper_automation/zotero_bridge.py
```

Expected: the first scan has no unsafe bridge implementation matches; the second shows every required boundary.

- [ ] **Step 3: Run the complete regression suite twice**

```powershell
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
git status --short
```

Expected: both runs pass; status contains only intentional review fixes and the appended changelog before commit.

- [ ] **Step 4: Append review evidence and commit fixes**

```powershell
git add paper_batch.py paper_automation/zotero_bridge.py paper_automation/batch_workflow.py tests/test_zotero_bridge.py tests/test_batch_workflow.py CHANGELOG.md
git commit -m "Harden project Zotero bridge"
```

If review finds no code changes, append the evidence to `CHANGELOG.md` and commit only that file with the same message.
