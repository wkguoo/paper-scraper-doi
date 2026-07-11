# Zotero 9 Bridge Integration and Acceptance Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the completed project-side queue and Zotero 9 plugin into the existing `$paper-download` workflow, prove the end-to-end handoff without live network calls, then perform an approval-gated test-profile acceptance.

**Architecture:** The project bridge writes only a strict JSON job and consumes only a strict JSON result. The plugin is treated as an external peer in automated tests through a deterministic fake result publisher; the existing `finalize_batch()` remains the sole authority for local PDF path, content, and reparse-point validation. The Codex Skill orchestrates `start`, at most one `resume`, `zotero`, and final reporting without direct Zotero MCP writes.

**Tech Stack:** Python 3, `unittest`, `pathlib`, `csv`, `json`, existing `paper_batch.py`, `paper_automation.zotero_bridge`, Zotero 9 test profile, Node built-in tests for plugin source.

## Global Constraints

- Complete the project-bridge and plugin plans before this plan.
- The Skill must never send the original full input list to Zotero; it uses only `working\zotero_fallback.csv`.
- The bridge request/result schema version is exactly 1 and contains no credentials, cookies, arbitrary commands, URLs, or externally supplied output directories.
- PDF finalization remains non-destructive and must continue to reject missing, relative, reparse-point, changed, and non-PDF attachment paths.
- Keep the one-`resume` limit, one Zotero confirmation per batch, and per-item failure isolation.
- Do not use Sci-Hub, Anna's Archive, LibGen, CAPTCHA automation, direct SQLite, or unauthenticated network listeners.
- Do not generate an XPI, install an extension, or modify the main Zotero profile until an explicit user approval gate in Task 4.
- Do not run the existing Windows project packaging script.
- Append every project modification to `CHANGELOG.md`.

---

## File Structure

- Create `tests/test_zotero_bridge_integration.py`: deterministic project/plugin protocol test using a fake outbox result.
- Modify `skills/paper-download/SKILL.md`: bridge-first orchestration, with strict manual CSV recovery preserved only as a failure path.
- Modify `tests/test_skills_packaging.py`: assert the bridge-first Skill contract.
- Modify `README.md`, `README_zh.md`, and `MANUAL_QA.md`: beginner workflow and test-profile acceptance instructions.
- Create `docs/zotero_bridge_beginner_guide.md`: normal run, failure recovery, and safe test profile installation.
- Modify `CHANGELOG.md`: record test evidence and approval boundaries.

### Task 1: Prove project/plugin JSON-to-PDF integration offline

**Files:**
- Create: `tests/test_zotero_bridge_integration.py`
- Modify: `paper_automation/zotero_bridge.py` only for fixes found by the test
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `queue_bridge_jobs(run_dir, library_id, bridge_root) -> BridgeBatch`, `run_zotero_bridge() -> BridgeRunResult`, and the plugin result schema.
- Produces: an offline acceptance test that proves one project PDF plus one bridge PDF reach the final directory while a third item remains failed.

- [ ] **Step 1: Write the failing end-to-end test**

Create a temporary run through the existing `start_batch()` test gateway, then publish a fake plugin result after the job appears in `outbox`. The test must use three records and assert all of the following:

```python
class ZoteroBridgeIntegrationTests(unittest.TestCase):
    def test_bridge_result_finalizes_project_and_zotero_pdfs_without_source_mutation(self) -> None:
        # Arrange: paper-0001 is already project-downloaded; paper-0002 and paper-0003 are fallback rows.
        # Queue one logical bridge batch and assert its sole small-job request contains only paper-0002 and paper-0003.
        # Publish the plugin-shaped JSON result:
        #   paper-0002 -> existing_pdf with an absolute fixture PDF and item ID 304
        #   paper-0003 -> no_pdf with reason no_available_pdf
        # Act: run_zotero_bridge(..., wait_seconds=1).
        # Assert: success_count == 2, failed_count == 1, no duplicate task IDs,
        # `pdfs` contains exactly two valid PDF byte hashes, source fixture bytes stay unchanged,
        # and reports/final_manifest.csv plus final_manifest.xlsx exist.
        # Act again with the same job/result. Assert: no new PDF, no changed source bytes,
        # and identical CSV/state report content.
```

Include negative subtests for a mismatched job hash, extra result field, duplicate task ID, and a `downloaded` row with an invalid local path. Each must leave `batch_state.json` and final PDFs unchanged.

Add a separate 101-fallback-row integration test. Its fake plugin must publish only chunk 1 first and assert that `run_zotero_bridge(..., wait_seconds=0)` leaves the state and `zotero_results.csv` untouched. After chunk 2 is published, one rerun must produce one ordered 101-row CSV and one finalization call. Assert both requests share `run_id`/`collection_name`, have chunk positions `1/2` and `2/2`, and do not duplicate PDF copies.

- [ ] **Step 2: Run the test and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_integration -v
```

Expected: import failure until project-bridge Tasks 1-4 are complete.

- [ ] **Step 3: Implement only gaps exposed by the integration test**

Do not duplicate validation in the test. Fix the production boundary that fails the assertion, then keep the test as the single reproducible protocol acceptance signal.

- [ ] **Step 4: Run focused and full project tests**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_zotero_bridge_integration tests.test_zotero_bridge tests.test_batch_workflow.BatchEndToEndTests -v
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
```

Expected: all pass; no network, Zotero runtime, browser, Cookie, or XPI is required.

- [ ] **Step 5: Append CHANGELOG and commit**

```powershell
git add paper_automation/zotero_bridge.py tests/test_zotero_bridge_integration.py CHANGELOG.md
git commit -m "Verify Zotero bridge integration offline"
```

### Task 2: Change the installed Skill to bridge-first orchestration

**Files:**
- Modify: `skills/paper-download/SKILL.md`
- Modify: `tests/test_skills_packaging.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: CLI command `paper_batch.py zotero --run-dir <run-dir>`.
- Produces: a Skill that does not call `collection_update`, `library_import`, `library_update`, or `zotero_script` for normal bridge execution.

- [ ] **Step 1: Add a failing Skill contract test**

Add a test that requires these exact normalized phrases in the Skill:

```python
required = (
    "paper_batch.py zotero --run-dir",
    "Only `zotero_fallback.csv` rows enter the bridge.",
    "one Zotero confirmation per batch",
    "zotero_results.csv",
    "Do not use direct Zotero MCP writes for normal bridge execution.",
    "zotero_unavailable",
    "finalize revalidates PDF content and reparse-point safety",
)
for phrase in required:
    self.assertIn(phrase, skill_text)
for obsolete_normal_path in (
    "collection_update(action:\"create\"",
    "library_import(kind:\"identifiers\"",
    "library_update(kind:\"collections\"",
):
    self.assertNotIn(obsolete_normal_path, skill_text)
```

Keep the old manual CSV recovery rules, but move them into an explicit “bridge unavailable or plugin not installed” recovery section. They must not become direct-write instructions.

- [ ] **Step 2: Run the Skill test and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging.SkillPackagingTests.test_paper_download_skill_uses_zotero_bridge -v
```

Expected: test method or required bridge phrases are missing.

- [ ] **Step 3: Rewrite the bridge stage of `SKILL.md`**

Replace normal Zotero MCP write instructions with this exact flow:

```text
1. Read manual_retry.csv and zotero_fallback.csv using the existing strict CSV rules.
2. If fallback has rows, run paper_batch.py zotero --run-dir "<run-dir>".
3. If exit code is 3, tell the user once that Zotero shows one batch confirmation, even if the batch has several subjobs; do not rerun start/resume.
4. After the plugin writes every outbox result for that run, rerun the same zotero command. It validates all JSON files, creates one strict CSV exclusively, and finalizes automatically.
5. If the bridge reports unavailable, retain the batch and write/consume only a strict recoverable result file. Do not attempt direct Zotero MCP writes.
```

Retain the legal-source, credentials, CAPTCHA, original-file, and final-report safety rules.

- [ ] **Step 4: Run packaging and full tests**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging -v
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: all pass.

- [ ] **Step 5: Append CHANGELOG and commit**

```powershell
git add skills/paper-download/SKILL.md tests/test_skills_packaging.py CHANGELOG.md
git commit -m "Use Zotero bridge in paper download skill"
```

### Task 3: Document beginner operation and integration recovery

**Files:**
- Create: `docs/zotero_bridge_beginner_guide.md`
- Modify: `README.md`
- Modify: `README_zh.md`
- Modify: `MANUAL_QA.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: verified CLI and plugin behavior from prior tasks.
- Produces: Chinese-first user instructions that distinguish project batch state, bridge queue state, plugin confirmation, and final PDF output.

- [ ] **Step 1: Write documentation acceptance assertions**

Add a test that checks the guide and Chinese README mention all of:

```text
paper_batch.py start
paper_batch.py resume
paper_batch.py zotero
one confirmation
%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1
pdfs\
reports\
do not overwrite
Zotero test profile
do not install to the main profile yet
```

- [ ] **Step 2: Run documentation test and verify RED**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging.SkillPackagingTests.test_zotero_bridge_beginner_docs -v
```

Expected: guide/test method missing.

- [ ] **Step 3: Write beginner guide and update manual QA**

The guide must show this user-visible sequence:

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results"
.\.venv\Scripts\python.exe paper_batch.py resume --run-dir "<run-dir>"
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
```

State that `resume` is used only when the project emitted manual retry rows; a `zotero` exit code of 3 means wait for the one Zotero confirmation and rerun only `zotero`; the final PDFs are in `<run-dir>\pdfs`; reports explain all unresolved items. Include recovery for no Zotero, stale job, plugin version mismatch, cancellation, and no-PDF result without suggesting repeated imports or manual SQLite edits.

- [ ] **Step 4: Run documentation and full tests**

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_skills_packaging -v
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
```

Expected: all pass.

- [ ] **Step 5: Append CHANGELOG and commit**

```powershell
git add docs/zotero_bridge_beginner_guide.md README.md README_zh.md MANUAL_QA.md tests/test_skills_packaging.py CHANGELOG.md
git commit -m "Document Zotero bridge workflow"
```

### Task 4: Approval-gated Zotero 9 test-profile acceptance

**Files:**
- Modify: `MANUAL_QA.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: a user-approved generated XPI and profile `elpj7iql.Zotero test` only.
- Produces: recorded manual acceptance evidence; no main-profile installation.

- [ ] **Step 1: Ask for the narrow installation approval**

Ask exactly: “是否允许生成一个测试用 XPI，并仅安装到 `Zotero test` 配置以验证本地桥接？不会修改主 Zotero 配置或主文库。” Do not build or install before a clear affirmative answer.

- [ ] **Step 2: Build XPI after approval and inspect its contents**

```powershell
powershell -ExecutionPolicy Bypass -File .\build_zotero_bridge_xpi.ps1 -OutputDirectory .\dist
tar -tf .\dist\zotero-paper-download-bridge-<version>.xpi
```

Expected: root-level `manifest.json`, `bootstrap.js`, `content/`, and `locale/`; no `tests/`, queue files, logs, credentials, or project PDF files.

- [ ] **Step 3: Install only in the test profile and restart Zotero test**

Use Zotero’s Add-ons UI in the `Zotero test` profile. Verify the extension is active and the Tools menu contains “文献下载桥接”. Do not use direct profile file copy and do not install to `g39b695l.default`.

- [ ] **Step 4: Perform the eight-item manual acceptance set**

1. No job shows idle status without errors.
2. A single declared chunk of a two-subjob run shows no confirmation; after its second chunk arrives, the two queued subjobs sharing a run ID show exactly one confirmation.
3. Cancel produces `user_cancelled` result rows and zero library writes.
4. Existing PDF returns `existing_pdf`; original attachment hash stays unchanged.
5. Existing item without PDF calls available-PDF once and returns `downloaded` or `no_pdf`.
6. Missing DOI imports once into the preserved temporary collection and does not duplicate on replay.
7. Close/restart Zotero during a three-item job; it resumes without a second confirmation or duplicate write.
8. Project consumes the result, finalizes PDF copies, and repeated `zotero` command is idempotent.

For each item record date/time, test library ID, job ID, result status, output paths, and any error text without credentials.

- [ ] **Step 5: Do not install to the main profile without a second approval**

After test acceptance passes, present the evidence and ask separately for main-profile installation. Keep the XPI and test artifacts; do not automatically package the Windows application.
