# Design: Remove automatic wiki-log writing

**Date:** 2026-07-06
**Status:** Approved (scope), in implementation

## Goal

After a wiki change (create / update / ingest / query-save), WikiMind should no
longer write to `log.md` automatically, and the AI (Mode A) should no longer be
instructed to append a log entry. The log capability stays available for
**explicit / manual** use.

## Scope (decided with user)

Remove auto-log at **both** the AI-instruction layer (Mode A) and the CLI layer
(Mode B). Keep the plumbing so a user can still log manually:

- **Keep:** `WikiStore.append_log()`, MCP tool `wiki_append_log`, `log.md` file,
  lint's handling of `log.md` as a protected nav page.
- **Remove:** automatic calls to `append_log()`, and the workflow instruction
  that mandates appending a log entry.
- **Remove (recommended):** the now-dead `log_entry` field from the ingest LLM
  contract, so the model no longer generates unused output.

## Changes

### 1. CLI auto-log (Mode B)
- `operations/ingest.py`: delete the `append_log(log_entry)` block.
- `operations/query.py`: delete the `store.append_log(...)` call in save path.

### 2. Ingest LLM contract (remove dead `log_entry`)
- `prompts/ingest.py`: drop `log_entry` from `required` and from `properties`.
- `llm_schema.py`: drop `log_entry` from `IngestToolOutput` and its parse/build.
- `tests/conftest.py` + `tests/test_ingest.py`: drop `log_entry` from fixtures.

### 3. AI-instruction layer (drop mandatory append-log step)
Edit step 6 in each workflow doc — remove `and append log (wiki_append_log)`
and the following "Log entry must be a single bullet line…" line. Keep the
`log.md` entry in the structure listing (the file still exists).
- Root `CLAUDE.md`
- `cli.py` (generated CLAUDE.md block)
- `templates/{book,research,code,general}/CLAUDE.md`

### 4. Docs
- `README.md` / `CHEATSHEET.md`: keep `wiki_append_log` in the tool tables (the
  tool still exists); no mandatory-workflow wording to remove.

### 5. Tests (invert to regression guards)
- `test_ingest_appends_log` → assert `log.md` is **not** grown by ingest.
- `test_query_save_appends_log` → assert `log.md` is **not** grown by query-save.

## Non-goals
- Not removing the `wiki_append_log` tool, `append_log()`, or `log.md`.
- Not changing lint behavior around `log.md`.
