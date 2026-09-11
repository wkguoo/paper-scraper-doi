# Paper Scraper DOI — Complete English Guide

[Project home](../../README.md) | English | [中文完整指南](zh.md)

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/github/license/wkguoo/paper-scraper-doi)
![Tests](https://github.com/wkguoo/paper-scraper-doi/actions/workflows/tests.yml/badge.svg)
![Release](https://img.shields.io/github/v/release/wkguoo/paper-scraper-doi?display_name=tag)

Windows-friendly unified DOI batch workflow with authorized access, OA discovery, and Zotero fallback.

This project helps researchers turn DOI tables, copied bibliography text, and AI-recommended paper lists into reviewable reports through **one user-facing batch workflow**. Lower-level OA, ScienceDirect, and publisher adapters are implementation details—not separate product entry points.

## Recommended entry points (use these)

| Situation | Use | Notes |
| --- | --- | --- |
| Any mixed DOI / title / Excel / Markdown list | `paper_batch.py` | Default CLI: project downloads → limited OA → unresolved list; Codex reuses local PDFs via its official Zotero plugin |
| Same workflow in a GUI | `start_paper_scraper_ui.bat` → tab **统一批次（推荐）** | Graphical shell around `paper_batch.py`; the other tab is **运行日志** |
| Natural-language agent | Codex skill `$paper-download` | Install script installs only this skill |

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"
.\.venv\Scripts\python.exe paper_batch.py resume --run-dir "<run-dir>"   # only if manual_retry has rows
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"   # optional native PDF retrieval / existing queue only
```

Do **not** start new literature jobs with `paper_skill.py`, `sd_institutional_skill.py`, or `sd_scraper.py` unless you intentionally want a compatibility path. Those scripts skip the shared batch state and Zotero fallback queue.

## Compatibility / advanced entry points (not the default)

| Entry | Role |
| --- | --- |
| `sd_scraper.py` | Legacy ScienceDirect DOI batch compatibility CLI |
| `sd_institutional_skill.py` | Internal ScienceDirect intake/download adapter (also used by preflight) |
| `paper_skill.py` | Internal OA-only adapter |
| `institutional_paper_skill.py` | Internal non-Elsevier institutional adapter |

## What It Does

- Reads DOI lists from Excel, CSV, TXT, Markdown, or pasted text.
- Runs a beginner preflight (when requested) to identify valid DOI rows, duplicates, invalid rows, and records that need manual review.
- Through the **unified batch**, tries open-access discovery, then authorized publisher access, one manual retry, and optional Zotero fallback.
- May download ScienceDirect supplementary materials when that stage runs with supplements enabled.
- Installs the single Codex skill `paper-download` so agents follow the same unified route.

## What It Does Not Do

- It does not provide database, university, publisher, or ScienceDirect access.
- It does not ask Codex or the script to enter your university account password.
- It does not guarantee that title-only metadata matching is correct. Uncertain rows are kept in `needs_review`.

中文说明：本项目不提供任何数据库、学校或出版社访问权限。完整中文说明见 [中文完整指南](zh.md)。

## Quick Start

Run these commands in PowerShell from the cloned repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Check the **recommended** CLI:

```powershell
.\.venv\Scripts\python.exe paper_batch.py --help
.\.venv\Scripts\python.exe paper_batch.py start --help
```

Open the Windows UI (it contains only **统一批次（推荐）** and **运行日志**):

```powershell
.\start_paper_scraper_ui.bat
```

Install or refresh Codex Skills (only `paper-download`):

```powershell
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1
```

The dry run only shows the target skill path and planned changes. The install command copies only `paper-download` into the Codex skills directory and sets `PAPER_SCRAPER_DOI_ROOT`.

## Common Workflows

### Beginner Preflight (optional before a formal download)

For messy AI recommendation lists, preflight first (local intake review; no PDF download):

```text
Use $paper-download to preflight these paper recommendations with --beginner --preflight.
Save results to D:\Literature\ScienceDirect.

1. A critical review of high entropy alloys and related concepts
2. DOI: 10.1016/j.actamat.2016.08.081
3. unclear recommendation about alloy fatigue without enough bibliographic information
```

Check `doi_intake_preview.csv`, `merged_doi_input.csv`, and related reports, then run **`paper_batch.py start`** (or the UI unified-batch tab) on the confirmed list.

### Recommended: official Zotero lookup and optional manual bridge

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"
```

`start`, `retry-failed`, and `recover-oa` leave unresolved DOI rows in
`working/zotero_fallback.csv` without queuing or waiting for Zotero. Codex uses
the official Zotero plugin through `paper-download` to match existing local
PDFs, then runs `paper_batch.py finalize` on confirmed successes only. The
standalone GUI/CLI does not launch Codex or perform this lookup.

For explicit native PDF retrieval or an existing bridge manifest, keep the
custom XPI enabled in the intended Zotero instance and run:

```powershell
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
```

Alternatively, pass `--auto-zotero` explicitly to `start`, `retry-failed`, or
`recover-oa`. `--no-auto-zotero` remains a mutually exclusive compatibility
flag. `--library-id` and `--wait-seconds` apply only to manual/opt-in bridge
runs. Exit 3 means waiting; continue the same `zotero` command when ready.
Keep old jobs and receipts unchanged. `resume` is only for the old one-shot
manual retry workflow enabled with `--enable-manual-retry`.

For the unified batch, user-facing files are in `结果\`: the original input,
`下载清单.csv`, `pdf\`, and an always-present empty `md\`; `补充材料\` is
created only when supplementary files were actually downloaded. The inventory
keeps the existing UTF-8-SIG CSV format and 12 columns
(`序号,状态,DOI,题名,作者,年份,期刊,下载来源,结果文件,补充材料,失败原因,task_id`),
with batch-root-relative paths such as `结果/pdf/paper.pdf` and
`结果/补充材料/paper`. Internal cache, reports, and handoff files remain in
`pdfs\`, `reports\`, and `working\`. See the
[Zotero bridge beginner guide](../zotero_bridge_beginner_guide.md). The XPI
remains approval-gated: test only in a Zotero test profile first.

For institutional login or verification, try the Codex in-app browser first.
If it is unavailable, the external browser fallback prefers Google Chrome, then
Edge Stable/Beta/Dev/Canary, then Playwright Chromium. An explicit `--browser-exe`
or `PAPER_SCRAPER_BROWSER_EXE` override always wins.

## Outputs

**Unified batch** (`paper_batch.py`) writes one timestamped run directory with
normalized input, stage reports, `manual_retry.csv` / `zotero_fallback.csv`,
final manifests, internal `pdfs\` cache, and the user delivery package under
`结果\`. Re-publishing preserves user-added PDF, supplement, and Markdown
files; old PDFs directly under `结果\` are migrated into `结果/pdf\`.

Legacy ScienceDirect-only runs may still create folders with reports such as:

- `doi_intake_preview.csv`
- `merged_doi_input.csv`
- `doi_batch_resolved.xlsx`
- `doi_batch_failed.csv`
- `pdf_download_report.csv`
- `supplement_download_report.csv`
- `run_summary.txt`
- `run_summary.json`
- `pdfs\`
- `supplements\`

## Security Notes

Treat institutional cookies and browser session state as credentials.

- Do not commit or upload `cookie.json`, `cookies.json`, exported cookies, account passwords, PDFs, result tables, browser cache, or internal institution pages.
- Do not paste cookies, passwords, PDFs, or institution screenshots into GitHub Issues.
- Keep downloaded PDFs, `results\`, `pdfs\`, `.venv\`, and `dist\` out of Git and release assets.
- See the [security policy](../../.github/SECURITY.md) before reporting security issues.

Before publishing a fork or release package, check:

```powershell
git status --short
git ls-files | rg "cookie|cookies|results|pdfs|\.pdf$|\.xlsx$|\.csv$|\.venv|dist"
```

## Development

Run the offline checks before committing Python or workflow changes:

```powershell
.\.venv\Scripts\python.exe -m compileall paper_batch.py preflight_doi_metadata.py paper_scraper_ui.py sd_scraper.py windows_paths.py sd_institutional_skill.py institutional_paper_skill.py paper_skill.py paper_automation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Manual checks that require real institutional login, CAPTCHA, or PDF access are documented in the [manual QA checklist](../development/manual-qa.md).

## License

This project is licensed under the [MIT License](../../LICENSE), with copyright held by `wkguoo`. Notices for third-party code included in this repository are listed in [THIRD_PARTY_NOTICES.md](../legal/THIRD_PARTY_NOTICES.md).
