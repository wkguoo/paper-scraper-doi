# Manual Zotero bridge / existing queue recovery

Read this reference only when the user explicitly requests Zotero native PDF
retrieval, or an existing run has `working/zotero_bridge_jobs.json` and the user
asks to continue that batch. Normal Codex lookup uses the official Zotero plugin
and does not enter this protocol. Do not migrate or rewrite existing queue jobs.

## Start or continue the manual route

Keep the actual `<run-dir>` and read `working/zotero_fallback.csv` using the CSV
contract in the main skill. Only its remaining DOI-bearing failures enter the
bridge. Do not import the complete input list again.

```powershell
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
```

For an existing queued run, rerun only the same command. Do not restart `start`,
run project downloads again, or change to the official lookup while its bridge
manifest exists. `paper_skill.py` is never a recovery route for a batch.

New downloads can explicitly opt in with `start --auto-zotero`; `retry-failed`
and `recover-oa` accept the same flag. The default is off. `--no-auto-zotero`
is retained for compatibility and is mutually exclusive with `--auto-zotero`.
`--library-id` and `--wait-seconds` apply to this opt-in/manual bridge only.
Default manual waiting is 600 seconds; 0 only queues and returns.

Keep the intended Zotero 9 instance open with the “文献下载桥接” plugin enabled.
Plugin 0.2.0+ applies one Zotero confirmation per batch automatically, unless the
user disabled auto-confirm. Do not request a confirmation modal when it is not
needed. A missing plugin or unavailable Zotero is not success.

Exit code `3` means the bridge is still waiting, not necessarily missing or
disabled. Preserve the run; the same command collects results once ready. Check
the plugin status when a download is pending; do not start another write or
repeat imports while the first call is in flight.

## Queue and results

- The project publishes strict version-1 JSON jobs only under
  `%LOCALAPPDATA%\PaperScraperDOI\zotero-bridge\v1`.
- Jobs contain no cookies, credentials, arbitrary commands, URLs or caller
  selected output paths. Never edit request JSON, manifests or plugin state.
- The collector verifies request/result identity and SHA-256 for every outbox
  result. It writes `zotero_results.csv`, or an exclusively created
  `zotero_results_retry_YYYYMMDD_HHMMSS.csv`, and finalizes automatically.
- Do not construct successful plugin results by hand. Do not run a separate
  normal-path `finalize` after bridge collection; publication has already run.
- Preserve `existing_pdf`, `downloaded`, `no_pdf`, `metadata_uncertain`,
  `not_found`, `no_attachment`, `download_failed`, `zotero_unavailable`,
  `zotero_api_unavailable`, `user_cancelled`, `job_expired`, `job_id_conflict`,
  and `plugin_error` with their actual reasons.
- Finalization revalidates PDF content and reparse-point safety. Delivery still
  follows the main skill's naming and package rules.

## Bridge unavailable or plugin not installed

Preserve `<run-dir>`, `manual_retry.csv`, `zotero_fallback.csv`, PDFs, queue jobs,
and prior result files. Do not fall back to direct Zotero MCP writes, custom
Zotero scripts, repeated imports or SQLite edits. Keep the batch recoverable and
report `zotero_unavailable`; do not report completion.

If a recovery report must be finalized without the plugin, build the complete
five-column row set in memory, validate all current task IDs, and write only
the unavailable failure rows using Python standard-library `csv.writer`,
open mode `x`, `newline=""`, `encoding="utf-8-sig"`. Never truncate, overwrite,
append, or partially publish an earlier result. Prefer `zotero_results.csv`
only if absent; otherwise use an exclusive retry filename. Then run:

```powershell
.\.venv\Scripts\python.exe paper_batch.py finalize --run-dir "<run-dir>" --zotero-results "<selected-recovery.csv>"
```

When Zotero becomes available, continue the original bridge for unresolved rows.
Never replace immutable evidence or delete the bridge manifest to force another
route. `resume` remains limited to batches explicitly started with
`--enable-manual-retry`; run exactly one `paper_batch.py resume --run-dir` only
when `manual_retry.csv` has rows.
