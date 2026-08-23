---
name: sciencedirect-doi-download
description: Internal ScienceDirect institutional DOI adapter used by the unified paper-download workflow. Do not invoke this skill as a standalone user entry; use paper-download for ScienceDirect or Elsevier PDF requests, DOI batches, title lists, and authorized access.
---

# ScienceDirect DOI Download

> Internal compatibility reference. New user requests must use the unified
> `paper-download` workflow and `paper_batch.py`; do not invoke this skill as a
> standalone entry.

The unified workflow should try the Codex in-app browser first. If it is not
available or cannot provide a usable session, the external browser fallback
uses Chrome first, then Edge channels, then Playwright Chromium; explicit
`--browser-exe` and `PAPER_SCRAPER_BROWSER_EXE` overrides remain authoritative.

Use the repository CLI instead of the Tkinter UI. Keep the OA resource assistance `paper_skill.py` workflow separate; this skill is specifically for ScienceDirect institutional access on the user's local machine.

Default to a two-stage beginner-safe workflow for noisy pasted lists: preflight first, then download only confirmed DOI rows. Read `references/beginner-workflow.md` when the user is new, asks "how to use", gives an AI-recommended list, or provides title-only/short citation text. Read `references/failure-reasons.md` when explaining reports or failures.

For student-facing beginner instructions, refer to `docs/sciencedirect_skill_beginner_guide.md` in the repository when the user asks how to use this skill.

## Workflow

1. Locate the scraper repository in this order:
   - Current directory or parent containing `sd_institutional_skill.py` and `skills/sciencedirect-doi-download/SKILL.md`.
   - `$env:PAPER_SCRAPER_DOI_ROOT` when it points to that repository.
   - A packaged folder containing `sd_institutional_skill.py`.
   - `E:\desktop\paper-scraper-doi` as the local fallback.
   - If none exist, ask the user for the repository path.
2. Use `.venv\Scripts\python.exe` when it exists; otherwise create the venv and install `requirements.txt`.
3. Run `sd_institutional_skill.py` with one or more inputs:
   - `--text "<pasted DOI or literature text>"`
   - `--input "<file>"`
   - `--folder "<folder>"`
4. Let the script normalize mixed text first: DOI rows are recognized directly; title-only rows stay in review unless the user explicitly enables title-only resolution for a formal run.
5. For noisy or beginner input, run `--beginner --preflight` first. Preflight is local intake review only; use `--resolve-title-only --auto-web-search` later only when the user explicitly wants title-only or short citation rows resolved by public metadata search.
6. Inspect `doi_intake_preview.csv`. Treat `needs_review` rows as unresolved; do not invent DOI values.
7. For direct download requests with clear DOI rows, run without `--beginner`/`--preflight`.
8. Let the script manage Chrome-first browser login. If institutional access is missing, it opens a debug browser window and polls until the user finishes login. Default browser order on Windows is Google Chrome, Edge Stable/Beta/Dev/Canary, then Playwright Chromium.
9. When PDF downloading is active, supplementary materials are downloaded by default into `supplements\`; add `--no-download-supplements` only when the user explicitly asks to skip them.
10. Report preflight outputs separately from formal download outputs. For preflight, report the output directory, recognized/needs-review counts, `doi_intake_preview.csv`, `merged_doi_input.csv`, `doi_batch_failed.csv`, `run_summary.txt`, and `run_summary.json`. For formal downloads, also report PDF success/failure/skip counts, `pdf_download_report.csv`, and `pdfs\`. Report supplement success/failure/skipped/not-found counts, `supplement_download_report.csv`, and `supplements\` only when PDF download and supplement download are both active.

## Commands

For pasted DOI text:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "10.1016/j.actamat.2024.119999" --out results
```

For pasted AI paper recommendations:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<copied AI paper list with DOI or titles>" --out results --beginner --preflight
```

After reviewing `doi_intake_preview.csv`, run confirmed rows without preflight:

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<confirmed DOI or paper list>" --out results
```

For a file:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\Papers\papers.xlsx" --out results
```

To use an explicit Cookie Editor export:

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\Papers\papers.xlsx" --out results --cookies "D:\Papers\cookies.json"
```

For a folder:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe sd_institutional_skill.py --folder "D:\PapersToDownload" --out results
```

To choose the save folder interactively on Windows:

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<paper list>" --choose-out
```

Use `--beginner --preflight` for first-pass recognition reports. Use `--dry-run` or `--no-download-pdfs` only when the user explicitly wants ScienceDirect DOI metadata/PII resolution without PDF download.

To download PDFs but skip supplementary files:

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\Papers\papers.xlsx" --out results --no-download-supplements
```

To force a specific browser executable:

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<paper list>" --out results --browser-exe "C:\Program Files (x86)\Microsoft\Edge Beta\Application\msedge.exe"
```

## Troubleshooting

- If Edge/Chrome is not installed in a standard location, the script checks Playwright Chromium as a fallback.
- To force a specific browser executable for the login window, prefer `--browser-exe`; the environment variable remains supported:

```powershell
$env:PAPER_SCRAPER_BROWSER_EXE = "D:\Path\To\msedge.exe"
```

- If ScienceDirect shows CAPTCHA, wait for the user to complete it in the opened browser, then continue polling instead of restarting the job repeatedly.
- If institutional access still fails, inspect `pdf_download_report.csv` and `run_summary.json`. The tool will automatically fall back to third-party data sources for failed PDFs.
- If Chinese text in `run_summary.txt` looks garbled in PowerShell, inspect the CSV/XLSX reports or open the file in an editor with UTF-8 support.
- If `review_hint` says to补 DOI or完整引用, report that row as unresolved and ask for DOI/title/journal/year/volume/pages before retrying.
- If supplement status is `not_found`, explain that no detectable supplement links were exposed on the article page; do not count it as a PDF failure.

## Safety

- Do not print, paste, summarize, or expose cookie values.
- Do not ask the user for passwords; the browser window is the only login surface.
- Treat `results/_auth/sciencedirect_cookies.json` as a local credential cache and never commit it.
- Treat `results/_auth/sciencedirect_cookies.json` as a local credential cache and never commit it.
- Treat the temporary debug browser profile as local credential state. The default workflow copies only a minimal browser profile subset, but the profile still must not be shared.
- Treat `needs_review` rows as unresolved; do not manually force them into download unless the user confirms the DOI.
- If downloads fail, inspect reports first; do not repeatedly hammer ScienceDirect.

To clear local institutional-access state after testing:

```powershell
Remove-Item -Recurse -Force (Join-Path $env:TEMP "chrome_dbg_profile")
Remove-Item -Force ".\results\_auth\sciencedirect_cookies.json"
```
