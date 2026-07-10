# Manual QA Checklist

Use this checklist for checks that require network access, browser interaction, institutional entitlement, or CAPTCHA handling. Do not put these scenarios in the default unittest suite.

## 1. ScienceDirect Beginner Preflight

Use a messy AI-recommended ScienceDirect list with at least one DOI row, one title-only row, and one unclear/noise row.

```powershell
$papers = @'
A critical review of high entropy alloys and related concepts
DOI: 10.1016/j.actamat.2016.08.081
unclear recommendation without enough bibliographic information
'@
.\.venv\Scripts\python.exe sd_institutional_skill.py --text $papers --out results --run-name manual_sd_preflight --beginner --preflight --auto-web-search
```

Expected:

- `doi_intake_preview.csv` is written with `valid`, `needs_review`, `duplicate`, `invalid`, or `empty` rows as appropriate.
- `run_summary.txt` points to rows that need manual DOI/citation review.
- `00_给研究生查看\README_先看我.txt`, `paper_index.csv`, `paper_index.xlsx`, and `失败项_下一步处理.csv` are written.
- No PDF is downloaded.
- No `supplement_download_report.csv` or `supplements\` directory is created during preflight.

## 2. ScienceDirect DOI/PII Dry Run

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "10.1016/j.actamat.2016.08.081" --out results --run-name manual_sd_dry_run --dry-run
```

Expected:

- `doi_intake_preview.csv`, `merged_doi_input.csv`, `doi_batch_resolved.xlsx` or a clear failure report are written.
- `pdf_download_report.csv` marks PDF rows as `not_requested`.
- `00_给研究生查看\paper_index.csv` and `library_index.csv` are written and point to no fake PDF paths.
- `--dry-run` is treated as ScienceDirect DOI metadata/PII resolution without PDF download, not as the first-pass workflow for messy beginner input.
- No browser login window is required.

## 3. Windows UI Local Preflight

Open `start_paper_scraper_ui.bat`, paste a messy AI ScienceDirect recommendation list, and use the `运行前体检（本地）` panel before starting the download.

Expected:

- The UI shows recognized DOI rows and rows needing review before a formal run.
- The `生成新手预检报告` action writes `00_给研究生查看\` and the result area can open it.
- `使用预检合并表` fills `merged_doi_input.csv` back into the DOI input for the formal run.
- No ScienceDirect login window is opened by this local preflight.
- No PDF files, `supplement_download_report.csv`, or `supplements\` directory are created by the local preflight itself.
- The user can proceed to a formal run only after checking or correcting the preview.

## 4. Legal OA Dry Run

```powershell
.\.venv\Scripts\python.exe paper_skill.py --text "DOI: 10.1038/s41586-024-07000-1" --out results\manual_oa_dry_run --email "you@example.com" --dry-run
```

Expected:

- `metadata/manifest.csv` and `metadata/manifest.json` are written.
- Download status is `dry_run` when a legal OA PDF candidate is found, or a clear unresolved reason is recorded.
- No institutional cookie or browser profile is used.

## 5. ScienceDirect PDF With Entitlement

Use one DOI that the user's institution can access.

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<entitled ScienceDirect DOI>" --out results --run-name manual_sd_entitled --login-wait-seconds 600
```

Expected:

- If the cached cookie is insufficient, an Edge/Chrome debug window opens.
- The user completes institutional login in the browser; no password is pasted into Codex or the terminal.
- `pdf_download_report.csv` records `success` and the PDF exists under `pdfs\`.
- `00_给研究生查看\paper_index.xlsx` links to the downloaded PDF by relative path and does not duplicate the PDF.
- `results\_auth\sciencedirect_cookies.json` may be created and must stay local.

## 6. ScienceDirect PDF And Supplementary Materials

Use one entitled ScienceDirect DOI whose article page shows supplementary files under "Extras" or an Appendix section.

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<entitled ScienceDirect DOI with supplementary files>" --out results --run-name manual_sd_supplements --login-wait-seconds 600
```

Expected:

- `pdf_download_report.csv` records the article PDF result.
- `supplement_download_report.csv` is written.
- Supplementary files, when found and downloadable, are saved under `supplements\<article-stem>\`.
- Supplement rows are linked to the article through DOI, PII, `article_file`, and `article_title`.
- `00_给研究生查看\paper_index.csv/xlsx` summarizes supplement status and relative supplement paths.
- If no supplementary files are detected, the report records `not_found` rather than creating placeholder files.

Disable supplement downloading for comparison:

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<entitled ScienceDirect DOI with supplementary files>" --out results --run-name manual_sd_no_supplements --no-download-supplements
```

Expected:

- PDF behavior is unchanged.
- No `supplement_download_report.csv` is generated for the disabled run.
- No `supplements\` directory is required for the disabled run.

## 7. ScienceDirect No Entitlement Or Non-ScienceDirect DOI

Use one DOI that is not available through the institution or is not an Elsevier/ScienceDirect DOI.

Expected:

- The run writes `doi_batch_failed.csv` or a failed row in `pdf_download_report.csv`.
- `00_给研究生查看\失败项_下一步处理.csv` classifies the row, for example as `非 ScienceDirect`, `无机构权限`, `验证码或限速`, or `可重试 PDF 失败`.
- The tool does not create a fake PDF success row.
- The final summary points to the failed report.

## 8. CAPTCHA, 403, Or Rate Limit

Trigger only with a small batch after confirming normal single-paper access.

Expected:

- CAPTCHA prompts ask the user to complete verification in the browser.
- 403/rate-limit handling waits or records a failure; it does not repeatedly hammer ScienceDirect.
- The user can inspect `pdf_download_report.csv` before retrying.

## 9. Windows Package Verification

```powershell
.\make_windows_ui_package.bat
```

Expected:

- The script exits successfully and creates `dist\paper-scraper-ui-windows`.
- The package contains `sd_supplements.py`.
- The package contains `student_handoff.py`.
- The package contains `skills\sciencedirect-doi-download\references\beginner-workflow.md`.
- The package contains `skills\sciencedirect-doi-download\references\failure-reasons.md`.
- `docs\sciencedirect_skill_beginner_guide.md`, `README.md`, `README_zh.md`, `WINDOWS_UI_README.md`, and `MANUAL_QA.md` are included.

## 10. Unified Batch With Zotero Fallback

Do not perform these seven checks as part of the default unittest suite. They
require a deliberately prepared local Zotero library and, where applicable,
the user's own authorized access. Do not use this checklist to test network,
browser, or GUI behavior automatically.

1. **Project-only success:** use rows resolved by the project workflow; verify
   `zotero_results.csv` has only the required header and `finalize` reports the
   final `pdfs\` directory.
2. **One manual retry:** prepare one row in `manual_retry.csv`; verify that the
   user action is requested once and `resume` is run once, not repeatedly.
3. **Existing Zotero item and PDF:** use a fallback DOI already in Zotero with
   a valid attachment; verify a preserved temporary collection, status
   `existing_pdf`, and one non-destructive final copy.
4. **Zotero available-PDF request:** use a fallback item without an attachment;
   verify a single batch available-PDF request and status `downloaded` or
   `no_pdf`, never a per-paper confirmation loop.
5. **Uncertain title:** use a no-DOI row whose normalized title does not also
   agree on year or first author; verify `metadata_uncertain` and no import.
6. **Unavailable Zotero is resumable:** close or disconnect Zotero before the
   fallback stage; verify every fallback row is `zotero_unavailable`, reports
   remain recoverable, and the batch is not described as complete.
7. **No overwrite and idempotency:** prepare same-name PDFs and rerun the same
   batch; verify final copies are not overwritten, duplicates are reconciled,
   and existing Zotero items are not imported again.
8. **Write-confirmation UI is unavailable:** begin from desktop Codex with a
   readable personal library, then let the first
   `collection_update(action:"create", ...)` return `Zotero MCP confirmation UI
   is unavailable for this Codex turn. Start a new Codex turn from Zotero and
   try again.` Verify that the failed attempt performs zero Zotero writes after
   the error, does not substitute `zotero_script` for collection/import/tag
   confirmation, and prompts once to start a Zotero-panel turn saying
   `继续该批次`. Confirm the new turn restarts from library check and collection
   creation while retaining the run directory and `zotero_fallback.csv`, without
   rerunning project downloads or a second `resume`. If that new turn is still
   not writable, verify `zotero_unavailable` result rows and a recoverable,
   unfinished batch.

## Cleanup

Run after institutional-access tests if this machine should not keep cached browser state:

```powershell
Remove-Item -Recurse -Force (Join-Path $env:TEMP "chrome_dbg_profile")
Remove-Item -Force ".\results\_auth\sciencedirect_cookies.json"
```
