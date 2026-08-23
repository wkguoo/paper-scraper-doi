# Beginner Workflow

Use this reference when the user is new, gives copied AI recommendations, or provides title-only/short citation text.

## Default sequence

1. Run preflight first:

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<paper list>" --out results --beginner --preflight
```

2. Report these preflight files:
   - `doi_intake_preview.csv`
   - `merged_doi_input.csv` when generated
   - `doi_batch_failed.csv`
   - `run_summary.txt`
   - `run_summary.json`

3. Explain statuses:
   - `valid`: confirmed DOI candidate; can be downloaded in a second run.
   - `needs_review`: unresolved; ask the user to supply DOI or a fuller citation.
   - `duplicate`: already represented by another row.
   - `invalid` or `empty`: copied input should be corrected or ignored.

4. Download only confirmed rows by rerunning without `--beginner` and `--preflight`.
5. In the formal download report, include `doi_batch_resolved.xlsx`, `pdf_download_report.csv`, and `pdfs\`. Include `supplement_download_report.csv` and `supplements\` only when PDF downloading and supplement downloading were both active.

## When to use optional search

For title-only or short citation inputs, preflight marks uncertain rows for review first. Use `--resolve-title-only --auto-web-search` later only when the user explicitly wants public metadata search to help fill DOI values.

Do not use optional search as a license to guess DOI values. If evidence is weak, leave the row in `needs_review`.

## What to tell the user

Keep the final report concrete:

- output directory
- number of valid DOI rows
- number of `needs_review` rows
- PDF success/failed/skipped counts when a download run was performed
- supplement success/failed/skipped/not-found counts only when PDF download and supplement download were enabled
- exact report paths
- whether institutional login or cookie cache was used

Explain supplement status `not_found` as no detectable supplement links on the article page, not as a PDF failure.
