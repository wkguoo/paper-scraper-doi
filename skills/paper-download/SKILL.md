---
name: paper-download
description: Use when Codex needs ScienceDirect, institutional, or open-access PDF downloads from DOI/title lists, including a project-first batch that may require a connected Zotero fallback.
---

# Paper Download

## Entry map (mandatory)

Recommended entry / default product entry for agents and users: `paper_batch.py`
(this skill). Compatibility CLIs and other skills are not primary routes.

| User intent | Use | Do not use as primary |
| --- | --- | --- |
| DOI metadata preflight only (no PDF) | `preflight_doi_metadata.py` (parallel Crossref) | in-batch `start` DOI preflight (`doi_preflight.py`) |
| New literature list (any publisher mix) | `paper_batch.py start --no-doi-preflight` after parallel Crossref when the list already has DOIs | `paper_skill.py`, `sd_scraper.py` |
| Continue / collect Zotero results | `paper_batch.py zotero --run-dir` | direct Zotero MCP for normal runs |
| Optional one-shot login/CAPTCHA retry (compat) | `paper_batch.py resume --run-dir` only with `--enable-manual-retry` batches | restart `start` unnecessarily |
| GUI | UI tab **统一批次（推荐）**; use **运行日志** to inspect progress | Expect DOI/OA compatibility tabs or GUI email/Cookie fields |

Use this as the single entry point for a mixed DOI/title paper list. Run the
project workflow first. Only `zotero_fallback.csv` rows enter the bridge. Never
send the complete input list to Zotero again.

## Mandatory existing run-dir route

This rule overrides every later section, including prerequisites, recovery,
and direct routes. It applies when the user supplies an existing `<run-dir>`
and OA/institutional stages are already done (default path skips manual
resume; `manual_retry.csv` is usually empty).

Do not inspect `paper_skill.py --help`. Never run `paper_skill.py` for an existing batch run directory.
Do not invent `zotero-fallback`, `--input`, or `--wait`. Do not run `start`,
`resume`, or a normal-path `finalize`. After a read-only check of
`<run-dir>\working\zotero_fallback.csv`, the first and only executable command
is exactly:

```powershell
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
```

If it returns exit code `3`, keep Zotero open with plugin **0.2.0+** (auto-confirm
by default). After the plugin finishes, rerun exactly that same command—no other
downloader command and no direct Zotero write. Do not ask the user to click a
confirmation modal unless they disabled auto-confirm.

## Repository and prerequisites

Locate the repository in this order:

1. Current directory or a parent containing `paper_batch.py`,
   `sd_institutional_skill.py`, and `paper_automation`.
2. `$env:PAPER_SCRAPER_DOI_ROOT` when it points to that repository.
3. A packaged folder containing the same scripts.
4. Otherwise ask the user for the repository path.

Use `.venv\Scripts\python.exe` when present. For bridge fallback, keep Zotero 9
open with the local “文献下载桥接” plugin enabled. Never expose cookies, passwords,
or session data, and never automate a CAPTCHA.

For login or verification, try the Codex in-app browser first when it is
available. If the in-app browser cannot be called or cannot provide a session
usable by the local project, let the external browser fallback run. On Windows
the fallback order is Google Chrome, Edge Stable/Beta/Dev/Canary, then
Playwright Chromium. An explicit `--browser-exe` or
`PAPER_SCRAPER_BROWSER_EXE` override always takes precedence.

## Parallel Crossref DOI preflight (default metadata check)

Do **not** use the in-batch sequential DOI preflight inside `paper_batch.py start`
(`paper_automation.doi_preflight`) as the primary metadata check. It is too
slow on large DOI lists.

For a project Markdown DOI table (15 data columns, unique contiguous indexes,
one DOI per row), run parallel Crossref. It does **not** download PDFs:

```powershell
.\.venv\Scripts\python.exe preflight_doi_metadata.py --input "<list.md>" --output "<out-dir>\<stem>_预检.csv" --workers 8
```

- Concurrent Crossref `works/{DOI}` (`--workers` 1–8; use 8 for large lists).
- Resume from `<output>.partial.csv` if interrupted. Refuses to overwrite an
  existing `--output`.
- Statuses: `verified_crossref`, `doi_not_found`, `doi_mismatch`,
  `metadata_incomplete`, `rate_limited`, `api_error`. Title clash vs the source
  table is `title_difference_review` on a verified row.
- Exit `0` if every row is `verified_crossref`, else `2`.
- First five CSV columns (`doi,title,authors,journal,year`) are download-ready.

If the user only asked to preflight, stop after that CSV (plus optional
verified / review splits). Do not start a PDF batch.

Then download with `--no-doi-preflight` so `start` does not re-run sequential
Crossref:

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "<verified-or-download-ready.csv>" --out "<output-root>" --no-doi-preflight
```

`--resolve-title-metadata` is a different, title-only path. Do not substitute
sequential in-batch DOI preflight for this parallel catalog.

## Elsevier API-first ScienceDirect route

For a ScienceDirect DOI (normally `10.1016/*`), `paper_batch.py start`
automatically uses this fixed order:

1. Elsevier Article/Object API for the main PDF and requested supplements.
2. Bounded API retry before changing channels: retry `network_error`,
   `rate_limited`, and `invalid_pdf` after 5 seconds and 15 seconds (three API
   attempts total). Do not retry terminal `unauthorized`, `not_entitled`,
   `not_found`, or `no_main_pdf` responses.
3. Existing browser institutional access for only the DOI rows that still did
   not succeed through the API.
4. Bounded OA recovery.
5. Zotero fallback for the remaining DOI-bearing failures.

This is an internal stage of the unified batch. Do not call
`paper_automation/elsevier_api.py`, `sd_institutional_skill.py`, or a hand-made
Elsevier request as a separate user download route.

Configuration is process-environment only:

- `ELSEVIER_API_KEY` enables the API stage. When missing, continue directly to
  the browser path; absence of the key is not a terminal batch failure.
- `ELSEVIER_INSTTOKEN` is optional. Never require it when API Key-only access
  succeeds.
- Never ask the user to paste either credential into chat. Check only whether
  each variable is present. The application does not auto-load `.env` or
  `.env.example`.
- Never place credentials in URLs, logs, reports, commands, or input files; do
  not disable TLS verification, fabricate a token, alter networking, solve a
  CAPTCHA, or bypass publisher access controls.

API success for a DOI must not create the browser downloader or read browser
cookies. A successful main PDF remains successful if an individual supplement
fails; record that attachment failure separately and do not launch the browser
for it. `--no-download-supplements` disables supplements on both API and
browser paths.

Preserve the API status without treating it as the final browser result:
`api_key_missing`, `unauthorized`, `not_entitled`, `not_found`,
`rate_limited`, `no_main_pdf`, `invalid_pdf`, `network_error`, or `success`.
After API 401, or after a 429 remains after the bounded API retries, stop
further API probes for that batch and route the remaining ScienceDirect rows
to the browser. Keep browser/OA/Zotero failure classification authoritative
for later recovery. `request_attempts` records whether a row used one, two, or
three real API calls; circuit-marked rows use zero.

Use `<run-dir>\reports\sciencedirect\elsevier_api_attempts.csv` for the
sanitised API audit. It may contain DOI, safe statuses, HTTP status, boolean
authentication mode, request-attempt count, FULL XML/main-EID flags,
PDF size/validity, and browser fallback state; it must not contain response
bodies, full headers, credentials, or cookies. Successful PDFs and supplements
still follow the delivery naming and directory rules below.

For development acceptance, prefer a real API Key-only success through
`paper_batch.py start`. If no known no-entitlement DOI or non-institutional
network exists, do not probe random papers without bound. Run
`.\.venv\Scripts\python.exe -m unittest tests.test_elsevier_api -v` for the
403 → `not_entitled` → browser routing check, and record the unavailable live
403 as `waived_environment_unavailable`; never present a simulated 403 as a
publisher response.

## CSV reading contract

Read `manual_retry.csv` and `zotero_fallback.csv` with Python `csv` semantics,
`newline=""`, and `encoding="utf-8-sig"` (UTF-8-SIG). Require this exact
project-generated header:

```text
task_id,source_index,input_doi,input_title,doi,title,authors,journal,year,publisher,status,source,file,reason
```

Pending CSV files may ignore completely blank records: a pending record is
blank only when every parsed field contains no non-whitespace value. A pending
record is data when at least one field is non-empty after trimming.

Every `zotero_results*.csv` file is stricter. Read with
`csv.reader(..., strict=True)` and require exactly:

```text
task_id,zotero_item_id,attachment_path,status,reason
```

Reject physical blank records after the header, all-whitespace data rows,
rows with other than five fields, decoding/CSV errors, duplicate or unknown
task IDs, and non-exact headers. Stop on validation failure; do not guess.

## Bridge-first batch protocol

Keep the CLI's printed run directory as `<run-dir>`. Do not edit the original
input or any project-generated pending CSV.

1. Prefer a **DOI-only** list (one DOI per line, or a CSV/XLSX with a DOI column).
   Markdown is allowed, but by default only explicit DOIs become tasks; section
   headers and notes are dropped. Use `--resolve-title-metadata` only when the
   user explicitly wants title-only rows.

2. For DOI lists, run `preflight_doi_metadata.py` first (see Parallel Crossref
   DOI preflight). Then run the project download with **`--no-doi-preflight`**
   (no manual resume; failures with DOI go to Zotero; `start` auto-queues the
   bridge and waits):

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --no-doi-preflight
   ```

   Keep Zotero 9 open with the bridge plugin **0.2.0+** enabled before or during
   `start`. Defaults: auto-Zotero + `--wait-seconds 600`. Use `--no-auto-zotero`
   only if the user asks to queue later; `--enable-manual-retry` only for the
   old one-shot login/CAPTCHA path. Do not leave in-batch sequential DOI
   preflight on for large lists.

3. Default batches write empty `manual_retry.csv`. Skip `resume` unless the
   user explicitly started with `--enable-manual-retry` and that file has data
   rows. For that compat path only: pause once for the browser action, then
   run exactly one `resume`. Never run `resume` a second time.

4. Only DOI-bearing bridge-eligible failures enter `zotero_fallback.csv`
   (`unsupported_publisher`, network/capture errors, etc.). Rows that are
   `metadata_uncertain` / no DOI stay in reports only and are **not** sent to
   Zotero. Do not use direct Zotero MCP writes for normal bridge execution.

5. If auto-queue was disabled (`--no-auto-zotero`) or bridge was not run yet,
   run the local bridge command once after `start`:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
   ```

   The project publishes strict version-1 JSON jobs only under
   `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1`. It sends no cookies,
   credentials, arbitrary commands, URLs, or caller-selected output paths.

6. Exit code `3` means the batch is queued and waiting for the plugin to finish.
   Plugin **0.2.0+** auto-confirms (one Zotero confirmation per batch is applied
   automatically; no modal unless the user disabled auto-confirm). Keep Zotero
   open. Do not rerun `start` or `resume`, and do not import items manually while
   the batch is active.

7. After the plugin writes every outbox result for the run, rerun only the same
   command (or rely on `start --wait-seconds` already polling):

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
   ```

   The command validates every request/result identity and SHA-256, creates one
   strict `zotero_results.csv` (or an exclusive retry filename), and finalizes
   automatically. Do not call `paper_batch.py finalize` on the normal bridge
   path and do not construct plugin results by hand.

8. Report `<run-dir>\结果\pdf\` as the final user PDF directory and
   `<run-dir>\reports\` as the audit trail. Never report unresolved rows as
   complete. Local checks do not certify an attachment path: finalize revalidates PDF content and reparse-point safety
   before copying.

## Failure routing (non-Elsevier)

| Situation | Next hop |
| --- | --- |
| No DOI / `metadata_uncertain` | Reports only (not Zotero) |
| `unsupported_publisher` | Zotero fallback (DOI required); no browser retry |
| `not_pdf_response` / network `error` | `retry-failed` (default whitelist) then Zotero |
| Gold OA / metadata OA signal | Bounded OA first / `recover-oa` (no deep multi-source) |

`retry-failed` defaults to network-class failures only; use `--retry-all-failed`
only when the user asks for the broader set.

## Bridge unavailable or plugin not installed

Use this section only when the local bridge cannot run, Zotero is unavailable,
or the plugin is not installed. Do not fall back to direct Zotero MCP writes,
custom Zotero scripts, repeated imports, or SQLite edits.

- Preserve `<run-dir>`, `manual_retry.csv`, `zotero_fallback.csv`, existing
  PDFs, reports, queue jobs, and prior result files. Do not rerun project
  downloads or a second `resume`.
- Report `zotero_unavailable` for current fallback rows and keep the batch
  recoverable. This is not success.
- If a local recovery CSV is necessary, build the complete five-column row set
  in memory, validate all current task IDs, and use Python standard-library
  `csv.writer` with open mode `x`, `newline=""`, and
  `encoding="utf-8-sig"`. Never truncate, overwrite, append, or partially
  publish an earlier file.
- Prefer `<run-dir>\working\zotero_results.csv` only when it does not exist.
  On collision or a changed task set, create
  `zotero_results_retry_YYYYMMDD_HHMMSS.csv` exclusively.
- Pass only that validated recovery file to:

  ```powershell
  .\.venv\Scripts\python.exe paper_batch.py finalize --run-dir "<run-dir>" --zotero-results "<selected-zotero-results.csv>"
  ```

- When Zotero later becomes available, rerun the bridge for still-unresolved
  fallback rows. Never replace immutable prior evidence.

The bridge/plugin may return `existing_pdf`, `downloaded`, `no_pdf`,
`metadata_uncertain`, `not_found`, `no_attachment`, `download_failed`,
`zotero_unavailable`, `zotero_api_unavailable`, `user_cancelled`,
`job_expired`, `job_id_conflict`, or `plugin_error`. Preserve the precise
reason and let project finalization decide the final batch state.

## OA 直下 + limited recovery (unsupported / capture miss)

**Default (do not skip):** after non-Elsevier institutional miss
(`unsupported_publisher`, `not_pdf_response`, adapter error), the project
**automatically tries bounded OA HTTP download** before Zotero:

- Inside `run_institutional_workflow` (`adapter=oa_direct` on success).
- Again in `paper_batch` post-stage OA recovery for
  `unsupported_publisher` / `not_pdf_response` / `pending_zotero` **even without**
  a pre-flagged OA signal.

Do **not** manually probe with multi-URL browser sessions, Wayback, CORE ID fishing, OAI, or guessed bitstreams.

Optional second chance after `start`:

```powershell
.\.venv\Scripts\python.exe paper_batch.py recover-oa --run-dir "<run-dir>"
```

- Budget: **≤60s per DOI** (default; institutional inline ~45s); metadata + annotated OA URL(s) + **at most one** repo `pdf_url`.
- Other failure classes (not unsupported/not_pdf) still need an OA signal unless `recover-oa` is used with broader flags.
- Early stop on first valid `%PDF`; host unreachable is cached for the run.
- Repository landing with no PDF URL → `repo_metadata_only`, stop.
- On failure: keep prior reason, then Zotero; do not start a long multi-source chase.

## PDF delivery naming (mandatory)

Write every successful PDF into user delivery `结果/pdf/` with the final name
**at download/publish time**:

```text
年份-第一作者姓-题名.pdf
```

Example: `2001-Kim-Densification-behavior-of-titanium-alloy-powder.pdf`

- Shared helper: `paper_automation.file_manager.make_pdf_filename()`.
- If year/author/clean title are missing from the input, resolve by DOI (Crossref/OpenAlex/publisher metadata) **before** naming; do not leave `0000-Unknown-...` or `paper-000N.pdf` as the user-facing file when metadata can be resolved.
- Do not rely on a separate post-download rename step for normal jobs. Report the year–author–title paths as the delivered PDFs.

## User delivery package

The only user-facing package is `<run-dir>\结果\`. Keep its top level limited
to the following four items, plus `补充材料\` only when at least one
supplementary file was actually copied:

```text
结果\
├── <original-input-name>     # original input copied byte-for-byte
├── 下载清单.csv               # final user inventory
├── pdf\                       # article PDFs only
├── md\                        # always created; reserved for later PDF→MD
└── 补充材料\                  # conditional; grouped by article filename stem
```

Rules for this package:

- Preserve the input file's original basename and format. For direct text
  input, create `输入清单.txt`; reserved-name collisions receive an
  `输入清单_` prefix.
- Keep article PDFs under `结果/pdf/` and use the mandatory
  `年份-第一作者姓-题名.pdf` naming rule. Do not leave article PDFs directly
  under `结果/`.
- Keep supplementary files under `结果/补充材料/<article-stem>/`; omit the
  top-level folder when no supplementary file exists. The inventory fields
  `结果文件` and `补充材料` use batch-root-relative paths such as
  `结果/pdf/paper.pdf`.
- Always create `结果/md/`, but do not convert PDFs to Markdown in this skill.
  A later `docling-pdf-md` task writes Markdown there.
- Re-publishing or `refresh-delivery` must preserve user-added PDFs,
  supplementary files, and Markdown files. Legacy PDFs directly under
  `结果/` are migrated into `结果/pdf/` during the next publish.
- `reports/`, `working/`, and the internal cache `pdfs/` remain under the run
  root for recovery and audit. They are not user delivery items. Rename maps
  belong under `reports/`, not `结果/`.

## Internal output tree

```text
results\paper_batch_YYYYMMDD_HHMMSS\
├── 结果\          # only the user delivery package described above
├── pdfs\          # internal download cache; not user delivery
├── reports\
│   ├── final_manifest.csv
│   ├── final_manifest.xlsx
│   ├── failed.csv
│   └── run_summary.txt
└── working\
    ├── manual_retry.csv
    ├── zotero_fallback.csv
    ├── zotero_results.csv
    └── zotero_results_retry_YYYYMMDD_HHMMSS.csv
```

## Single user-facing route

Always start a new PDF download with `paper_batch.py start` (after parallel
Crossref preflight when the list already has DOIs). Do not expose
or select `paper_skill.py` or `sd_institutional_skill.py` as standalone user
routes. They are internal adapters used by the unified batch implementation;
direct execution would bypass the shared state, failure classification, and
Zotero fallback queue.

The unified batch may still write separate OA, ScienceDirect, and institutional
stage reports internally. Those are implementation details, not separate user
workflows. `supplement_download_report.csv` remains an internal report; copied
supplementary files are published only under `结果/补充材料/`.

## Safety

- Do not expose credentials, cookies, passwords, or session data.
- Do not automatically solve CAPTCHA or bypass publisher access controls.
- Do not overwrite original inputs, result files, PDFs, Zotero attachments,
  collections, items, or the only copy of a queue/result artifact.
- Do not use direct Zotero MCP writes for normal bridge execution.
- Never report unavailable or unresolved Zotero fallback as complete.
