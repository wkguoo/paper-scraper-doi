---
name: legal-oa-paper-download
description: Resolve messy copied paper lists, DOI/title text, AI-recommended literature, or local text/Markdown files into metadata and provide open-access PDF candidate download assistance. Use when the user asks Codex to find or download open-access papers without institutional cookies, ScienceDirect login, Sci-Hub, LibGen, or paywall bypasses.
---

# OA Resource Assistance Paper Download

Use `paper_skill.py` for public-source paper identification and open-access PDF candidate download assistance. Keep this separate from `sciencedirect-doi-download`; this workflow does not use institutional cookies, browser profile state, or ScienceDirect login.

## Repository

Resolve the repository root in this order:

1. Current directory or parent containing `paper_skill.py` and `paper_automation`.
2. `$env:PAPER_SCRAPER_DOI_ROOT` when it points to that repository.
3. A packaged folder containing `paper_skill.py`.
4. `E:\desktop\paper-scraper-doi` as the local fallback.
5. If none exist, ask the user for the repository path.

Use `.venv\Scripts\python.exe` when it exists; otherwise create the venv and install `requirements.txt`.

## Workflow

1. Accept one input source:
   - `--text "<pasted DOI/title/paper recommendation text>"`
   - `--input "<text-or-markdown-file>"`
2. Run `paper_skill.py` with an explicit `--out` directory.
3. Prefer `--dry-run` first when the input is noisy, title-only, or copied from an AI recommendation.
4. Use `--email` when available for polite Crossref/Unpaywall API use.
5. Report `metadata/manifest.csv`, `metadata/manifest.json`, `failed/duplicates.csv`, counts for resolved rows, downloaded PDFs, duplicates, and unresolved rows without accessible open-access PDFs.

## Commands

Dry-run pasted recommendations:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe paper_skill.py --text "<copied paper list>" --out "D:\Literature\OA" --email "you@example.com" --dry-run
```

Download accessible open-access PDF candidates from a file:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe paper_skill.py --input "D:\Papers\papers.txt" --out "D:\Literature\OA" --email "you@example.com"
```

Use `--limit <N>` only for smoke testing and `--overwrite` only when the user explicitly wants existing PDFs replaced.

## Safety

- Do not use Sci-Hub, LibGen, shadow libraries, or paywall-bypass sources.
- Do not use `cookies.json`, `results/_auth`, Chrome cookies, or institutional browser sessions in this workflow.
- Treat `needs_review`, `no_legal_open_pdf`, and `response_not_pdf` as real unresolved outcomes, not failures to hide.
- Do not synthesize PDF URLs from landing pages unless the public metadata source explicitly provides a PDF URL and the response validates as a PDF.
