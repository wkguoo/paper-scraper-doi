# Task 5 Report: Zotero Reconciliation and Final Reports

## Scope

Implemented only Task 5 in `paper_automation/batch_workflow.py` and `tests/test_batch_workflow.py`, with the required project change log. Task 6 CLI and Task 7 MCP were not implemented.

## Design decisions

1. `finalize_batch(run_dir, zotero_results)` validates the canonical run directory and the complete UTF-8-SIG Zotero CSV before changing state. Required headers are exact, repeated headers, empty IDs, duplicate IDs, and unknown IDs are rejected. A validation failure leaves `batch_state.json` unchanged.
2. Existing OA/institutional successes and `duplicate` rows are never overwritten. Other rows are saved after each Zotero result transition. Non-success Zotero rows keep their Zotero status/reason/source, clear `file`, and do not masquerade as successful downloads.
3. Zotero success requires a nonempty item ID plus a local non-symlink regular file passing Task 2 PDF validation. The attachment is copied through `copy_pdf_safely()` into the batch `pdfs/` directory; it is never moved, deleted, or modified. Same-content PDFs reuse an existing safe batch copy.
4. `metadata_uncertain` remains auditable after a successful attachment copy: the status records the usable Zotero PDF, while `reason` keeps the `metadata_uncertain` marker and prior uncertainty detail. This deliberately does not claim Zotero attachment success confirms DOI/title metadata.
5. `write_final_reports()` is safe for start/resume before any Zotero export exists. It emits stable UTF-8-SIG CSV reports, a write-only XLSX manifest with every string forced to text, and an atomic temp-then-replace write for every report artifact. Duplicate terminal rows are excluded from `failed.csv` and explicitly counted in the summary.

## TDD record

- RED: `BatchFinalizeTests` was added first. The first focused run failed because `finalize_batch` and `FINAL_MANIFEST_FIELDS` did not exist, while the pre-existing minimal report writer did not create `failed.csv`.
- GREEN: Added strict reconciliation, local attachment validation/copying, `ZOTERO_RESULT_FIELDS`, `ZOTERO_SUCCESS`, `FINAL_MANIFEST_FIELDS`, and final report writers.
- Coverage: successful reconciliation; existing project success protection; invalid CSV headers/IDs with unchanged state; URL/symlink/HTML/missing/directory attachment rejection; source hash preservation; same-attachment reuse; metadata uncertainty audit; non-success/missing/empty Zotero results; CSV/XLSX ordering; XLSX formula-text safety; failure summary; and diagnostic report-write errors.

## Verification

Executed from the isolated worktree with `TEMP` and `TMP` set to `.codex-test-tmp`:

```powershell
..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchFinalizeTests -v
..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchRunTests -v
..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
..\..\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation
git diff --check
```

Results: `BatchFinalizeTests` 7 passed; `BatchRunTests` 38 passed; full offline suite 251 passed with 2 expected skips; compile and diff checks exited 0.

No network calls, institutional login, Cookie read, live Zotero access, attachment mutation, source input mutation, or packaging command was performed.
