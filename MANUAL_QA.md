# Manual QA Checklist

Use this checklist for checks that require network access, browser interaction, institutional entitlement, or CAPTCHA handling. Do not put these scenarios in the default unittest suite.

## 1. ScienceDirect DOI Dry Run

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "10.1016/j.actamat.2016.08.081" --out results --run-name manual_sd_dry_run --dry-run
```

Expected:

- `doi_intake_preview.csv`, `merged_doi_input.csv`, `doi_batch_resolved.xlsx` or a clear failure report are written.
- `pdf_download_report.csv` marks PDF rows as `not_requested`.
- No browser login window is required.

## 2. Legal OA Dry Run

```powershell
.\.venv\Scripts\python.exe paper_skill.py --text "DOI: 10.1038/s41586-024-07000-1" --out results\manual_oa_dry_run --email "you@example.com" --dry-run
```

Expected:

- `metadata/manifest.csv` and `metadata/manifest.json` are written.
- Download status is `dry_run` when a legal OA PDF candidate is found, or a clear unresolved reason is recorded.
- No institutional cookie or browser profile is used.

## 3. ScienceDirect PDF With Entitlement

Use one DOI that the user's institution can access.

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<entitled ScienceDirect DOI>" --out results --run-name manual_sd_entitled --login-wait-seconds 600
```

Expected:

- If the cached cookie is insufficient, a Chrome/Edge debug window opens.
- The user completes institutional login in the browser; no password is pasted into Codex or the terminal.
- `pdf_download_report.csv` records `success` and the PDF exists under `pdfs\`.
- `results\_auth\sciencedirect_cookies.json` may be created and must stay local.

## 4. ScienceDirect No Entitlement Or Non-ScienceDirect DOI

Use one DOI that is not available through the institution or is not an Elsevier/ScienceDirect DOI.

Expected:

- The run writes `doi_batch_failed.csv` or a failed row in `pdf_download_report.csv`.
- The tool does not create a fake PDF success row.
- The final summary points to the failed report.

## 5. CAPTCHA, 403, Or Rate Limit

Trigger only with a small batch after confirming normal single-paper access.

Expected:

- CAPTCHA prompts ask the user to complete verification in the browser.
- 403/rate-limit handling waits or records a failure; it does not repeatedly hammer ScienceDirect.
- The user can inspect `pdf_download_report.csv` before retrying.

## Cleanup

Run after institutional-access tests if this machine should not keep cached browser state:

```powershell
Remove-Item -Recurse -Force (Join-Path $env:TEMP "chrome_dbg_profile")
Remove-Item -Force ".\results\_auth\sciencedirect_cookies.json"
```
