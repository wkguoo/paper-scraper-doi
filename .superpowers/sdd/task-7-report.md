# Task 7 Report: Unified Paper Download Skill

## RED baseline

The pre-change `skills/paper-download/SKILL.md` was evaluated by a fresh agent against this user request:

> Process a mixed DOI/title list with the project first, send only failures to Zotero Find Available PDF, minimize manual work, deliver centralized PDFs, and pause once for login/CAPTCHA with only one retry.

Observed gaps:

1. No Zotero tool or Find Available PDF procedure.
2. No handoff from project failures to Zotero.
3. No `zotero_results.csv` contract or centralized PDF reconciliation.
4. No single-pause, single-retry rule.
5. No DOI-first deduplication or conservative title-only matching rule.
6. No batch confirmation strategy for Zotero writes.
7. No resumable behavior when Zotero is unavailable.
8. The frontmatter claimed an unspecified third-party fallback that the body could not execute safely.

The baseline agent could only route to `sd_institutional_skill.py` or `paper_skill.py`, inspect their reports, and stop at unresolved rows. This is the required failing behavior before editing the Skill.

## Implementation status

- Complete.

## TDD evidence

- RED: Added `test_paper_download_skill_documents_batch_zotero_fallback_contract`
  and ran `..\\..\\.venv\\Scripts\\python.exe -m unittest
  tests.test_skills_packaging -v`. The old Skill failed 25 contract assertions
  because it had no `paper_batch.py` sequence, Zotero MCP protocol, result CSV
  contract, or safety constraints.
- GREEN: Replaced the route with the project-first batch protocol, then the
  focused suite passed 18 tests. The full offline suite passed 281 tests with
  2 skipped tests.

## Delivered scope

- Added one-time `manual_retry.csv` pause/resume guidance, header-only
  `zotero_results.csv` handling, Zotero availability checks, temporary
  collection preservation, DOI-first batch deduplication, conservative
  title-only matching, batch confirmation/tagging, and one guarded available-PDF
  script with an undo step.
- Documented the exact five result fields, allowed statuses, attachment-path
  validation, non-destructive final copy, and resumable unavailable-Zotero
  behavior.
- Added English and Chinese beginner instructions plus seven manual QA cases.
- No network, real Zotero, credentials, CAPTCHA automation, original data
  changes, or packaging were used.

## Independent review repair cycle

### Review RED

- CLI: `BatchCliTests` reproduced the false completion message with
  `failed_count=3` and `zotero_fallback_count=2`; 1 of 13 tests failed because
  the old finalize branch always printed `批次已完成`.
- Skill: the forward contract test produced 23 missing assertions covering
  exact collection/search/import/tag parameters, CSV row semantics, personal
  library selection, Unicode normalization, retry result files, compatibility
  statuses, and recoverable incomplete wording.

### Review GREEN

- `paper_batch.py` now reports completion only when both unresolved counters
  are zero. Incomplete finalize still returns 0 after publishing reports, but
  prints `批次未完成且可恢复`, the unresolved count, and the final PDF directory
  without a resume command.
- The Skill now fixes one `libraryID` per attempt, documents exact Zotero calls,
  NFKC/casefold matching, exclusive canonical/retry result files, and the
  distinction between six generated statuses and three parser-only compatible
  statuses.
- Focused results: `BatchCliTests` 13/13 and skill packaging 19/19.
- Full offline result: 283 tests passed, 2 skipped.
- No network, real Zotero, credentials, CAPTCHA automation, source-data changes,
  or packaging were used.
