# Task 8 Report: Offline End-to-End Acceptance

## Scope and boundaries

This Task 8 acceptance adds one offline integration fixture only. It does not
modify product code, invoke a network client, access a real Zotero library,
install the project Skill, read credentials, or package the Windows project.

## Test design

`BatchEndToEndTests.test_start_resume_finalize_produces_one_manifest_and_valid_pdfs`
uses the existing deterministic normalizer and `FakeBatchGateway`:

1. Three normalized inputs are supplied.
2. The first receives a valid project PDF during `start`.
3. The other two enter `captcha_required`, then both pass through exactly one
   `resume`; `gateway.retry_calls == 1` verifies the single retry.
4. A controlled Zotero CSV supplies a valid attachment for `paper-0002` and a
   `no_pdf/no_available_pdf` result for `paper-0003`.
5. `finalize` must report two successes and one failure, publish exactly two
   valid PDFs, create the XLSX manifest, retain all three task IDs in the CSV
   manifest, and preserve both original source-PDF hashes.
6. A second `finalize` call must retain the same delivered names and bytes,
   proving the current terminal-state implementation does not duplicate or
   overwrite final PDFs.

## Evidence

- Focused acceptance command:

  ```powershell
  ..\..\.venv\Scripts\python.exe -m unittest tests.test_batch_workflow.BatchEndToEndTests -v
  ```

  Result: `Ran 1 test in 0.629s` and `OK`.

- Syntax command:

  ```powershell
  ..\..\.venv\Scripts\python.exe -m compileall paper_batch.py paper_scraper_ui.py sd_scraper.py sd_scraper_en.py windows_paths.py sd_institutional_skill.py paper_skill.py paper_automation
  ```

  Result: exit code 0.

- Full offline command:

  ```powershell
  ..\..\.venv\Scripts\python.exe -m unittest discover -s tests -v
  ```

  Result: `Ran 288 tests in 14.492s`, `OK (skipped=2)`.

- Active-code/Skill source scan:

  ```powershell
  rg -n "Sci-Hub|scihub|Anna's Archive|annas_archive|LibGen|apply_auto_fallback" paper_batch.py paper_automation sd_institutional_skill.py paper_skill.py doi_batch_utils.py skills/paper-download/SKILL.md
  ```

  Result: no matches (rg exit code 1).

- `git diff --check` result: exit code 0.

## Limitations and manual acceptance status

The fixture is deliberately offline. It validates the project-side file and
state contract only; it cannot prove a user's live Zotero connection, personal
library selection, attachment availability, institutional entitlement, or
login/CAPTCHA interaction. Those remain the Task 8 manual Zotero acceptance
steps and require the user to authorize external application access. No Skill
installation or packaging was performed.

## Offline acceptance review repair

The follow-up review tightened the same end-to-end fixture without changing
product code:

- The two delivered PDF SHA-256 values must equal the distinct project and
  Zotero fixture hashes, so two copies of one source cannot satisfy the test.
- The CSV manifest must contain exactly three rows, and `assertCountEqual`
  requires each expected task ID exactly once.
- The first and second `finalize` calls snapshot all six report files, batch
  state, and delivered PDFs. `final_manifest.csv`, `failed.csv`,
  `run_summary.txt`, `batch_status.csv`, `batch_status.json`, state, and PDF
  files must remain byte-for-byte identical.
- A diagnostic run separated the two finalizations by 2.1 seconds and showed
  that only `final_manifest.xlsx` changed at the ZIP/package metadata level.
  This is expected from a newly created `openpyxl` workbook and is not a
  project-state change. The final test retains both XLSX byte snapshots and
  compares all worksheet values instead of claiming unsupported byte-level
  determinism.

Review verification:

- Diagnostic strict-byte run: one expected failure at the aggregate report
  byte comparison, caused by XLSX package metadata.
- Focused final run: `Ran 1 test in 0.632s`, `OK`.
- Full offline run: `Ran 288 tests in 14.350s`, `OK (skipped=2)`.
- The isolated worktree had no pre-existing uncommitted files before this
  review repair began.
- Live Zotero acceptance remains a later manual step; it is outside this
  offline fixture and was not treated as a test defect.

## Skill installation and live availability check

- The updated personal `paper-download` Skill was installed after a dry run.
- The previous installed Skill was preserved under
  `C:\Users\wkguopro\.codex\skill-backups\paper-download\20260711_055044`.
- The installed and source SHA-256 values both equal
  `83339B36E5B6ADBA3F214187C47CF18AF56B830D107C90EBDF47C06C0036303E`.
- `PAPER_SCRAPER_DOI_ROOT` now points to this verified isolated worktree.
- The first read-only `library_search(entity:"libraries", mode:"list")` call
  returned `No active library available`. No collection, item, tag, attachment,
  or PDF write was attempted. Live acceptance remains safely resumable after
  the user opens Zotero and activates a personal library.
