---
name: sciencedirect-doi-download
description: Download ScienceDirect PDFs through the user's institutional access from pasted DOI text, AI-recommended paper lists, title-only literature text, DOI tables, or folders of literature files. Use when the user asks Codex to fetch/download ScienceDirect or Elsevier papers, process DOI batches, resolve copied paper recommendations into DOI/PDF downloads, or use local Chrome/Edge institutional login rather than the Tkinter UI.
---

# ScienceDirect DOI Download

Use the repository CLI instead of the Tkinter UI. Keep the legal OA `paper_skill.py` workflow separate; this skill is specifically for ScienceDirect institutional access on the user's local machine.

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
4. Let the script resolve mixed text first: DOI rows are normalized directly; title-only rows are resolved through public metadata and low-confidence matches go to review instead of download.
5. Let the script manage Chrome/Edge login. If institutional access is missing, it opens a debug browser window and polls until the user finishes login.
6. Report the output directory, recognized/needs-review counts, PDF success/failure/skip counts, `doi_intake_preview.csv`, `pdf_download_report.csv`, `doi_batch_failed.csv`, and `run_summary.txt`.

## Commands

For pasted DOI text:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "10.1016/j.actamat.2024.119999" --out results
```

For pasted AI paper recommendations:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<copied AI paper list with DOI or titles>" --out results
```

For a file:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\Papers\papers.xlsx" --out results
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

Use `--dry-run` or `--no-download-pdfs` only when the user asks to preview/resolve without downloading.

## Troubleshooting

- If Chrome/Edge is not installed in a standard location, the script checks Playwright Chromium as a fallback.
- To force a specific browser executable for the login window, set:

```powershell
$env:PAPER_SCRAPER_BROWSER_EXE = "D:\Path\To\chrome.exe"
```

- If ScienceDirect shows CAPTCHA, wait for the user to complete it in the opened browser, then continue polling instead of restarting the job repeatedly.
- If Chinese text in `run_summary.txt` looks garbled in PowerShell, inspect the CSV/XLSX reports or open the file in an editor with UTF-8 support.

## Safety

- Do not print, paste, summarize, or expose cookie values.
- Do not ask the user for passwords; the browser window is the only login surface.
- Do not use Sci-Hub, LibGen, or paywall-bypass sources.
- Treat `results/_auth/sciencedirect_cookies.json` as a local credential cache and never commit it.
- Treat the temporary debug browser profile as local credential state. The default workflow copies only a minimal browser profile subset, but the profile still must not be shared.
- Treat `needs_review` rows as unresolved; do not manually force them into download unless the user confirms the DOI.
- If downloads fail, inspect reports first; do not repeatedly hammer ScienceDirect.

To clear local institutional-access state after testing:

```powershell
Remove-Item -Recurse -Force (Join-Path $env:TEMP "chrome_dbg_profile")
Remove-Item -Force ".\results\_auth\sciencedirect_cookies.json"
```
