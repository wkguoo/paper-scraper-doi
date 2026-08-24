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
- No PDF is downloaded.
- No `supplement_download_report.csv` or `supplements\` directory is created during preflight.

## 2. ScienceDirect DOI/PII Dry Run

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "10.1016/j.actamat.2016.08.081" --out results --run-name manual_sd_dry_run --dry-run
```

Expected:

- `doi_intake_preview.csv`, `merged_doi_input.csv`, `doi_batch_resolved.xlsx` or a clear failure report are written.
- `pdf_download_report.csv` marks PDF rows as `not_requested`.
- `--dry-run` is treated as ScienceDirect DOI metadata/PII resolution without PDF download, not as the first-pass workflow for messy beginner input.
- No browser login window is required.

## 3. Windows UI Local Preflight

Open `start_paper_scraper_ui.bat`, paste a messy AI ScienceDirect recommendation list, and use the `运行前体检（本地）` panel before starting the download.

Expected:

- The UI shows recognized DOI rows and rows needing review before a formal run.
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

## 5. Elsevier API-First Smoke Test (Unified Entry)

Use only `paper_batch.py start`. Never paste credential values into this file,
chat, command output, CSV/XLSX input, or Git. Before testing, verify only whether
the two process variables are present:

```powershell
[pscustomobject]@{
    ELSEVIER_API_KEY_Set   = [bool]$env:ELSEVIER_API_KEY
    ELSEVIER_INSTTOKEN_Set = [bool]$env:ELSEVIER_INSTTOKEN
}
```

Create three isolated, fixed batches under `results\elsevier_api_smoke_test\`:

1. Open a PowerShell process that has `ELSEVIER_API_KEY` but no
   `ELSEVIER_INSTTOKEN`, then run:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py start --text "10.1016/j.actamat.2016.08.081" --out "results\elsevier_api_smoke_test" --run-name "api_key_only" --no-auto-zotero
   ```

2. In a process with both variables present, run:

   ```powershell
   .\.venv\Scripts\python.exe paper_batch.py start --text "10.1016/j.actamat.2016.08.081" --out "results\elsevier_api_smoke_test" --run-name "api_key_insttoken" --no-auto-zotero
   ```

3. With a known DOI that the institution cannot access, run the complete
   API retry → browser → limited OA → Zotero-eligibility chain. Keep Zotero open if actual
   automatic fallback is part of the check; otherwise add `--no-auto-zotero`
   and verify `zotero_fallback.csv` was produced.

   ```powershell
   $noEntitlementDoi = Read-Host "Known no-entitlement DOI"
   .\.venv\Scripts\python.exe paper_batch.py start --text $noEntitlementDoi --out "results\elsevier_api_smoke_test" --run-name "no_entitlement"
   ```

   If the user has neither a known no-entitlement DOI nor a non-institutional
   network, do not alter networking, invent a bad token, or keep probing random
   papers. Record the live 403 check as user-waived and run the offline routing
   acceptance instead:

   ```powershell
   .\.venv\Scripts\python.exe -m unittest tests.test_elsevier_api -v
   ```

   This verifies 403 → `not_entitled` → browser routing and report isolation,
   but it is not evidence that the publisher returned a real 403. Retain one
   real non-success API smoke result, when available, as separate evidence that
   the browser/Zotero fallback path is operational.

Expected for each batch:

- Inspect `reports\sciencedirect\elsevier_api_attempts.csv`; it contains no
  response body, full request headers, API Key, Institution Token, or Cookie.
- A successful API row has `status=success`, a valid final-named PDF under the
  ScienceDirect stage `pdfs\`, and `browser_fallback=False`.
- Transient `network_error`, `rate_limited`, and `invalid_pdf` results use at
  most three API calls with 5-second and 15-second waits before fallback;
  `request_attempts` records the actual count.
- API-only success does not launch a browser or read browser cookies.
- 403 is `not_entitled`, is never reported as PDF success, and proceeds to the
  existing fallback ladder.
- Unified delivery publishes valid files under `结果\pdf\` and supplements
  under `结果\补充材料\<article-stem>\` without changing the input.
- Record only sanitised fields in `smoke_summary.csv`: authentication mode
  booleans, HTTP status, FULL XML boolean, main EID boolean, PDF size/validity,
  supplement count, browser fallback boolean, and final report status.
- If the example DOI fails in both authentication modes, do not mark real API
  acceptance complete; repeat with a user-provided DOI known to be entitled.
- When the real 403 check is user-waived, record it as `waived_environment_unavailable`
  rather than `passed`; do not report the simulated 403 as a live entitlement result.

## 6. ScienceDirect PDF With Entitlement

Use one DOI that the user's institution can access.

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --text "<entitled ScienceDirect DOI>" --out results --run-name manual_sd_entitled --login-wait-seconds 600 --no-auto-zotero
```

Expected:

- Elsevier API is tried first. Retryable API errors exhaust the bounded retry
  budget before a browser opens; terminal API failures may fall back immediately.
- The user completes institutional login in the browser; no password is pasted into Codex or the terminal.
- `pdf_download_report.csv` records `success` and the PDF exists under `pdfs\`.
- `results\_auth\sciencedirect_cookies.json` may be created and must stay local.

## 7. ScienceDirect PDF And Supplementary Materials

Use one entitled ScienceDirect DOI whose article page shows supplementary files under "Extras" or an Appendix section.

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --text "<entitled ScienceDirect DOI with supplementary files>" --out results --run-name manual_sd_supplements --login-wait-seconds 600 --no-auto-zotero
```

Expected:

- `pdf_download_report.csv` records the article PDF result.
- `supplement_download_report.csv` is written.
- Supplementary files, when found and downloadable, are saved under `supplements\<article-stem>\`.
- Supplement rows are linked to the article through DOI, PII, `article_file`, and `article_title`.
- If no supplementary files are detected, the report records `not_found` rather than creating placeholder files.

Disable supplement downloading for comparison:

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --text "<entitled ScienceDirect DOI with supplementary files>" --out results --run-name manual_sd_no_supplements --no-download-supplements --no-auto-zotero
```

Expected:

- PDF behavior is unchanged.
- No `supplement_download_report.csv` is generated for the disabled run.
- No `supplements\` directory is required for the disabled run.

## 8. ScienceDirect No Entitlement Or Non-ScienceDirect DOI

Use one DOI that is not available through the institution or is not an Elsevier/ScienceDirect DOI.

Expected:

- The run writes `doi_batch_failed.csv` or a failed row in `pdf_download_report.csv`.
- The tool does not create a fake PDF success row.
- The final summary points to the failed report.
- `elsevier_api_attempts.csv` records `not_entitled` (403) or another safe API
  reason, while `pdf_download_report.csv` keeps the browser failure reason that
  drives limited OA and Zotero fallback.

## 9. CAPTCHA, 403, Or Rate Limit

Trigger only with a small batch after confirming normal single-paper access.

Expected:

- CAPTCHA prompts ask the user to complete verification in the browser.
- 403/rate-limit handling waits or records a failure; it does not repeatedly hammer ScienceDirect.
- An API 401 opens the API circuit immediately. A 429 first uses the bounded
  API retry budget; if it persists, the circuit opens for the remaining batch
  rows, which then go directly to browser handling rather than consuming more
  API quota.
- The user can inspect `pdf_download_report.csv` before retrying.


## 11. Unified Batch With Zotero Fallback

Do not perform these checks in the default unittest suite. They require an
explicitly approved XPI and the isolated profile `elpj7iql.Zotero test`. Do not
install the extension in `g39b695l.default`, do not copy files directly into a
profile, and do not exercise the user's main library.

Before starting, record the XPI version, Zotero version, test library ID, date,
and test collection. For every case record job ID, result status, output paths,
and error code without credentials.

1. **Idle:** with no queue job, start Zotero test and verify the Tools menu
   contains “文献下载桥接”; “查看最近状态” reports idle without an error.
2. **Complete-chunk barrier and one confirmation:** queue only chunk 1 of a
   two-chunk run and verify zero prompts/writes. Add chunk 2 and verify exactly
   one native confirmation for the shared `run_id`.
3. **Cancel means zero writes:** cancel that confirmation; verify one
   `user_cancelled` row per task, durable cancellation replay after restart,
   and zero collection/item/attachment writes.
4. **Existing PDF:** use an existing item with a valid local PDF. Verify
   `existing_pdf`, no available-PDF call, and unchanged source attachment hash.
5. **Existing item without PDF:** verify one collection assignment and at most
   one available-PDF call, returning `downloaded` or `no_pdf`.
6. **Missing DOI:** verify one identifier import into the preserved temporary
   collection with translator attachments disabled. Replay must not import,
   assign, or request the PDF twice.
7. **Crash/restart:** interrupt a three-item confirmed run after item 1. Restart
   Zotero test and verify no second confirmation and no duplicate Zotero write.
   Inspect the retained progress: a completed ownership checkpoint may resume,
   but an unresolved write intent must become `write_outcome_uncertain` without
   being claimed or retried. Also interrupt an approved undo and
   verify it resumes without a second undo prompt or touching preexisting IDs;
   an action left in an uncertain pending state must be reported as skipped and
   must not be replayed after restart.
8. **Project finalization and idempotency:** rerun
   `paper_batch.py zotero --run-dir "<run-dir>"`; verify strict JSON consumption,
   final PDFs under `pdfs\`, reports under `reports\`, unchanged source PDF
   hashes, and no changed state/PDF copies on a repeated command.

After all eight cases pass, present the evidence and ask separately before any
main-profile installation. Do not automatically package the Windows project.

## Cleanup

Run after institutional-access tests if this machine should not keep cached browser state:

```powershell
Remove-Item -Recurse -Force (Join-Path $env:TEMP "chrome_dbg_profile")
Remove-Item -Force ".\results\_auth\sciencedirect_cookies.json"
```
