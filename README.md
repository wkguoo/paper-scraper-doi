# Paper Scraper DOI

[English](README.md) | [中文说明](README_zh.md)

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/github/license/wkguoo/paper-scraper-doi)
![Tests](https://github.com/wkguoo/paper-scraper-doi/actions/workflows/tests.yml/badge.svg)
![Release](https://img.shields.io/github/v/release/wkguoo/paper-scraper-doi?display_name=tag)

Windows-friendly DOI organizer and authorized paper access helper with OA PDF discovery and Codex Skills.

This project helps researchers turn DOI tables, copied bibliography text, and AI-recommended paper lists into reviewable reports. It provides a Windows Tkinter UI, command-line workflows, and optional Codex Skills for ScienceDirect authorized-access PDF saving and open-access PDF candidate discovery.

## What It Does

- Reads DOI lists from Excel, CSV, TXT, Markdown, or pasted text.
- Runs a beginner preflight to identify valid DOI rows, duplicates, invalid rows, and records that need manual review.
- Saves ScienceDirect PDFs when you already have authorized access through your institution, browser login state, or exported cookies.
- Attempts ScienceDirect supplementary material downloads and records attachment status.
- Searches public metadata sources for open-access PDF candidates without using institutional cookies.
- Installs Codex Skills so the same workflows can be started with natural language.

## What It Does Not Do

- It does not provide database, university, publisher, or ScienceDirect access.
- It does not ask Codex or the script to enter your university account password.
- It does not guarantee that title-only metadata matching is correct. Uncertain rows are kept in `needs_review`.

中文兼容说明：本项目基于开源项目修改并扩展；本项目不提供任何数据库、学校或出版社访问权限。完整中文说明见 [README_zh.md](README_zh.md)。

## Quick Start

Run these commands in PowerShell from the cloned repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Check the command-line entry points:

```powershell
.\.venv\Scripts\python.exe sd_scraper.py --help
.\.venv\Scripts\python.exe paper_skill.py --help
```

Open the Windows UI:

```powershell
.\start_paper_scraper_ui.bat
```

Install or refresh Codex Skills:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1 -DryRun
powershell -ExecutionPolicy Bypass -File .\install_codex_skills.ps1
```

The dry run only shows the target skill path and planned changes. The install command copies `paper-download`, `sciencedirect-doi-download`, and `legal-oa-paper-download` into the Codex skills directory and sets `PAPER_SCRAPER_DOI_ROOT`.

## Common Workflows

### Beginner Preflight

Use preflight before downloading from a messy recommendation list:

```text
Use $paper-download to preflight these paper recommendations with --beginner --preflight.
Save results to D:\Literature\ScienceDirect.

1. A critical review of high entropy alloys and related concepts
2. DOI: 10.1016/j.actamat.2016.08.081
3. unclear recommendation about alloy fatigue without enough bibliographic information
```

Preflight only performs local intake, deduplication, and review hints. It does not download PDFs, parse ScienceDirect PII values, or create supplementary material folders. Check `doi_intake_preview.csv`, `merged_doi_input.csv`, `doi_batch_failed.csv`, `run_summary.txt`, and `00_给研究生查看\` before running a real download.

### ScienceDirect Authorized-Access Workflow

Use this workflow only for papers you can already access through your institution or personal subscription:

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs
```

To skip supplementary material downloads:

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs --no-download-supplements
```

### OA PDF Candidate Discovery

Use this workflow for mixed publisher lists when you only want to search public metadata and downloadable open-access candidates:

```powershell
.\.venv\Scripts\python.exe paper_skill.py --input "papers.txt" --out "D:\Literature\OA" --email "you@example.com" --dry-run
.\.venv\Scripts\python.exe paper_skill.py --input "papers.txt" --out "D:\Literature\OA" --email "you@example.com"
```

This workflow does not read `cookies.json` and does not use institutional login state.

## Outputs

ScienceDirect batch runs create a timestamped result folder containing reports such as:

- `doi_intake_preview.csv`
- `merged_doi_input.csv`
- `doi_batch_resolved.xlsx`
- `doi_batch_failed.csv`
- `pdf_download_report.csv`
- `supplement_download_report.csv`
- `run_summary.txt`
- `run_summary.json`
- `00_给研究生查看\`
- `pdfs\`
- `supplements\`

OA PDF candidate discovery writes metadata and download status into `metadata\manifest.csv`, `metadata\manifest.json`, `failed\`, `logs\`, and `pdfs\` when files are downloaded.

## Security Notes

Treat institutional cookies and browser session state as credentials.

- Do not commit or upload `cookie.json`, `cookies.json`, exported cookies, account passwords, PDFs, result tables, browser cache, or internal institution pages.
- Do not paste cookies, passwords, PDFs, or institution screenshots into GitHub Issues.
- Keep downloaded PDFs, `results\`, `pdfs\`, `.venv\`, and `dist\` out of Git and release assets.
- See [SECURITY.md](SECURITY.md) before reporting security issues.

Before publishing a fork or release package, check:

```powershell
git status --short
git ls-files | rg "cookie|cookies|results|pdfs|\.pdf$|\.xlsx$|\.csv$|\.venv|dist"
```

## Development

Run the offline checks before committing Python or workflow changes:

```powershell
.\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Manual checks that require real institutional login, CAPTCHA, or PDF access are documented in [MANUAL_QA.md](MANUAL_QA.md).

## Project Origin

This project is based on and extends [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main). The original project uses the MIT License. This repository keeps the original copyright and license notices, and adds Windows UI support, DOI batch intake improvements, Cookie JSON support, supplementary material handling, OA PDF candidate discovery, and Codex Skills.

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for license and modification details. Later changes, extensions, and new modules in this repository are maintained by `wkguoo` and declare modification copyright as `Copyright (c) 2026 wkguoo (modifications)`.
