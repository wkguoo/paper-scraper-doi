# Domain Docs

This is a single-context repository.

## Before exploring or changing code

- Read root `CONTEXT.md` if it exists.
- Read relevant decisions in `docs/adr/` if that directory exists.
- If neither exists, proceed without creating them unless a task explicitly resolves durable domain terminology or an architectural decision.

## Vocabulary

Use terminology defined by any available context or ADR documents in issue titles, tests, code, and documentation. For this project, keep the distinction clear between project-side batch processing, the local bridge queue, Zotero plugin processing, and final PDF publication.

## Layout

Future durable domain context belongs at root `CONTEXT.md`; architecture decisions belong under `docs/adr/`.
