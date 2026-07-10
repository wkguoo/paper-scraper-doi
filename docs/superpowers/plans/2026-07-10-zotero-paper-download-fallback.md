# Zotero Paper Download Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable `$paper-download` workflow that accepts one literature list, runs the project's authorized/OA download paths, sends only unresolved papers to Zotero, and delivers all valid PDFs in one directory.

**Architecture:** `paper_batch.py` is the project CLI with `start`, `resume`, and `finalize` commands. `paper_automation.batch_workflow` owns state, recovery, PDF validation, deduplication, and final reports; `paper_automation.batch_stages` adapts the existing OA, ScienceDirect, and non-Elsevier workflows into one normalized result type. The `paper-download` Codex Skill owns Zotero MCP calls and exchanges results with the project through CSV files.

**Tech Stack:** Python 3, `pathlib`, `csv`, `json`, `hashlib`, `shutil`, `dataclasses`, `unittest`, `openpyxl`, existing project download modules, Zotero MCP tools.

## Global Constraints

- Default to Simplified Chinese user-facing text and beginner-friendly run instructions.
- Support pasted text and TXT, Markdown, CSV, XLSX, and XLSM inputs.
- Never modify, move, delete, or overwrite original input files or Zotero attachments.
- Save generated work under a new timestamped output directory.
- Use only public OA candidates, publisher sites, and the user's existing institutional access.
- Do not call Sci-Hub, Anna's Archive, LibGen, or any other shadow library.
- Never log Cookie values, passwords, or institutional session contents.
- A login/CAPTCHA condition may pause once and retry once; a second failure is recorded and skipped.
- Do not automatically package the Windows application.
- Preserve unrelated existing working-tree changes and append every project modification to `CHANGELOG.md`.

---

### Task 1: Remove shadow-library fallback from every active workflow

**Files:**
- Delete: `paper_automation/scihub_fallback.py`
- Modify: `paper_automation/workflow.py`
- Modify: `sd_institutional_skill.py`
- Modify: `doi_batch_utils.py`
- Modify: `paper_skill.py`
- Test: `tests/test_paper_automation.py`
- Test: `tests/test_sd_institutional_skill.py`

**Interfaces:**
- Consumes: existing `run_workflow(input_text, output_dir, email, dry_run, overwrite, limit)` and `sd_institutional_skill.main(argv)` behavior.
- Produces: failures remain explicit `failed` records for later authorized/Zotero stages; no shadow-library function is importable or callable.

- [ ] **Step 1: Write failing safety tests**

Add these tests:

```python
class WorkflowSafetyTests(unittest.TestCase):
    def test_oa_failure_stays_failed_for_later_authorized_fallback(self) -> None:
        import csv
        from unittest.mock import patch
        from paper_automation.models import MetadataResult
        from paper_automation.workflow import run_workflow

        metadata = MetadataResult(
            source_index=1,
            query_title="Closed paper",
            doi="10.1000/closed",
            title="Closed paper",
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "paper_automation.workflow.MetadataResolver.resolve_one",
            return_value=metadata,
        ):
            result = run_workflow("10.1000/closed", tmp)
            with Path(result.manifest_csv).open("r", encoding="utf-8-sig") as handle:
                row = next(csv.DictReader(handle))

        self.assertEqual(row["download_status"], "failed")
        self.assertEqual(row["reason"], "no_legal_open_pdf")

    def test_shadow_library_module_is_not_part_of_project(self) -> None:
        self.assertFalse((PROJECT_ROOT / "paper_automation" / "scihub_fallback.py").exists())
```

Add this guard to `tests/test_sd_institutional_skill.py`:

```python
def test_sciencedirect_main_has_no_shadow_library_fallback(self) -> None:
    import inspect
    import sd_institutional_skill

    source = inspect.getsource(sd_institutional_skill.main)
    self.assertNotIn("apply_auto_fallback", source)
    self.assertNotIn("scihub_downloaded", source)
```

- [ ] **Step 2: Run tests and verify the safety test fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_paper_automation.WorkflowSafetyTests tests.test_sd_institutional_skill -v
```

Expected: failure because `paper_automation/scihub_fallback.py` and active fallback calls still exist.

- [ ] **Step 3: Remove all active fallback code**

Delete `paper_automation/scihub_fallback.py`. Remove the `apply_auto_fallback` import and fallback block from `sd_institutional_skill.py`. Remove the fallback block from `paper_automation/workflow.py`. Remove the complete function named `apply_auto_fallback` from `doi_batch_utils.py`, including its import of `paper_automation.scihub_fallback`.

Change the accepted success status check in `doi_batch_utils.py` from:

```python
{"success", "scihub_downloaded"}
```

to:

```python
{"success"}
```

Set `paper_skill.py`'s parser description to:

```python
description="Identify paper text, resolve metadata, and download publicly available open-access PDF candidates.",
```

- [ ] **Step 4: Run targeted and source-scan tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_paper_automation.WorkflowSafetyTests tests.test_sd_institutional_skill -v
rg -n "Sci-Hub|scihub|Anna's Archive|annas_archive|apply_auto_fallback" paper_automation sd_institutional_skill.py paper_skill.py doi_batch_utils.py
```

Expected: tests pass; `rg` returns no matches in active project code.

- [ ] **Step 5: Commit only files owned by this task when safe**

```powershell
git add paper_automation/workflow.py paper_automation/scihub_fallback.py sd_institutional_skill.py doi_batch_utils.py tests/test_paper_automation.py tests/test_sd_institutional_skill.py
git commit -m "Remove shadow library download fallback"
```

If a listed file already contains unrelated user edits, do not stage the whole file; leave it uncommitted and record that in `CHANGELOG.md`.

---

### Task 2: Add batch paths, durable state, PDF validation, and safe copying

**Files:**
- Create: `paper_automation/batch_workflow.py`
- Create: `tests/test_batch_workflow.py`

**Interfaces:**
- Produces: `BatchPaths`, `create_batch_paths()`, `load_batch_state()`, `save_batch_state()`, `is_valid_pdf()`, `copy_pdf_safely()`.
- Consumed by: Tasks 3–6.

- [ ] **Step 1: Write failing unit tests**

Create `tests/test_batch_workflow.py` with:

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class BatchFileTests(unittest.TestCase):
    def test_paths_and_state_are_created_under_new_run_directory(self) -> None:
        from paper_automation.batch_workflow import create_batch_paths, load_batch_state, save_batch_state

        with tempfile.TemporaryDirectory() as tmp:
            paths = create_batch_paths(Path(tmp), now=datetime(2026, 7, 10, 17, 0, 0))
            save_batch_state(paths, {"version": 1, "rows": []})

            self.assertEqual(paths.root.name, "paper_batch_20260710_170000")
            self.assertTrue(paths.pdfs.is_dir())
            self.assertTrue(paths.reports.is_dir())
            self.assertEqual(load_batch_state(paths.root)["version"], 1)

    def test_pdf_validation_and_copy_are_non_destructive_and_deduplicated(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely, is_valid_pdf

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.pdf"
            source.write_bytes(b"%PDF-1.7\nvalid payload")
            destination = root / "pdfs"

            first = copy_pdf_safely(source, destination, "paper.pdf")
            second = copy_pdf_safely(source, destination, "paper.pdf")

            self.assertTrue(is_valid_pdf(first))
            self.assertEqual(first, second)
            self.assertTrue(source.exists())
            self.assertEqual(len(list(destination.glob("*.pdf"))), 1)

    def test_non_pdf_is_rejected(self) -> None:
        from paper_automation.batch_workflow import copy_pdf_safely

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "login.pdf"
            source.write_text("<html>login</html>", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not_pdf_response"):
                copy_pdf_safely(source, Path(tmp) / "pdfs", "paper.pdf")
```

- [ ] **Step 2: Run tests and verify import failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFileTests -v
```

Expected: `ModuleNotFoundError` or missing interface failures.

- [ ] **Step 3: Implement the file/state primitives**

Start `paper_automation/batch_workflow.py` with:

```python
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class BatchPaths:
    root: Path
    pdfs: Path
    reports: Path
    working: Path
    state: Path
    normalized_input: Path
    manual_retry: Path
    zotero_fallback: Path
    zotero_results: Path


def create_batch_paths(output_root: str | Path, run_name: str | None = None, now: datetime | None = None) -> BatchPaths:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    root = Path(output_root).expanduser().resolve() / (run_name or f"paper_batch_{stamp}")
    pdfs, reports, working = root / "pdfs", root / "reports", root / "working"
    for path in (root, pdfs, reports, working):
        path.mkdir(parents=True, exist_ok=True)
    return BatchPaths(
        root=root,
        pdfs=pdfs,
        reports=reports,
        working=working,
        state=working / "batch_state.json",
        normalized_input=working / "normalized_input.csv",
        manual_retry=working / "manual_retry.csv",
        zotero_fallback=working / "zotero_fallback.csv",
        zotero_results=working / "zotero_results.csv",
    )


def save_batch_state(paths: BatchPaths, payload: dict) -> Path:
    temporary = paths.state.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(paths.state)
    return paths.state


def load_batch_state(run_dir: str | Path) -> dict:
    path = Path(run_dir) / "working" / "batch_state.json"
    return json.loads(path.read_text(encoding="utf-8"))


def is_valid_pdf(path: str | Path, minimum_size: int = 12) -> bool:
    target = Path(path)
    if not target.is_file() or target.stat().st_size < minimum_size:
        return False
    with target.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_pdf_safely(source: str | Path, destination_dir: str | Path, filename: str) -> Path:
    source_path = Path(source).expanduser().resolve()
    if not is_valid_pdf(source_path):
        raise ValueError("not_pdf_response")
    destination = Path(destination_dir)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / filename
    source_hash = _sha256(source_path)
    if target.exists():
        if is_valid_pdf(target) and _sha256(target) == source_hash:
            return target
        target = target.with_name(f"{target.stem}_{source_hash[:8]}{target.suffix}")
    shutil.copy2(source_path, target)
    return target
```

- [ ] **Step 4: Run file/state tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFileTests -v
```

Expected: all three tests pass.

- [ ] **Step 5: Commit**

```powershell
git add paper_automation/batch_workflow.py tests/test_batch_workflow.py
git commit -m "Add resumable paper batch state"
```

---

### Task 3: Normalize the three project download stages

**Files:**
- Create: `paper_automation/batch_stages.py`
- Modify: `tests/test_batch_workflow.py`

**Interfaces:**
- Produces: `BatchOptions`, `StageResult`, `run_oa_stage()`, `run_sciencedirect_stage()`, `run_non_elsevier_stage()`.
- Consumed by: `start_batch()` and `resume_batch()` in Task 4.

- [ ] **Step 1: Add failing adapter tests**

Append:

```python
class BatchStageTests(unittest.TestCase):
    def test_stage_result_marks_only_valid_pdf_as_success(self) -> None:
        from paper_automation.batch_stages import StageResult

        result = StageResult(
            task_id="paper-0001",
            doi="10.1016/example",
            title="Example",
            status="downloaded",
            file="paper.pdf",
            reason="",
            source="oa",
        )
        self.assertEqual(result.source, "oa")

    def test_route_splits_sciencedirect_from_other_publishers(self) -> None:
        from paper_automation.batch_stages import split_institutional_rows

        rows = [
            {"task_id": "paper-0001", "doi": "10.1016/j.actamat.2024.1"},
            {"task_id": "paper-0002", "doi": "10.1038/s41467-020-1"},
            {"task_id": "paper-0003", "doi": ""},
        ]
        science_direct, other = split_institutional_rows(rows)
        self.assertEqual([row["task_id"] for row in science_direct], ["paper-0001"])
        self.assertEqual([row["task_id"] for row in other], ["paper-0002", "paper-0003"])

    def test_manual_retry_statuses_are_explicit(self) -> None:
        from paper_automation.batch_stages import needs_manual_retry

        self.assertTrue(needs_manual_retry("auth_required", ""))
        self.assertTrue(needs_manual_retry("failed", "captcha_required"))
        self.assertFalse(needs_manual_retry("unsupported_publisher", ""))
```

- [ ] **Step 2: Run tests and verify missing module failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchStageTests -v
```

- [ ] **Step 3: Implement normalized adapter types and routing**

Create `paper_automation/batch_stages.py` with these public definitions:

```python
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BatchOptions:
    email: str = ""
    cookies: str = ""
    browser_exe: str = ""
    login_wait_seconds: int = 0
    debug_port: int = 9333
    throttle_seconds: float = 1.0


@dataclass(frozen=True)
class StageResult:
    task_id: str
    doi: str
    title: str
    status: str
    file: str
    reason: str
    source: str


def split_institutional_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    science_direct, other = [], []
    for row in rows:
        target = science_direct if str(row.get("doi", "")).lower().startswith("10.1016/") else other
        target.append(row)
    return science_direct, other


def needs_manual_retry(status: str, reason: str) -> bool:
    text = f"{status} {reason}".lower()
    return any(token in text for token in ("auth_required", "captcha", "turnstile", "login_required"))


def write_stage_input(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["task_id", "doi", "title", "authors", "journal", "year"])
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in writer.fieldnames})
    return path
```

Then add `run_oa_stage()`, `run_sciencedirect_stage()`, and `run_non_elsevier_stage()` as thin adapters. They must:

- call `paper_automation.workflow.run_workflow()` for OA;
- call `sd_institutional_skill.main()` with a fixed `--run-name sciencedirect`, `--no-download-supplements`, and optional browser/cookie flags;
- call `paper_automation.institutional.run_institutional_workflow()` for non-Elsevier rows;
- read each existing report and return one `StageResult` per input row;
- map only a valid local PDF to `status="downloaded"`; preserve every other status/reason.

Use these exact public signatures: `run_oa_stage(rows: list[dict], output_dir: Path, options: BatchOptions) -> list[StageResult]`, `run_sciencedirect_stage(input_path: Path, output_dir: Path, options: BatchOptions) -> list[StageResult]`, and `run_non_elsevier_stage(input_path: Path, output_dir: Path, options: BatchOptions) -> list[StageResult]`.

- [ ] **Step 4: Add report-mapping tests and make them pass**

Add this concrete ScienceDirect adapter test; add an equivalent non-Elsevier test using `institutional_pdf_download_report.csv` and `status="unsupported_publisher"`:

```python
def test_sciencedirect_adapter_maps_success_and_auth_failure(self) -> None:
    import csv
    from unittest.mock import patch
    from paper_automation.batch_stages import BatchOptions, run_sciencedirect_stage, write_stage_input

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        valid_pdf = root / "download.pdf"
        valid_pdf.write_bytes(b"%PDF-1.7\nfixture")
        input_path = write_stage_input([
            {"task_id": "paper-0001", "doi": "10.1016/a", "title": "A"},
            {"task_id": "paper-0002", "doi": "10.1016/b", "title": "B"},
        ], root / "input.csv")

        def fake_sd_main(argv: list[str]) -> int:
            out = Path(argv[argv.index("--out") + 1]) / "sciencedirect"
            out.mkdir(parents=True, exist_ok=True)
            with (out / "pdf_download_report.csv").open("w", newline="", encoding="utf-8-sig") as handle:
                fields = [
                    "doi", "pii", "title", "status", "file", "reason",
                    "manual_pdf_url", "manual_status", "manual_reason",
                ]
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"doi": "10.1016/a", "title": "A", "status": "success", "file": str(valid_pdf)})
                writer.writerow({"doi": "10.1016/b", "title": "B", "status": "failed", "reason": "auth_required"})
            return 0

        with patch("paper_automation.batch_stages.sd_main", side_effect=fake_sd_main):
            results = run_sciencedirect_stage(input_path, root, BatchOptions())

        self.assertEqual([row.task_id for row in results], ["paper-0001", "paper-0002"])
        self.assertEqual(results[0].status, "downloaded")
        self.assertEqual(results[1].reason, "auth_required")
```

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchStageTests -v
```

Expected: all stage tests pass without network access.

- [ ] **Step 5: Commit**

```powershell
git add paper_automation/batch_stages.py tests/test_batch_workflow.py
git commit -m "Add project download stage adapters"
```

---

### Task 4: Implement `start` and one-time `resume`

**Files:**
- Modify: `paper_automation/batch_workflow.py`
- Modify: `tests/test_batch_workflow.py`

**Interfaces:**
- Produces: `BatchRunResult`, `start_batch()`, `resume_batch()`.
- Consumes: Task 2 state helpers and Task 3 stage adapters.

Define the result type before implementing the workflow:

```python
@dataclass(frozen=True)
class BatchRunResult:
    paths: BatchPaths
    total_count: int
    success_count: int
    failed_count: int
    manual_retry_count: int
    zotero_fallback_count: int
```

- [ ] **Step 1: Write failing workflow tests with a fake gateway**

Add:

```python
class FakeGateway:
    def __init__(self) -> None:
        self.retry_calls = 0

    def run_initial(self, rows, paths, options):
        return [
            {**rows[0], "status": "oa_downloaded", "source": "oa", "file": rows[0]["fixture_pdf"], "reason": ""},
            {**rows[1], "status": "captcha_required", "source": "institutional", "file": "", "reason": "captcha_required"},
            {**rows[2], "status": "no_open_pdf", "source": "oa", "file": "", "reason": "no_open_pdf"},
        ]

    def run_retry(self, rows, paths, options):
        self.retry_calls += 1
        return [{**row, "status": "no_entitlement", "reason": "retry_exhausted"} for row in rows]


class BatchRunTests(unittest.TestCase):
    def test_start_writes_only_manual_rows_to_retry_and_other_failures_to_zotero(self) -> None:
        import csv
        from paper_automation.batch_workflow import start_batch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_pdf = root / "fixture.pdf"
            valid_pdf.write_bytes(b"%PDF-1.7\nfixture")
            normalized = [
                {"task_id": "paper-0001", "doi": "10.1000/a", "title": "A", "fixture_pdf": str(valid_pdf)},
                {"task_id": "paper-0002", "doi": "10.1000/b", "title": "B", "fixture_pdf": ""},
                {"task_id": "paper-0003", "doi": "10.1000/c", "title": "C", "fixture_pdf": ""},
            ]
            result = start_batch(
                input_text="fixture",
                input_path=None,
                output_root=root,
                gateway=FakeGateway(),
                normalizer=lambda **_kwargs: normalized,
                now=datetime(2026, 7, 10, 17, 0, 0),
            )
            with result.paths.manual_retry.open("r", encoding="utf-8-sig") as handle:
                retry_rows = list(csv.DictReader(handle))
            with result.paths.zotero_fallback.open("r", encoding="utf-8-sig") as handle:
                fallback_rows = list(csv.DictReader(handle))

            self.assertEqual(len(list(result.paths.pdfs.glob("*.pdf"))), 1)
            self.assertEqual([row["task_id"] for row in retry_rows], ["paper-0002"])
            self.assertEqual([row["task_id"] for row in fallback_rows], ["paper-0003"])

    def test_resume_runs_manual_retry_only_once(self) -> None:
        from paper_automation.batch_workflow import load_batch_state, resume_batch, start_batch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid_pdf = root / "fixture.pdf"
            valid_pdf.write_bytes(b"%PDF-1.7\nfixture")
            normalized = [
                {"task_id": "paper-0001", "doi": "10.1000/a", "title": "A", "fixture_pdf": str(valid_pdf)},
                {"task_id": "paper-0002", "doi": "10.1000/b", "title": "B", "fixture_pdf": ""},
                {"task_id": "paper-0003", "doi": "10.1000/c", "title": "C", "fixture_pdf": ""},
            ]
            gateway = FakeGateway()
            started = start_batch(
                input_text="fixture",
                input_path=None,
                output_root=root,
                gateway=gateway,
                normalizer=lambda **_kwargs: normalized,
            )
            resume_batch(started.paths.root, gateway=gateway)
            resume_batch(started.paths.root, gateway=gateway)

            self.assertEqual(gateway.retry_calls, 1)
            self.assertTrue(load_batch_state(started.paths.root)["manual_retry_used"])

    def test_normalizer_supports_markdown_csv_and_xlsx(self) -> None:
        import csv
        from openpyxl import Workbook
        from paper_automation.batch_workflow import create_batch_paths, normalize_input
        from paper_automation.batch_stages import BatchOptions

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "papers.md"
            markdown.write_text("- DOI: 10.1000/markdown\n", encoding="utf-8")
            csv_path = root / "papers.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["doi", "title"])
                writer.writeheader()
                writer.writerow({"doi": "10.1000/csv", "title": "CSV paper"})
            xlsx_path = root / "papers.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["doi", "title"])
            sheet.append(["10.1000/xlsx", "XLSX paper"])
            workbook.save(xlsx_path)

            for index, input_path in enumerate((markdown, csv_path, xlsx_path), start=1):
                paths = create_batch_paths(root, run_name=f"run-{index}")
                rows = normalize_input(
                    input_text=None,
                    input_path=input_path,
                    paths=paths,
                    options=BatchOptions(),
                )
                self.assertEqual(len(rows), 1)
                self.assertTrue(rows[0]["doi"].startswith("10.1000/"))
```

- [ ] **Step 2: Run tests and verify missing workflow functions**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchRunTests -v
```

- [ ] **Step 3: Implement normalized records and `start_batch()`**

Use `sd_institutional_skill.build_intake()` to support pasted text and all configured file types, then write these fields to `normalized_input.csv`:

```python
NORMALIZED_FIELDS = [
    "task_id", "source_index", "input_doi", "input_title", "doi", "title",
    "authors", "journal", "year", "publisher", "status", "source", "file", "reason",
]
```

Assign deterministic IDs as `paper-0001`, `paper-0002`, and so on after deduplication. The state payload must use:

```python
{
    "version": 1,
    "run_dir": str(paths.root),
    "manual_retry_used": False,
    "rows": rows,
}
```

`normalize_input()` must call `build_intake(resolve_metadata=True, resolve_title_only_files=True, min_confidence=0.65)` and copy the approved unique rows into `normalized_input.csv`. Unresolved title-only rows remain `metadata_uncertain`; the function must not invent a DOI.

`DefaultStageGateway.run_initial(rows, paths, options)` must run OA first, then split only unresolved rows with `split_institutional_rows()`, then run ScienceDirect and non-Elsevier adapters. `run_retry(rows, paths, options)` must skip OA and process only the supplied authentication/CAPTCHA rows. `_merge_stage_rows()` matches strictly by `task_id`; `_write_pending_files()` writes authentication/CAPTCHA rows to `manual_retry.csv` before retry and writes every other non-success row to `zotero_fallback.csv`.

Implement:

```python
def start_batch(
    *,
    input_text: str | None,
    input_path: str | Path | None,
    output_root: str | Path,
    run_name: str | None = None,
    options: BatchOptions | None = None,
    gateway=None,
    normalizer=None,
    now: datetime | None = None,
) -> BatchRunResult:
    if (input_text is None) == (input_path is None):
        raise ValueError("exactly_one_input_required")
    selected_options = options or BatchOptions()
    paths = create_batch_paths(output_root, run_name=run_name, now=now)
    normalize = normalizer or normalize_input
    rows = normalize(
        input_text=input_text,
        input_path=input_path,
        paths=paths,
        options=selected_options,
    )
    state = {"version": 1, "run_dir": str(paths.root), "manual_retry_used": False, "rows": rows}
    save_batch_state(paths, state)
    runner = gateway or DefaultStageGateway()
    updates = runner.run_initial(rows, paths, selected_options)
    state["rows"] = _merge_stage_rows(rows, updates, paths)
    save_batch_state(paths, state)
    _write_pending_files(paths, state["rows"])
    write_final_reports(paths, state["rows"])
    return _result_from_state(paths, state)
```

Rules:

- exactly one of `input_text` and `input_path` is required;
- copy every successful stage PDF with `copy_pdf_safely()`;
- write authentication/CAPTCHA rows to `manual_retry.csv`;
- write every other unresolved row to `zotero_fallback.csv`;
- call `save_batch_state()` after every row transition.

- [ ] **Step 4: Implement `resume_batch()` with a permanent retry guard**

```python
def resume_batch(run_dir: str | Path, *, gateway=None) -> BatchRunResult:
    paths = _paths_from_run_dir(run_dir)
    state = load_batch_state(run_dir)
    if state.get("manual_retry_used"):
        return _result_from_state(paths, state)
    state["manual_retry_used"] = True
    save_batch_state(paths, state)
    retry_ids = {row["task_id"] for row in _read_csv_rows(paths.manual_retry)}
    retry_rows = [row for row in state["rows"] if row["task_id"] in retry_ids]
    runner = gateway or DefaultStageGateway()
    updates = runner.run_retry(retry_rows, paths, BatchOptions())
    state["rows"] = _merge_stage_rows(state["rows"], updates, paths)
    save_batch_state(paths, state)
    _write_pending_files(paths, state["rows"], manual_retry_used=True)
    write_final_reports(paths, state["rows"])
    return _result_from_state(paths, state)
```

- [ ] **Step 5: Run workflow tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchRunTests -v
```

Expected: start/resume tests pass and no network is used.

- [ ] **Step 6: Commit**

```powershell
git add paper_automation/batch_workflow.py tests/test_batch_workflow.py
git commit -m "Add resumable project-first batch workflow"
```

---

### Task 5: Reconcile Zotero results and create final reports

**Files:**
- Modify: `paper_automation/batch_workflow.py`
- Modify: `tests/test_batch_workflow.py`

**Interfaces:**
- Produces: `ZOTERO_RESULT_FIELDS`, `finalize_batch()`, `write_final_reports()`.
- Consumes: `working/zotero_results.csv` with `task_id`, `zotero_item_id`, `attachment_path`, `status`, `reason`.

- [ ] **Step 1: Write failing finalize tests**

Add tests that create:

```python
zotero_rows = [
    {
        "task_id": "paper-0002",
        "zotero_item_id": "42",
        "attachment_path": str(valid_pdf),
        "status": "existing_pdf",
        "reason": "",
    },
    {
        "task_id": "paper-0003",
        "zotero_item_id": "43",
        "attachment_path": str(html_file),
        "status": "downloaded",
        "reason": "",
    },
]
```

Assertions:

```python
self.assertEqual(rows_by_id["paper-0002"]["status"], "zotero_existing_pdf")
self.assertEqual(rows_by_id["paper-0003"]["status"], "not_pdf_response")
self.assertTrue((run_dir / "reports" / "final_manifest.csv").exists())
self.assertTrue((run_dir / "reports" / "final_manifest.xlsx").exists())
self.assertTrue((run_dir / "reports" / "failed.csv").exists())
self.assertTrue((run_dir / "reports" / "run_summary.txt").exists())
self.assertTrue(valid_pdf.exists())
```

- [ ] **Step 2: Run and verify missing finalize behavior**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFinalizeTests -v
```

- [ ] **Step 3: Implement strict Zotero CSV ingestion**

Define:

```python
ZOTERO_RESULT_FIELDS = ["task_id", "zotero_item_id", "attachment_path", "status", "reason"]
ZOTERO_SUCCESS = {"existing_pdf": "zotero_existing_pdf", "downloaded": "zotero_downloaded"}
```

Implement:

```python
def finalize_batch(run_dir: str | Path, zotero_results: str | Path) -> BatchRunResult:
    paths = _paths_from_run_dir(run_dir)
    state = load_batch_state(run_dir)
    results = _read_csv_rows(Path(zotero_results), required_fields=ZOTERO_RESULT_FIELDS)
    by_task = {row["task_id"]: row for row in results}
    for row in state["rows"]:
        result = by_task.get(row["task_id"])
        if not result:
            continue
        if result["status"] in ZOTERO_SUCCESS:
            try:
                name = _filename_for_batch_row(row)
                target = copy_pdf_safely(result["attachment_path"], paths.pdfs, name)
            except (OSError, ValueError) as exc:
                row.update(status="not_pdf_response", source="zotero", file="", reason=str(exc))
            else:
                row.update(
                    status=ZOTERO_SUCCESS[result["status"]],
                    source="zotero",
                    file=str(target),
                    reason="",
                    zotero_item_id=result["zotero_item_id"],
                )
        else:
            row.update(status=result["status"], source="zotero", reason=result["reason"])
        save_batch_state(paths, state)
    write_final_reports(paths, state["rows"])
    return _result_from_state(paths.root, state)
```

Use `paper_automation.file_manager.make_pdf_filename()` for `_filename_for_batch_row()`.

- [ ] **Step 4: Implement CSV, XLSX, failed, and summary writers**

`final_manifest.csv` and `final_manifest.xlsx` must contain the same ordered columns. `failed.csv` contains all rows whose status is not one of:

```python
SUCCESS_STATUSES = {"oa_downloaded", "institutional_downloaded", "zotero_existing_pdf", "zotero_downloaded"}
```

`run_summary.txt` must include input count, success count, failure count, final PDF directory, each failure status count, and one line per failed task containing `task_id`, status, and reason. Use `openpyxl.Workbook(write_only=True)` for XLSX.

- [ ] **Step 5: Run finalize tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFinalizeTests -v
```

- [ ] **Step 6: Commit**

```powershell
git add paper_automation/batch_workflow.py tests/test_batch_workflow.py
git commit -m "Add Zotero result reconciliation"
```

---

### Task 6: Add the beginner-friendly `paper_batch.py` CLI

**Files:**
- Create: `paper_batch.py`
- Modify: `tests/test_batch_workflow.py`

**Interfaces:**
- Produces commands: `paper_batch.py start`, `paper_batch.py resume`, `paper_batch.py finalize`.
- Consumes Task 4 and Task 5 workflow functions.

- [ ] **Step 1: Write failing CLI tests**

Add tests that patch the workflow functions and call:

```python
exit_code = main(["start", "--text", "10.1000/example", "--out", str(root)])
self.assertEqual(exit_code, 0)

exit_code = main(["resume", "--run-dir", str(run_dir)])
self.assertEqual(exit_code, 0)

exit_code = main([
    "finalize", "--run-dir", str(run_dir), "--zotero-results", str(results_csv)
])
self.assertEqual(exit_code, 0)
```

Also assert `start` rejects using both `--text` and `--input`.

- [ ] **Step 2: Run and verify CLI import failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchCliTests -v
```

- [ ] **Step 3: Implement complete CLI parsing**

Create `paper_batch.py` with:

```python
from __future__ import annotations

import argparse
import sys

from paper_automation.batch_stages import BatchOptions
from paper_automation.batch_workflow import finalize_batch, resume_batch, start_batch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="项目优先、Zotero 失败回退的批量 PDF 工作流")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="创建批次并运行项目下载阶段")
    source = start.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="TXT/Markdown/CSV/XLSX/XLSM 文献清单")
    source.add_argument("--text", help="直接粘贴的文献清单")
    start.add_argument("--out", default="results")
    start.add_argument("--run-name")
    start.add_argument("--email", default="")
    start.add_argument("--cookies", default="")
    start.add_argument("--browser-exe", default="")
    start.add_argument("--login-wait-seconds", type=int, default=0)
    start.add_argument("--debug-port", type=int, default=9333)
    start.add_argument("--throttle-seconds", type=float, default=1.0)

    resume = subparsers.add_parser("resume", help="只重试一次登录或验证码失败项")
    resume.add_argument("--run-dir", required=True)

    finalize = subparsers.add_parser("finalize", help="归并 Zotero 附件并生成最终报告")
    finalize.add_argument("--run-dir", required=True)
    finalize.add_argument("--zotero-results", required=True)
    return parser
```

`main()` must print the run directory, final PDF directory, success/failure counts, fallback CSV path, and exact next command. It must never print Cookie contents.

- [ ] **Step 4: Run CLI tests and help smoke test**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchCliTests -v
.\.venv\Scripts\python.exe paper_batch.py --help
.\.venv\Scripts\python.exe paper_batch.py start --help
```

Expected: tests pass; help lists `start`, `resume`, and `finalize`.

- [ ] **Step 5: Commit**

```powershell
git add paper_batch.py tests/test_batch_workflow.py
git commit -m "Add unified paper batch CLI"
```

---

### Task 7: Teach `$paper-download` to coordinate Zotero in batches

**Files:**
- Modify: `skills/paper-download/SKILL.md`
- Modify: `tests/test_skills_packaging.py`
- Modify: `README.md`
- Modify: `README_zh.md`
- Modify: `MANUAL_QA.md`

**Interfaces:**
- Consumes: `paper_batch.py` commands and Zotero MCP tools.
- Produces: a documented Codex workflow that creates one temporary collection, batches writes, calls Zotero's available-PDF API, and writes `zotero_results.csv`.

- [ ] **Step 1: Add failing skill contract tests**

Add assertions to `tests/test_skills_packaging.py`:

```python
text = (PROJECT_ROOT / "skills" / "paper-download" / "SKILL.md").read_text(encoding="utf-8")
self.assertIn("paper_batch.py start", text)
self.assertIn("paper_batch.py resume", text)
self.assertIn("paper_batch.py finalize", text)
self.assertIn("library_search", text)
self.assertIn("library_import", text)
self.assertIn("Zotero.Attachments.addAvailablePDF", text)
self.assertIn("zotero_results.csv", text)
for forbidden in ("Sci-Hub", "Anna's Archive", "LibGen"):
    self.assertNotIn(forbidden, text)
```

- [ ] **Step 2: Run and verify skill test failure**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging -v
```

- [ ] **Step 3: Replace the skill route with the unified batch protocol**

Document this exact sequence in `skills/paper-download/SKILL.md`:

1. Run `paper_batch.py start`.
2. If `manual_retry.csv` is non-empty, pause once for the user and then run `paper_batch.py resume` once.
3. Read `zotero_fallback.csv`; if empty, run `finalize` with a header-only `zotero_results.csv`.
4. Check Zotero availability with `library_search(entity:"libraries", mode:"list")`.
5. Create one collection named `Codex下载回退_YYYYMMDD_HHMMSS`.
6. Search every DOI before import; batch-add existing items to the collection and batch-import only missing identifiers. For a row without DOI, accept a Zotero match only when the normalized title matches and either year or first author also matches; otherwise write `metadata_uncertain` without importing.
7. Batch Zotero write confirmations so the user is not prompted once per paper.
8. For items without an existing PDF, run one `zotero_script` write operation with an undo step and compatibility guard:

```javascript
const createdIds = [];
env.addUndoStep(async () => {
  for (const id of createdIds) {
    const attachment = await Zotero.Items.getAsync(id);
    if (attachment && !attachment.deleted) await attachment.eraseTx();
  }
});
if (typeof Zotero.Attachments.addAvailablePDF !== "function") {
  return { ok: false, reason: "zotero_api_unavailable", rows: [] };
}
const rows = [];
for (const itemId of itemIds) {
  const item = await Zotero.Items.getAsync(itemId);
  let attachment = null;
  for (const attachmentId of item.getAttachments()) {
    const candidate = await Zotero.Items.getAsync(attachmentId);
    if (candidate.isPDFAttachment() && await candidate.fileExists()) {
      attachment = candidate;
      break;
    }
  }
  let status = "existing_pdf";
  if (!attachment) {
    attachment = await Zotero.Attachments.addAvailablePDF(item);
    status = attachment ? "downloaded" : "no_pdf";
    if (attachment) createdIds.push(attachment.id);
  }
  rows.push({
    itemId,
    status,
    attachmentPath: attachment ? attachment.getFilePath() : "",
    reason: attachment ? "" : "no_available_pdf",
  });
}
return { ok: true, rows };
```

9. Write `zotero_results.csv` with exactly the five fields from the design.
10. Batch-apply `codex-download-success` or `codex-download-failed` tags to temporary-collection items; preserve the collection and all items after the task.
11. Run `paper_batch.py finalize` and report the final `pdfs` directory.
12. If Zotero is unavailable, write `zotero_unavailable` rows and leave the batch resumable.

- [ ] **Step 4: Update beginner documentation and manual QA**

Add one concise example to both READMEs:

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results"
```

Add the three CLI commands, output tree, one-time retry rule, Zotero prerequisite, temporary collection behavior, and no-overwrite behavior. Add the seven manual checks from the approved design to `MANUAL_QA.md`.

- [ ] **Step 5: Run skill/docs tests**

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging -v
rg -n "paper_batch.py|zotero_results.csv|Codex下载回退" README.md README_zh.md MANUAL_QA.md skills/paper-download/SKILL.md
```

- [ ] **Step 6: Commit only non-overlapping files**

```powershell
git add MANUAL_QA.md
git commit -m "Document Zotero paper download workflow"
```

Because README and Skill files currently contain user changes, do not stage them wholesale unless their existing diff is intentionally included and reviewed.

---

### Task 8: Full verification, skill installation, changelog, and manual acceptance

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `tests/test_batch_workflow.py`
- Verify: all files listed above
- External install target: the user's installed `paper-download` Skill, only after approval for external write.

**Interfaces:**
- Produces: verified local project behavior and an installed Skill usable in a new Codex task.

- [ ] **Step 1: Run syntax and complete offline tests**

```powershell
.\.venv\Scripts\python.exe -m compileall paper_batch.py paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
```

Expected: all commands return exit code 0.

- [ ] **Step 2: Add and run an offline end-to-end fixture**

Add this final integration test, using the `FakeGateway` and deterministic normalizer from Task 4:

```python
class BatchEndToEndTests(unittest.TestCase):
    def test_start_resume_finalize_produces_one_manifest_and_valid_pdfs(self) -> None:
        import csv
        from paper_automation.batch_workflow import finalize_batch, resume_batch, start_batch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_pdf = root / "project.pdf"
            project_pdf.write_bytes(b"%PDF-1.7\nproject fixture")
            zotero_pdf = root / "zotero.pdf"
            zotero_pdf.write_bytes(b"%PDF-1.7\nzotero fixture")
            normalized = [
                {"task_id": "paper-0001", "doi": "10.1000/a", "title": "A", "fixture_pdf": str(project_pdf)},
                {"task_id": "paper-0002", "doi": "10.1000/b", "title": "B", "fixture_pdf": ""},
                {"task_id": "paper-0003", "doi": "10.1000/c", "title": "C", "fixture_pdf": ""},
            ]
            gateway = FakeGateway()
            started = start_batch(
                input_text="fixture",
                input_path=None,
                output_root=root,
                gateway=gateway,
                normalizer=lambda **_kwargs: normalized,
            )
            resume_batch(started.paths.root, gateway=gateway)
            with started.paths.zotero_results.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=[
                    "task_id", "zotero_item_id", "attachment_path", "status", "reason",
                ])
                writer.writeheader()
                writer.writerow({
                    "task_id": "paper-0002",
                    "zotero_item_id": "42",
                    "attachment_path": str(zotero_pdf),
                    "status": "downloaded",
                    "reason": "",
                })
                writer.writerow({
                    "task_id": "paper-0003",
                    "zotero_item_id": "43",
                    "attachment_path": "",
                    "status": "no_pdf",
                    "reason": "no_available_pdf",
                })
            finalized = finalize_batch(started.paths.root, started.paths.zotero_results)

            self.assertEqual(gateway.retry_calls, 1)
            self.assertEqual(finalized.success_count, 2)
            self.assertEqual(finalized.failed_count, 1)
            self.assertEqual(len(list(started.paths.pdfs.glob("*.pdf"))), 2)
            self.assertTrue((started.paths.reports / "final_manifest.xlsx").exists())
            self.assertIn("no_available_pdf", (started.paths.reports / "run_summary.txt").read_text(encoding="utf-8"))
```

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchEndToEndTests -v
```

Expected: the test passes, valid PDFs are deduplicated, one retry occurs, and every row appears in the final manifest.

- [ ] **Step 3: Inspect security invariants**

```powershell
rg -n "Sci-Hub|scihub|Anna's Archive|annas_archive|LibGen|apply_auto_fallback" paper_batch.py paper_automation sd_institutional_skill.py paper_skill.py doi_batch_utils.py skills/paper-download/SKILL.md
rg -n "cookie.*value|password" results -g "*.txt" -g "*.csv" -g "*.json"
```

Expected: no shadow-library active-code matches and no credential values in generated reports.

- [ ] **Step 4: Append a complete `CHANGELOG.md` entry**

Record the date/time, task goal, every created/modified/deleted file, implementation details, reasons, exact run commands, generated outputs, success checks, Zotero prerequisite, access limitations, existing uncommitted files, and confirmation that the project was not packaged.

- [ ] **Step 5: Install the updated project Skill after explicit filesystem approval**

First dry-run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1 -DryRun
```

Then, after approval to write outside the project:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1
```

Restart/open a new Codex task so the updated Skill is loaded.

- [ ] **Step 6: Perform manual Zotero acceptance**

With Zotero open and an active personal library:

1. Run one list containing an existing Zotero PDF, an item without a PDF, and a DOI not yet in the library.
2. Confirm the temporary collection remains.
3. Confirm the existing PDF is copied without moving its Zotero attachment.
4. Confirm `addAvailablePDF` is attempted only for missing PDFs.
5. Confirm closing Zotero produces `zotero_unavailable` and reopening allows continuation.
6. Confirm any login/CAPTCHA prompt occurs no more than once per batch.
7. Open every final PDF and compare `final_manifest.xlsx` with the input list.

- [ ] **Step 7: Final completion audit**

For each approved design requirement, cite one authoritative artifact: test name/output, CLI output, batch state, final manifest, PDF file validation, Zotero collection state, or Skill text. Do not claim completion if Zotero manual acceptance or any required test is missing.
