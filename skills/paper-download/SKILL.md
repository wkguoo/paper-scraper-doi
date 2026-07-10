---
name: paper-download
description: Route paper download requests to either ScienceDirect/Elsevier institutional-access downloads or open-access resource discovery and download assistance. Use when Codex needs to download papers, process DOI batches, resolve DOI/title lists, handle local literature files or folders, dry-run paper recognition, use institutional Edge/Chrome login and cookies for ScienceDirect, or find open-access PDF candidates without institutional cookies.
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

Use `sd_institutional_skill.py` for ScienceDirect institutional access when the user mentions ScienceDirect, Elsevier, institution/school access, cookies, Edge/Chrome login, DOI batch download, or when the input is clearly dominated by Elsevier DOI values such as `10.1016/...`.

Use `paper_skill.py` for open-access resource discovery and download assistance when the user asks for OA/open-access PDFs, public-source PDFs, no login, no cookies, or mixed publisher lists where institutional access is not requested.

When intent is unclear, infer from wording and input. Ask only if the choice changes safety or expected access path.

For noisy AI recommendations, title-only lists, short citations, or beginner users, route ScienceDirect requests through preflight first:

```powershell
.\.venv\Scripts\python.exe sd_institutional_skill.py --text "<paper list>" --out results --beginner --preflight
```

Download only after reporting `doi_intake_preview.csv`, `merged_doi_input.csv`, `00_给研究生查看\paper_index.csv`, and excluding `needs_review` rows.

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

Use `--beginner --preflight` when the user asks for a safe preview or gives messy recommendations. Preflight writes intake/review outputs and does not download PDFs or supplement files. Use `--dry-run` only when the user specifically wants ScienceDirect DOI metadata/PII resolution without PDF download. Use `--resolve-title-only` only when the user explicitly wants file rows without DOI to be resolved by title.

When PDF downloading is active, ScienceDirect supplementary materials are downloaded by default into `supplements\` and summarized in `supplement_download_report.csv`. These supplement outputs are generated only when PDF download and supplement download are both active. Add `--no-download-supplements` only when the user explicitly wants PDFs without supplementary files. Explain supplement status `not_found` as no detectable supplement links, not as a PDF failure.

Report preflight outputs separately from formal download outputs. Preflight centers on `doi_intake_preview.csv`, `merged_doi_input.csv`, `doi_batch_failed.csv`, `run_summary.txt`, and `00_给研究生查看\`; do not report `doi_batch_resolved.xlsx` as a preflight output. Formal downloads also report `doi_batch_resolved.xlsx`, `pdf_download_report.csv`, `pdfs\`, `library_index.csv`, and `00_给研究生查看\paper_index.csv/xlsx`. When generated, also report `supplement_download_report.csv` plus `supplements\`.

Every ScienceDirect institutional run writes a student handoff folder:

```text
00_给研究生查看\
├── README_先看我.txt
├── paper_index.csv
├── paper_index.xlsx
└── 失败项_下一步处理.csv
```

Explain that this folder indexes PDFs and supplements by relative path and does not copy downloaded files. Use `失败项_下一步处理.csv` before retrying failed DOI values.

## OA Resource Assistance Workflow

Run `paper_skill.py` for public metadata and open-access PDF candidates only:

```powershell
Set-Location "<resolved repository root>"
.\.venv\Scripts\python.exe paper_skill.py --input "D:\Papers\papers.txt" --out "D:\Literature\OA" --email "you@example.com"
```

For noisy copied recommendations, prefer dry-run first:

```powershell
.\.venv\Scripts\python.exe paper_skill.py --text "<copied paper list>" --out "D:\Literature\OA" --email "you@example.com" --dry-run
```

Report `metadata\manifest.csv`, `metadata\manifest.json`, `failed\duplicates.csv`, downloaded PDFs, duplicates, and unresolved rows without accessible open-access PDFs.

## Safety

- Do not print, paste, summarize, or expose cookie values.
- Do not ask for passwords; browser login is the only login surface.
- Do not use institutional cookies or browser sessions in the OA resource assistance workflow.
- Do not use institutional cookies or browser sessions in the OA resource assistance workflow.
- Treat `needs_review`, `no_legal_open_pdf`, `response_not_pdf`, 403, CAPTCHA, and no-entitlement rows as real unresolved outcomes.
- If downloads fail, inspect reports before retrying; do not repeatedly hammer ScienceDirect.
