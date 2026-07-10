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
