# Domain Docs

This is a single-context repository.

## Before exploring or changing code

- Read root `CONTEXT.md` if it exists.
- Read relevant decisions in `docs/adr/` if that directory exists.
- If neither exists, proceed without creating them unless a task explicitly resolves durable domain terminology or an architectural decision.

## Vocabulary

Use terminology defined by any available context or ADR documents in issue titles, tests, code, and documentation. For this project, keep the distinction clear between project-side batch processing, the local bridge queue, Zotero plugin processing, and final PDF publication.

## Delivery PDF naming

Successful PDFs in the user-facing `pdfs/` folder use **`年份-第一作者姓-题名.pdf`**, chosen at download/publish time (see root `AGENTS.md` “PDF Delivery Naming Rule”). Stage/cache names may differ; delivery copies must not remain `0000-Unknown-...` when metadata can be resolved.

## Limited OA recovery

Optional `paper_batch.py recover-oa` runs a **bounded** OA/repo recovery for unsupported rows (see root `AGENTS.md`). It is not multi-source deep search: no default browser CDP, host negative cache, per-DOI time budget.

## Layout

Future durable domain context belongs at root `CONTEXT.md`; architecture decisions belong under `docs/adr/`.
