# Repository Guidelines

## Project Structure & Module Organization

This repository is a Windows-oriented paper download helper.

**User-facing default:** `paper_batch.py` (CLI) and the UI tab **统一批次（推荐）** in `paper_scraper_ui.py`. Codex agents should use skill `paper-download` only.

**Internal / compatibility modules (not default user routes):** `sd_scraper.py` / `sd_scraper_en.py` (legacy ScienceDirect CLIs), `sd_institutional_skill.py` (ScienceDirect intake/download adapter, also used for preflight), `paper_skill.py` (OA-only adapter), `institutional_paper_skill.py` (non-Elsevier institutional adapter), and skills `sciencedirect-doi-download` / `legal-oa-paper-download`. Shared libraries live under `paper_automation/` and `doi_batch_utils.py`. Path helpers: `windows_paths.py`. Packaging: `start_paper_scraper_ui.bat`, `install_codex_skills.ps1`, `make_windows_ui_package.bat`. Docs: `README.md`, `README_zh.md`, `WINDOWS_UI_README.md`, `MANUAL_QA.md`. Generated `results/`, `dist/`, PDFs, and cookies stay out of Git.

## Build, Test, and Development Commands

Create an isolated environment and install runtime dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Recommended CLI (new literature jobs):

```powershell
.\.venv\Scripts\python.exe paper_batch.py start --input "papers.xlsx" --out "results" --email "you@example.com"
```

Run the UI (default tab is unified batch):

```powershell
.\start_paper_scraper_ui.bat
```

Legacy ScienceDirect-only CLI (compatibility, not the default product path):

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs
```

Package the Windows UI source bundle:

```powershell
.\make_windows_ui_package.bat
```

Before committing Python changes, at minimum run:

```powershell
.\.venv\Scripts\python.exe -m compileall paper_batch.py paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation, `snake_case` for functions and variables, and `PascalCase` for classes. Prefer extending `paper_batch` / `paper_automation` for user-visible workflows; treat `sd_scraper*` and standalone skill CLIs as compatibility layers unless a task explicitly targets them. Prefer `pathlib.Path` and keep Windows-specific behavior in `windows_paths.py` where practical.

## Testing Guidelines

There is an offline unittest suite under `tests/`. For new logic, add focused tests using `test_*.py` names, and document any required network or institutional-access assumptions. Avoid live ScienceDirect calls in default tests; prefer small local fixtures for DOI parsing, CSV/Excel handling, path behavior, report generation, and skill packaging. Real institutional login and PDF-download checks belong in `MANUAL_QA.md`.

## Commit & Pull Request Guidelines

Git history currently shows only an initial release, so no detailed convention is established. Use concise imperative commit subjects, for example `Fix DOI batch CSV encoding`. Pull requests should describe the user-facing workflow affected, list verification commands, note any manual UI checks, and mention whether cookies, network access, or institutional entitlements were required.

## Literature Identification & Download Rules

Do not skip a literature entry merely because the source text does not provide a DOI. When an entry contains only an author, year, partial title, journal clue, or research-topic description, first search authoritative scholarly sources and resolve the formal title, authors, year, journal, and DOI before starting the download workflow. Verify the identity using all available context, de-duplicate it against already resolved or downloaded papers, and then download the article and any clearly associated supplementary materials through the project's legal open-access or institutional-access routes.

If the available clues match multiple publications and cannot support a unique identification, do not guess and do not silently omit the entry. Record it as `metadata_uncertain` or an equivalent review status, preserve the candidate matches and the reason for ambiguity in the report, and ask for user confirmation only when the remaining choice materially changes which paper would be downloaded. Broad research directions or unspecified paper series must be converted into a bounded candidate list with explicit selection criteria before batch downloading; they must not be expanded without limit.

For browser-assisted institutional login, literature retrieval, and paper downloads, use the Chrome browser built into Codex by default. Do not automatically launch Google Chrome, Microsoft Edge, or any other browser in a separate desktop window, and do not automatically read cookies from those desktop browsers. An external desktop browser may be used only after the user explicitly requests or approves it. Preserve `--browser-exe` and `PAPER_SCRAPER_BROWSER_EXE` only as explicit user-controlled overrides for workflows that genuinely require an external browser.

## Security & Configuration Tips

Never commit `cookies.json`, browser cookie exports, downloaded PDFs, or generated result tables. Treat institutional cookies as credentials. Keep sample commands generic and avoid hard-coded local user paths in committed documentation or code.

## Agent skills

### Issue tracker

Project work is tracked in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the repository's default five-label triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository; read root `CONTEXT.md` and relevant `docs/adr/` files when they exist. See `docs/agents/domain.md`.
