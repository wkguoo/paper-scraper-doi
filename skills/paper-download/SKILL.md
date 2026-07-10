---
name: paper-download
description: Use when Codex needs ScienceDirect, institutional, or open-access paper downloads from DOI/title lists, including a project-first batch that may require a connected Zotero fallback.
---

# Paper Download

Use this as the single entry point for a mixed DOI/title paper list. The project
workflow always runs first. Zotero is a fallback only for rows that remain in
the project's `zotero_fallback.csv`; it is not a second downloader for the
whole input list.

## Repository and prerequisites

Locate the repository in this order:

1. Current directory or a parent containing `paper_batch.py`,
   `sd_institutional_skill.py`, `paper_skill.py`, and `paper_automation`.
2. `$env:PAPER_SCRAPER_DOI_ROOT` when it points to that repository.
3. A packaged folder containing the same scripts.
4. If none exist, ask the user for the repository path.

Use `.venv\Scripts\python.exe` when it exists. The full fallback protocol
requires Zotero to be open and its Codex connection available. Do not start a
real download, read cookies, request a password, or attempt to handle a CAPTCHA
without the user's explicit request and interaction.

## Batch protocol

Run the following sequence in this order. Keep the CLI's printed run directory
as `<run-dir>` and do not edit the user's original input file.

1. Start the project workflow first:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results"
   ```

2. Inspect `<run-dir>\working\manual_retry.csv`. If it has data rows, pause
   once for the user to finish the required browser action. After the user says
   it is ready, run exactly one retry:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py resume --run-dir "<run-dir>"
   ```

   Do not retry a second time. If `manual_retry.csv` has no data rows, do not
   run `paper_batch.py resume` for this step.

3. Read `<run-dir>\working\zotero_fallback.csv` after the one permitted
   retry. If it has no data rows, create
   `<run-dir>\working\zotero_results.csv` with only this header, preserving
   any existing file and never adding data rows:

   ```text
   task_id,zotero_item_id,attachment_path,status,reason
   ```

   Then run `paper_batch.py finalize` with that header-only file and report the
   final `pdfs\` directory:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py finalize --run-dir "<run-dir>" --zotero-results "<run-dir>\working\zotero_results.csv"
   ```

4. When `zotero_fallback.csv` has data rows, check the connection before any
   Zotero write with `library_search(entity:"libraries", mode:"list")`.
   If this call cannot list a usable library, write one result row for every
   fallback `task_id` with status `zotero_unavailable`, an empty item/path, and
   a concise connection reason. Keep the batch resumable, run
   `paper_batch.py finalize` to publish the unresolved report, and do not
   describe the batch as complete.

5. When a library is available, create one temporary collection named
   `Codex下载回退_YYYYMMDD_HHMMSS`. Keep this collection and every item in it
   after reconciliation; never delete either as cleanup.

6. Resolve the entire fallback list before importing anything:

   - Search every DOI with `library_search` first. Add already-existing item
     IDs to the temporary collection in one batch with
     `library_update(kind:"collections")`.
   - Gather only DOI values with no existing item, de-duplicate them, then
     import that batch once with `library_import(kind:"identifiers")` into the
     temporary collection. Do not import a DOI that was already found.
   - For a row without a DOI, accept an existing match only when its normalized
     title is exactly the same and either the year or the first author also
     matches. Otherwise write `metadata_uncertain` for that task, with no
     import and no guessed item ID.

   Confirm Zotero writes by batch (collection creation, batch membership,
   identifier import, and later tags), never one confirmation per paper.

7. Detect existing PDF attachments for all resolved items. For an item that
   already has a valid PDF, record `existing_pdf` and do not ask Zotero to
   search again. For all remaining item IDs, issue one
   `zotero_script(mode:"write")` operation, one time for the batch, using the
   compatibility guard and undo operation below. This is the only available-PDF
   request for each item in the batch.

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

   If the compatibility guard returns `zotero_api_unavailable`, write that
   status for every unresolved item in this Zotero batch, with an empty
   `attachment_path`; do not claim a PDF was downloaded.

8. Write `<run-dir>\working\zotero_results.csv` with exactly these five fields
   in this order and no others:

   ```text
   task_id,zotero_item_id,attachment_path,status,reason
   ```

   The only statuses are `existing_pdf`, `downloaded`, `metadata_uncertain`,
   `zotero_unavailable`, `zotero_api_unavailable`, and `no_pdf`. A non-empty
   `attachment_path` must be an absolute Windows path to an existing ordinary
   PDF file. Reject a relative path, directory, reparse point, or non-PDF file;
   record `no_pdf` with the rejection reason instead. Do not move, rename,
   delete, or modify a Zotero attachment.

9. Batch-apply the `codex-download-success` tag to items with `existing_pdf` or
   `downloaded`, and `codex-download-failed` to items with `metadata_uncertain`,
   `zotero_unavailable`, `zotero_api_unavailable`, or `no_pdf`. Preserve the
   temporary collection and its items.

10. Finalize exactly once after `zotero_results.csv` is ready:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py finalize --run-dir "<run-dir>" --zotero-results "<run-dir>\working\zotero_results.csv"
   ```

   `finalize` validates and non-destructively copies accepted PDFs into
   `<run-dir>\pdfs\`. It must not overwrite an existing output: filename
   conflicts are handled by the project's reconcile rules. Report the final
   `pdfs\` directory and unresolved reasons separately.

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
    └── zotero_results.csv
```

`pdfs\` is the final non-destructive copy destination. `working\` holds the
resumable handoff files, and `reports\` is the audit trail.

## ScienceDirect and open-access routes

For a ScienceDirect or Elsevier request that does not need the unified batch,
use `sd_institutional_skill.py`. For noisy beginner lists, start with
`--beginner --preflight`; formal PDF runs may produce
`supplement_download_report.csv` and `supplements\`. Add
`--no-download-supplements` only when the user explicitly wants PDFs without
supplementary files.

For open-access candidate assistance without institutional access, use
`paper_skill.py` and report unresolved rows honestly. Do not broaden the source
set beyond the project's documented routes.

## Safety

- Do not expose cookie values, passwords, session data, or credential files.
- Do not automatically solve or bypass a CAPTCHA; pause only for the one
  user-handled retry described above.
- Do not overwrite original inputs, existing PDFs, Zotero attachments, or an
  existing `zotero_results.csv`.
- Never report an unavailable Zotero fallback as a completed download batch.
