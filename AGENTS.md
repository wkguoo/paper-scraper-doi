# Repository Guidelines

## Project Structure & Module Organization

This repository is a compact Windows-oriented paper download helper. Core ScienceDirect logic lives in `sd_scraper.py` for the Chinese CLI, `sd_scraper_en.py` for the English CLI, and `sd_institutional_skill.py` for the Codex ScienceDirect institutional-access skill. The legal open-access workflow lives in `paper_skill.py` and `paper_automation/`. The Tkinter desktop entry point is `paper_scraper_ui.py`, with Windows path helpers in `windows_paths.py`. Codex skills live under `skills/`. User documentation is in `README.md`, `README_zh.md`, `WINDOWS_UI_README.md`, `MANUAL_QA.md`, plus the Chinese cookie-export guide. Windows launch, skill install, and packaging scripts are `start_paper_scraper_ui.bat`, `install_codex_skills.ps1`, and `make_windows_ui_package.bat`. Generated outputs such as `results/`, `dist/`, `pdfs/`, CSV/XLSX/JSON files, and cookies are intentionally ignored.

## Build, Test, and Development Commands

Create an isolated environment and install runtime dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the UI:

```powershell
.\start_paper_scraper_ui.bat
```

Run a DOI batch download from the CLI:

```powershell
.\.venv\Scripts\python.exe sd_scraper.py -m doi_batch --input "papers.csv" --doi-column "doi" --cookies "cookies.json" --download-pdfs
```

Package the Windows UI source bundle:

```powershell
.\make_windows_ui_package.bat
```

Before committing Python changes, at minimum run:

```powershell
.\.venv\Scripts\python.exe -m compileall paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation, `snake_case` for functions and variables, and `PascalCase` for classes. Keep UI code in `paper_scraper_ui.py`; keep scraper behavior in the CLI modules unless a UI-only wrapper is needed. Prefer `pathlib.Path` for filesystem paths and keep Windows-specific behavior inside `windows_paths.py` where practical.

## Testing Guidelines

There is an offline unittest suite under `tests/`. For new logic, add focused tests using `test_*.py` names, and document any required network or institutional-access assumptions. Avoid live ScienceDirect calls in default tests; prefer small local fixtures for DOI parsing, CSV/Excel handling, path behavior, report generation, and skill packaging. Real institutional login and PDF-download checks belong in `MANUAL_QA.md`.

## Commit & Pull Request Guidelines

Git history currently shows only an initial release, so no detailed convention is established. Use concise imperative commit subjects, for example `Fix DOI batch CSV encoding`. Pull requests should describe the user-facing workflow affected, list verification commands, note any manual UI checks, and mention whether cookies, network access, or institutional entitlements were required.

## Security & Configuration Tips

Never commit `cookies.json`, browser cookie exports, downloaded PDFs, or generated result tables. Treat institutional cookies as credentials. Keep sample commands generic and avoid hard-coded local user paths in committed documentation or code.

## Agent skills

### Issue tracker

Project work is tracked in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the repository's default five-label triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository; read root `CONTEXT.md` and relevant `docs/adr/` files when they exist. See `docs/agents/domain.md`.
