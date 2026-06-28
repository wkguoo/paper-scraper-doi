# Failure Reasons

Use this reference when explaining `doi_intake_preview.csv`, `doi_batch_failed.csv`, `pdf_download_report.csv`, `supplement_download_report.csv`, or `run_summary.txt`.

## Intake and metadata

- `metadata_confidence_below_threshold`: The title-only match was too uncertain. Ask for DOI, full title, journal, year, volume, and pages.
- `insufficient_bibliographic_context`: The text looked like a title but lacked enough citation context. Ask for DOI or a fuller citation.
- `not_probable_title`: The copied text is likely a note, heading, or comment rather than a paper title.
- `metadata_not_found`: Crossref/OpenAlex/search fallback did not confirm a DOI.
- `duplicate`: The same DOI or near-identical title was already kept.

## ScienceDirect resolution

- Non-`10.1016/...` DOI values are often not ScienceDirect/Elsevier and may need the legal OA workflow instead.
- DOI resolution failure means the DOI did not lead to a ScienceDirect article page or the network request failed.

## PDF download

- `failed`: Inspect `reason`; common causes are expired cookies, no institutional entitlement, CAPTCHA, 403, rate limiting, or an inaccessible PDF endpoint.
- `skipped`: Usually already downloaded or intentionally not requested.
- `not_requested`: The run was `--preflight`, `--dry-run`, or `--no-download-pdfs`.
- `--dry-run`: ScienceDirect DOI metadata/PII resolution without PDF download. Do not present it as the first safe workflow for messy beginner input; use `--beginner --preflight` first.

## Supplement download

- `success`: A supplementary file was saved under `supplements\<article-stem>\`.
- `failed`: Inspect `reason`; common causes are an attachment link returning an HTML login page, missing entitlement, 403, or a non-file response.
- `skipped`: The supplementary file already exists.
- `not_found`: The article page did not expose detectable supplementary links. Do not treat this as a PDF failure.

`supplement_download_report.csv` and `supplements\` are generated only when PDF download and supplement download are both active. They are not expected from `--preflight`, `--dry-run`, `--no-download-pdfs`, or `--no-download-supplements` runs.

Never hide unresolved rows. Report them as the next manual action.
