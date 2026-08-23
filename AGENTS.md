# Repository Guidelines

## Project Structure & Module Organization

This repository is a Windows-oriented paper download helper.

**User-facing default:** `paper_batch.py` (CLI) and the UI tab **统一批次（推荐）** in `paper_scraper_ui.py`; the GUI contains only that entry tab plus **运行日志**. Codex agents should use skill `paper-download` only.

**Internal / compatibility modules (not default user routes):** `sd_scraper.py` (legacy ScienceDirect DOI batch compatibility CLI), `sd_institutional_skill.py` (ScienceDirect intake/download adapter, also used for preflight), `paper_skill.py` (OA-only adapter), `institutional_paper_skill.py` (non-Elsevier institutional adapter), and skills `sciencedirect-doi-download` / `legal-oa-paper-download`. Shared libraries live under `paper_automation/` and `doi_batch_utils.py`. Path helpers: `windows_paths.py`. Packaging: `start_paper_scraper_ui.bat`, `install_codex_skills.ps1`, `make_windows_ui_package.bat`. Docs: `README.md`, `README_zh.md`, `WINDOWS_UI_README.md`, `MANUAL_QA.md`. Generated `results/`, `dist/`, PDFs, and cookies stay out of Git.

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
.\.venv\Scripts\python.exe -m compileall paper_batch.py preflight_doi_metadata.py paper_scraper_ui.py sd_scraper.py windows_paths.py sd_institutional_skill.py institutional_paper_skill.py paper_skill.py paper_automation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation, `snake_case` for functions and variables, and `PascalCase` for classes. Prefer extending `paper_batch` / `paper_automation` for user-visible workflows; treat `sd_scraper.py` and standalone skill CLIs as compatibility layers unless a task explicitly targets them. Prefer `pathlib.Path` and keep Windows-specific behavior in `windows_paths.py` where practical.

## Testing Guidelines

There is an offline unittest suite under `tests/`. For new logic, add focused tests using `test_*.py` names, and document any required network or institutional-access assumptions. Avoid live ScienceDirect calls in default tests; prefer small local fixtures for DOI parsing, CSV/Excel handling, path behavior, report generation, and skill packaging. Real institutional login and PDF-download checks belong in `MANUAL_QA.md`.

## Commit & Pull Request Guidelines

Git history currently shows only an initial release, so no detailed convention is established. Use concise imperative commit subjects, for example `Fix DOI batch CSV encoding`. Pull requests should describe the user-facing workflow affected, list verification commands, note any manual UI checks, and mention whether cookies, network access, or institutional entitlements were required.

## Literature Identification & Download Rules

Do not skip a literature entry merely because the source text does not provide a DOI. When an entry contains only an author, year, partial title, journal clue, or research-topic description, first search authoritative scholarly sources and resolve the formal title, authors, year, journal, and DOI before starting the download workflow. Verify the identity using all available context, de-duplicate it against already resolved or downloaded papers, and then download the article and any clearly associated supplementary materials through the project's legal open-access or institutional-access routes.

If the available clues match multiple publications and cannot support a unique identification, do not guess and do not silently omit the entry. Record it as `metadata_uncertain` or an equivalent review status, preserve the candidate matches and the reason for ambiguity in the report, and ask for user confirmation only when the remaining choice materially changes which paper would be downloaded. Broad research directions or unspecified paper series must be converted into a bounded candidate list with explicit selection criteria before batch downloading; they must not be expanded without limit.

For browser-assisted institutional login, literature retrieval, and paper downloads, use the Chrome browser built into Codex by default. Do not automatically launch Google Chrome, Microsoft Edge, or any other browser in a separate desktop window, and do not automatically read cookies from those desktop browsers. An external desktop browser may be used only after the user explicitly requests or approves it. Preserve `--browser-exe` and `PAPER_SCRAPER_BROWSER_EXE` only as explicit user-controlled overrides for workflows that genuinely require an external browser.

## Batch failure ladder (A1/A2) + IUCr short try (C6)

**Default one-batch ladder** (do not invent extra agent run dirs):

1. Institutional / ScienceDirect stages
2. Limited OA recovery (`run_post_download_ladder` on `start` **and** `retry-failed`)
3. `zotero_fallback.csv` + CLI auto Zotero (`--no-auto-zotero` to skip)
4. Merge-safe publish to `结果/` + `下载清单.csv` (manual drops preserved)

**Fixed run (A1):** prefer `paper_batch.py start --out <parent> --run-name <job>`;
same input reuses the folder. Use `--fresh` only for a deliberate new batch.

**IUCr (C6):** DOIs `10.1107/*` use **short institutional try** (adapter circuit
threshold **1** + fewer PDF candidates). After miss → OA once → Zotero. Disable
with `--no-iucr-short-try`.

**Manual PDF drop (A3):** after placing a file into `结果/`, run:

```powershell
.\.venv\Scripts\python.exe paper_batch.py refresh-delivery --run-dir "<run-dir>"
```

## OA 直下 + Limited OA recovery (unsupported publishers / capture miss)

**Default product rule (do not skip):** when a non-Elsevier item is
`unsupported_publisher` (no adapter: MDPI/AGU/MSA/SAGE/…) or the adapter returns
`not_pdf_response` / network capture miss, **try bounded OA HTTP download before
Zotero**. This is wired into:

1. `paper_automation.institutional.workflow` — after adapter miss/fail, call
   `recover_oa_limited` (no browser); success → `status=pdf_downloaded`,
   `adapter=oa_direct`.
2. `paper_batch` / `run_post_download_ladder` auto OA recovery after download
   stages — for `unsupported_publisher` / `not_pdf_response` / `pending_zotero`,
   **always attempt** even without a pre-flagged OA signal; other failure classes
   still require an OA signal unless the user runs `recover-oa` manually.

**Do not** run multi-source deep search by default (no multi-URL browser CDP,
no Wayback/CORE/OAI enumeration).

Manual re-run on an existing batch:

```powershell
.\.venv\Scripts\python.exe paper_batch.py recover-oa --run-dir "<run-dir>"
```

Rules for agents and scripts:

1. Prefer project OA (`recover_oa_limited` / `paper_batch.py recover-oa`) over ad-hoc probes.
2. Per DOI budget defaults to **60 seconds** (institutional inline OA uses ~45s); early-stop on first valid PDF.
3. Steps only: (0) Crossref/OpenAlex metadata → (1) annotated OA PDF URLs only → (2) **at most one** repository location that already has a `pdf_url`.
4. **No browser CDP** on the OA path. Do not open SAGE/DOI/repo pages to scrape links.
5. If OpenAlex points at a repository **landing page without a PDF URL** (metadata-only), record `repo_metadata_only` and stop — do not render JS or guess bitstreams.
6. Host negative cache: if a host is `CONNECTION_CLOSED` / SSL failure for one DOI, skip that host for sibling DOIs in the same run.
7. After limited OA fails, keep the prior institutional reason, then use Zotero fallback / institutional VPN — do not invent more sources.
8. Agents must not treat `unsupported_publisher` as terminal without the OA-direct attempt having run (unless user set `try_oa_direct=False` / disabled auto OA).

## PDF Delivery Naming Rule (mandatory)

Every successfully downloaded PDF must be **named correctly at download/publish time** when it is written into the user-facing delivery `pdfs/` folder. Do not leave intermediate or placeholder names as the delivered file, and do not treat a separate post-batch rename as the normal workflow.

**Required delivery pattern:**

```text
年份-第一作者姓-题名.pdf
```

Examples: `2001-Kim-Densification-behavior-of-titanium-alloy-powder.pdf`, `2024-Abedini-Finite-element-modelling-of-ultrasonic-assisted-hot-pressing.pdf`

**Filename sanitize (B5):** strip HTML/MathML tags and residues (`iin-situ-i`,
`subN-sub`) in `clean_title_for_filename` before writing delivery names.

**DOI intake (B4):** `clean_doi` keeps balanced parentheses in paths
(e.g. `10.1016/0956-716x(92)90275-j`) and peels trailing markdown (`**`).

Rules:

- Use the shared helper `paper_automation.file_manager.make_pdf_filename()` (and ScienceDirect `make_article_stem` / `_make_pdf_filename`, which follow the same pattern).
- If the input list lacks year, first author, or a clean title, **resolve metadata by DOI** (Crossref / OpenAlex / publisher page metadata) **before** choosing the delivery filename, then write the PDF under that final name.
- Forbidden as the final delivery name for successful downloads: `0000-Unknown-...`, `paper-0001.pdf`, raw task IDs, or other placeholders when year/author/title can be resolved.
- Stage/cache paths may keep temporary names; the copy into delivery `pdfs/` must use the year–author–title name on first successful publish.
- Agents downloading literature for a user must follow this rule without asking the user to rename files afterward.

## Security & Configuration Tips

Never commit `cookies.json`, browser cookie exports, downloaded PDFs, or generated result tables. Treat institutional cookies as credentials. Keep sample commands generic and avoid hard-coded local user paths in committed documentation or code.

## Agent skills

### Issue tracker

Project work is tracked in GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the repository's default five-label triage vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository; read root `CONTEXT.md` and relevant `docs/adr/` files when they exist. See `docs/agents/domain.md`.
