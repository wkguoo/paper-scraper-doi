# Legal OA Paper Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a legal, public-source paper identification and OA PDF workflow that accepts messy pasted text, deduplicates entries, resolves metadata, downloads only allowed open PDFs, and writes manifest files.

**Architecture:** Keep the existing ScienceDirect DOI batch workflow intact. Add a separate `paper_automation` package plus a `paper_skill.py` CLI wrapper so the legal OA workflow does not reuse institutional cookies, anti-bot bypasses, or restricted publisher download code.

**Tech Stack:** Python standard library, existing `doi_batch_utils.clean_doi`, `doi_batch_utils.extract_doi_from_text`, `unittest`.

---

### Task 1: Parser and Deduplicator

**Files:**
- Create: `paper_automation/models.py`
- Create: `paper_automation/parser.py`
- Create: `paper_automation/deduplicator.py`
- Test: `tests/test_paper_automation.py`

- [x] Write failing tests for messy pasted text, DOI extraction, title normalization, DOI duplicate mapping, and title fuzzy duplicate mapping.
- [x] Implement dataclasses for paper candidates and duplicate mappings.
- [x] Implement DOI extraction by reusing existing DOI cleaning rules.
- [x] Implement conservative title candidate extraction and `needs_review` marking for ambiguous rows.
- [x] Implement DOI-first deduplication and title fallback deduplication.
- [x] Run `python -m unittest tests.test_paper_automation -v`.

### Task 2: Metadata and OA PDF Selection

**Files:**
- Create: `paper_automation/metadata_resolver.py`
- Create: `paper_automation/pdf_finder.py`
- Test: `tests/test_paper_automation.py`

- [x] Write failing tests using fake JSON responses for Crossref, OpenAlex, and Unpaywall.
- [x] Implement a small JSON HTTP client using `urllib.request` with a clear User-Agent.
- [x] Resolve by DOI first; if DOI is absent, query by title.
- [x] Score title matches with normalized exact/fuzzy matching and DOI agreement.
- [x] Prefer Unpaywall OA PDFs, then OpenAlex OA PDFs, then Crossref PDF links that declare a PDF content type.
- [x] Never synthesize a PDF URL when no allowed source returns one.
- [x] Run `python -m unittest tests.test_paper_automation -v`.

### Task 3: File Management, Manifest, and CLI

**Files:**
- Create: `paper_automation/file_manager.py`
- Create: `paper_automation/downloader.py`
- Create: `paper_automation/manifest.py`
- Create: `paper_automation/workflow.py`
- Create: `paper_skill.py`
- Test: `tests/test_paper_automation.py`

- [x] Write failing tests for Windows-safe PDF names, output directory creation, dry-run manifest rows, and existing-file skip behavior.
- [x] Implement directory creation for `pdfs/`, `metadata/`, `logs/`, and `failed/`.
- [x] Implement filename generation as `year_first-author_short-title_doi-hash.pdf`.
- [x] Implement PDF download validation: accept only `application/pdf` or `%PDF` bytes; retry limited transient failures; rate-limit between downloads.
- [x] Implement resumable manifest writing to CSV and JSON.
- [x] Implement CLI arguments: `--input`, `--text`, `--out`, `--email`, `--dry-run`, `--overwrite`, `--limit`.
- [x] Run `python -m unittest tests.test_paper_automation -v`.

### Task 4: Documentation and Verification

**Files:**
- Modify: `README_zh.md`
- Modify: `README.md`

- [x] Add legal OA workflow examples without suggesting paywall bypass.
- [x] Document that Unpaywall email is recommended and can be passed with `--email`.
- [x] Document output files and failure reasons.
- [x] Run `python -m py_compile paper_skill.py paper_automation/*.py paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py`.
- [x] Run the full unittest suite with `python -m unittest discover -v`.
