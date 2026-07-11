---
name: paper-download
description: Use when Codex needs ScienceDirect, institutional, or open-access PDF downloads from DOI/title lists, including a project-first batch that may require a connected Zotero fallback.
---

# Paper Download

Use this as the single entry point for a mixed DOI/title paper list. Run the
project workflow first. Only `zotero_fallback.csv` rows enter the bridge. Never
send the complete input list to Zotero again.

## Mandatory existing run-dir route

This rule overrides every later section, including prerequisites, recovery,
and direct routes. It applies when the user supplies an existing `<run-dir>`
and says the one manual retry is already finished.

Do not inspect `paper_skill.py --help`. Never run `paper_skill.py` for an existing batch run directory.
Do not invent `zotero-fallback`, `--input`, or `--wait`. Do not run `start`,
`resume`, or a normal-path `finalize`. After a read-only check of
`<run-dir>\working\zotero_fallback.csv`, the first and only executable command
is exactly:

```powershell
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
```

If it returns exit code `3`, ask the user only to keep Zotero open and approve
the single batch confirmation. After the plugin finishes, rerun exactly that
same command—no other downloader command and no direct Zotero write.

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

1. Run the project workflow first:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results"
   ```

2. Read `<run-dir>\working\manual_retry.csv`. If it has data rows, pause once
   for the user to finish the required browser action, then run exactly one
   retry:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py resume --run-dir "<run-dir>"
   ```

   Never run `resume` a second time. Skip it when the file has no data rows.

3. Read `<run-dir>\working\zotero_fallback.csv` after that one permitted
   retry. Only `zotero_fallback.csv` rows enter the bridge. Do not use direct
   Zotero MCP writes for normal bridge execution.

4. Run the local bridge command:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
   ```

   The project publishes strict version-1 JSON jobs only under
   `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1`. It sends no cookies,
   credentials, arbitrary commands, URLs, or caller-selected output paths.

5. Exit code `3` means the batch is queued and waiting. Tell the user once to
   keep Zotero open and accept the one Zotero confirmation per batch. Several
   subjobs/chunks still produce one confirmation. Do not rerun `start` or
   `resume`, and do not import items manually while the batch is active.

6. After the plugin writes every outbox result for the run, rerun only the same
   command:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
   ```

   The command validates every request/result identity and SHA-256, creates one
   strict `zotero_results.csv` (or an exclusive retry filename), and finalizes
   automatically. Do not call `paper_batch.py finalize` on the normal bridge
   path and do not construct plugin results by hand.

7. Report `<run-dir>\pdfs\` as the final PDF directory and `<run-dir>\reports\`
   as the audit trail. Never report unresolved rows as complete. Local checks
   do not certify an attachment path: finalize revalidates PDF content and reparse-point safety
   before copying.

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

## Output tree

```text
results\paper_batch_YYYYMMDD_HHMMSS\
├── pdfs\
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

## Direct routes without an existing run-dir

Use this section only when the user did not supply an existing batch run
directory. For a ScienceDirect/Elsevier request that does not need the unified batch, use
`sd_institutional_skill.py`. For noisy beginner lists, start with
`--beginner --preflight`. Formal runs may write `supplement_download_report.csv`
and `supplements\`; use `--no-download-supplements` only when the user declines
supplementary files. For clearly legal open-access assistance without institutional
access, use `paper_skill.py` and report unresolved rows honestly.

## Safety

- Do not expose credentials, cookies, passwords, or session data.
- Do not automatically solve CAPTCHA or bypass publisher access controls.
- Do not overwrite original inputs, result files, PDFs, Zotero attachments,
  collections, items, or the only copy of a queue/result artifact.
- Do not use direct Zotero MCP writes for normal bridge execution.
- Never report unavailable or unresolved Zotero fallback as complete.
