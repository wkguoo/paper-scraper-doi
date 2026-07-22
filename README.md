# Paper Scraper DOI

[English](README.md) | [中文说明](README_zh.md)

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
| Any mixed DOI / title / Excel / Markdown list | `paper_batch.py` | Default CLI: OA → institutional access → one manual retry → Zotero fallback |
| Same workflow in a GUI | `start_paper_scraper_ui.bat` → tab **统一批次（推荐）** | Graphical shell around `paper_batch.py` |
| Natural-language agent | Codex skill `$paper-download` | Install script installs only this skill |

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"
.\.venv\Scripts\python.exe paper_batch.py resume --run-dir "<run-dir>"   # only if manual_retry has rows
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"   # remaining failures only
```

Do **not** start new literature jobs with `paper_skill.py`, `sd_institutional_skill.py`, `sd_scraper.py`, or `sd_scraper_en.py` unless you intentionally want a compatibility path. Those scripts skip the shared batch state and Zotero fallback queue.

## Compatibility / advanced entry points (not the default)

| Entry | Role |
| --- | --- |
| UI tabs `DOI 批量下载` / `文献检索` / `OA 资源辅助获取` | Legacy GUI paths for ScienceDirect-only or OA-only tasks |
| `sd_scraper.py` / `sd_scraper_en.py` | Legacy ScienceDirect search + DOI batch CLIs (CN / EN) |
| `sd_institutional_skill.py` | Internal ScienceDirect intake/download adapter (also used by preflight) |
| `paper_skill.py` | Internal OA-only adapter |
| `institutional_paper_skill.py` | Internal non-Elsevier institutional adapter |
| Skills `sciencedirect-doi-download` / `legal-oa-paper-download` | Internal skill docs; not installed by default |

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

中文兼容说明：本项目基于开源项目修改并扩展；本项目不提供任何数据库、学校或出版社访问权限。完整中文说明见 [README_zh.md](README_zh.md)。

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

Open the Windows UI (first tab is **统一批次（推荐）**):

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

### Recommended: unified batch with Zotero fallback

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"
```

Prefer a **DOI-only** list (TXT one DOI per line, or a table with a DOI column).
Markdown is fine, but by default only explicit DOIs become tasks.

Default path: DOI preflight → OA (gold / OA-signal only) → institutional access →
bounded OA recovery for OA-signal failures → **DOI-bearing failures go to
`zotero_fallback.csv`** (no `resume` gate). `start` **auto-queues** Zotero and
returns immediately (default `--wait-seconds 0`). Keep Zotero open with bridge
plugin **0.2.0+**. Exit code 3 means the job is queued; after the plugin
finishes, rerun only the same command:

```powershell
.\.venv\Scripts\python.exe paper_batch.py zotero --run-dir "<run-dir>"
```

Optional: `--wait-seconds N` on `start` to poll in-process; `--no-auto-zotero`
to queue later; `--enable-manual-retry` for the legacy one-shot login/CAPTCHA
path (then `resume` once if `manual_retry.csv` has rows).

Read batch progress without changing state:

```powershell
.\.venv\Scripts\python.exe paper_batch.py status --run-dir "<run-dir>"
.\.venv\Scripts\python.exe paper_batch.py status --run-dir "<run-dir>" --json
```

New batches use a dynamic debugging port and a controlled shared institutional
browser profile. Reuse requires matching PID, executable, profile, port, and
DevTools browser ID; an unknown process on an explicit port is never attached.

Final PDFs are in `pdfs\`, reports are in `reports\`, and handoff files remain
in `working\`. See the
[Zotero bridge beginner guide](docs/zotero_bridge_beginner_guide.md). The XPI
remains approval-gated: test only in a Zotero test profile first.

For institutional login or verification, try the Codex in-app browser first.
If it is unavailable, the external browser fallback prefers Google Chrome, then
Edge Stable/Beta/Dev/Canary, then Playwright Chromium. An explicit `--browser-exe`
or `PAPER_SCRAPER_BROWSER_EXE` override always wins.

## Outputs

**Unified batch** (`paper_batch.py`) writes one timestamped run directory with
normalized input, stage reports, `manual_retry.csv` / `zotero_fallback.csv`,
final manifests, and `pdfs\`.

Legacy ScienceDirect-only runs may still create folders with reports such as:

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

## Recovery and trusted delivery

Unified batches keep optional attempt leases in `working\batch_state.json`.
Each active attempt has a five-minute lease with periodic renewal. A second
process receives `batch_attempt_in_progress`; expired attempts are reclaimed,
and late writes from an old attempt are rejected as `attempt_lease_lost`.

Crossref, OpenAlex, Unpaywall, and Semantic Scholar lookups share
`working\metadata_cache.jsonl`. Successful and not-found lookups live for 30
days; transient failures live for five minutes. DOI-only input is cleaned
locally without a preflight network requirement.

PDFs and supplements use bounded streaming publication: 256 MB for article
PDFs, 2 GB for supplements, and 8 MB for metadata JSON. Same-name different
content is never overwritten. At final delivery, program-owned PDFs must also
open with `pypdf` and contain at least one page; failures become
`not_pdf_response`. Manually added PDFs are preserved.

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
.\.venv\Scripts\python.exe -m compileall paper_batch.py paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation
$env:PYTHONPATH = (Resolve-Path -LiteralPath ".\tests").Path
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test .\zotero_bridge_plugin\tests\*.test.cjs
```

Offline tests block unmocked public sockets while allowing loopback. Windows CI
uses Node 24 for all 65 plugin tests and validates an XPI only in a temporary CI
directory; local validation does not replace anything under `dist\`.

Manual checks that require real institutional login, CAPTCHA, or PDF access are documented in [MANUAL_QA.md](MANUAL_QA.md).

## Project Origin

This project is based on and extends [GAO-pooh/paper-scraper](https://github.com/GAO-pooh/paper-scraper/tree/main). The original project uses the MIT License. This repository keeps the original copyright and license notices, and adds Windows UI support, DOI batch intake improvements, Cookie JSON support, supplementary material handling, OA PDF candidate discovery, and Codex Skills.

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for license and modification details. Later changes, extensions, and new modules in this repository are maintained by `wkguoo` and declare modification copyright as `Copyright (c) 2026 wkguoo (modifications)`.
