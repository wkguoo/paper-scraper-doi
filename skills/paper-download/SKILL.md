---
name: paper-download
description: Route paper download requests to either ScienceDirect/Elsevier institutional-access downloads or legal open-access PDF downloads. Use when Codex needs to download papers, process DOI batches, resolve DOI/title lists, handle local literature files or folders, dry-run paper recognition, use institutional Chrome/Edge login and cookies for ScienceDirect, or find legal OA PDFs without institutional cookies, Sci-Hub, LibGen, or paywall bypasses.
---

# Paper Download

Use this as the single entry point for paper download tasks. Route to the repository CLI that matches the user's intent; keep the two workflows separate.

## Repository

Locate the repository in this order:

1. Current directory or parent containing `sd_institutional_skill.py`, `paper_skill.py`, and `paper_automation`.
2. `$env:PAPER_SCRAPER_DOI_ROOT` when it points to that repository.
3. A packaged folder containing both CLI scripts.
4. `E:\desktop\paper-scraper-doi` as the local fallback.
5. If none exist, ask the user for the repository path.

Use `.venv\Scripts\python.exe` when it exists; otherwise create the venv and install `requirements.txt`.

## Route

Use `sd_institutional_skill.py` for ScienceDirect institutional access when the user mentions ScienceDirect, Elsevier, institution/school access, cookies, Chrome/Edge login, DOI batch download, or when the input is clearly dominated by Elsevier DOI values such as `10.1016/...`.

Use `paper_skill.py` for legal open-access downloads when the user asks for OA/open-access PDFs, public-source PDFs, no login, no cookies, or mixed publisher lists where institutional access is not requested.

When intent is unclear, infer from wording and input. Ask only if the choice changes safety or expected access path.

## ScienceDirect Institutional Workflow

Run `sd_institutional_skill.py` with one or more inputs:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe sd_institutional_skill.py --input "D:\Papers\papers.xlsx" --out "D:\Literature\ScienceDirect"
```

Other input forms:

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<DOI or paper list>" --out results
.\.venv\Scripts\python.exe sd_institutional_skill.py --folder "D:\PapersToDownload" --out results
```

Use `--dry-run` when the user asks to preview/resolve without downloading. Use `--resolve-title-only` only when the user explicitly wants file rows without DOI to be resolved by title.

Report `doi_intake_preview.csv`, `merged_doi_input.csv`, `doi_batch_resolved.xlsx`, `doi_batch_failed.csv`, `pdf_download_report.csv`, `run_summary.txt`, and `pdfs\`.

## Legal OA Workflow

Run `paper_skill.py` for public metadata and legal OA PDF candidates only:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe paper_skill.py --input "D:\Papers\papers.txt" --out "D:\Literature\OA" --email "you@example.com"
```

For noisy copied recommendations, prefer dry-run first:

```powershell
.\.venv\Scripts\python.exe paper_skill.py --text "<copied paper list>" --out "D:\Literature\OA" --email "you@example.com" --dry-run
```

Report `metadata\manifest.csv`, `metadata\manifest.json`, `failed\duplicates.csv`, downloaded PDFs, duplicates, and failed/no-legal-PDF rows.

## Safety

- Do not print, paste, summarize, or expose cookie values.
- Do not ask for passwords; browser login is the only login surface.
- Do not use Sci-Hub, LibGen, shadow libraries, or paywall-bypass sources.
- Do not use institutional cookies or browser sessions in the legal OA workflow.
- Treat `needs_review`, `no_legal_open_pdf`, `response_not_pdf`, 403, CAPTCHA, and no-entitlement rows as real unresolved outcomes.
- If downloads fail, inspect reports before retrying; do not repeatedly hammer ScienceDirect.
