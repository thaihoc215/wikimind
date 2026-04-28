# WikiMind — Agent Instructions

WikiMind is an LLM-powered wiki tool that maintains itself. It has two modes: a CLI (Mode B, calls an LLM provider directly) and an MCP server (Mode A, the AI assistant IS the LLM). Both write to the same `.wiki/vault/` directory.

See [ARCHITECTURE.md](../ARCHITECTURE.md) for a full architecture walkthrough.

---

## Build & test

```bash
pip install -e .           # install with editable mode
pip install -e ".[dev]"    # add test deps
pip install -e ".[pdf]"    # add optional PDF support

pytest                     # run all 82 tests (no API keys needed — all LLM calls are mocked)
```

Requires Python ≥ 3.11. Entry point: `wikimind.cli:app` (Typer).

---

## Project structure

```
wikimind/
├── cli.py          # Typer CLI — 8 commands, each loads config → WikiStore + LLMClient + Retriever → operation
├── config.py       # TOML loader → typed dataclasses (ProjectConfig, LLMConfig, WikiConfig, PathsConfig)
├── wiki.py         # WikiStore — ALL filesystem ops (read/write pages, index, log, dedup via SHA256)
├── llm.py          # LLMClient + ProviderAdapter (Anthropic / OpenAI / Ollama) — all return (json, in_tok, out_tok)
├── llm_schema.py   # Typed frozen dataclasses + parse_*() validators for all LLM tool outputs
├── retrieval.py    # Retriever protocol + 3 backends: KeywordIndex / BM25 / Qmd
├── server.py       # FastMCP server — 10 tools, path-sandboxed, background qmd embed thread
├── operations/     # Business logic (ingest, query, lint) — no direct LLM calls in CLI commands
└── prompts/        # System prompts + JSON tool schemas for each operation
```

---

## Core pattern: adding a new operation

Every operation follows a strict 3-part structure:

1. **`prompts/X.py`** — `X_SYSTEM_PROMPT` string + `X_TOOL` JSON schema dict
2. **`operations/X.py`** — `def x(store: WikiStore, llm: LLMClient, retriever: Retriever, ...) → XResult`
3. **`cli.py`** — Typer command that loads config, instantiates dependencies, calls `operations.x()`

Operations must never import from `cli.py`. `LLMClient`, `WikiStore`, `Retriever` are injected.

---

## LLM output validation

All LLM responses go through `llm_schema.py` before any filesystem writes. Use the existing typed dataclasses (`IngestToolOutput`, `QueryToolOutput`, `LintToolOutput`) and `parse_*()` validators. Never write LLM output directly to disk without validation — raise `LLMOutputValidationError` on bad output.

---

## WikiStore conventions

- **All wiki paths are relative to `wiki_path`** (e.g., `entities/foo.md`). Absolute paths and `../` are rejected by `_resolve_wiki_relative_path()`.
- **Dedup via SHA256**: `is_already_ingested(source_path)` checks `.wikimind/sources.json`. Call `mark_ingested()` after a successful ingest.
- **`index.md` is the master catalog** — always update it via `update_index(to_add, to_remove)` after writing new pages.
- **`log.md` is append-only** — format: `- [YYYY-MM-DD] action | one-line summary`
- **Wikilinks normalize aggressively**: `[[Entity]]`, `[[entity]]`, and `[[entities/entity.md]]` all resolve to the same page. Bare stems only work if unique.
- Frontmatter is required on every page: `title`, `type`, `tags`, `created`, `updated`.

---

## Retrieval backends

`make_retriever(store, backend, wiki_config, root)` factory in `retrieval.py`. Protocol: `retrieve(query, top_k) → dict[str, str]` (path → content). Default: `bm25`. Fallback from `qmd` → `bm25` if qmd not installed (silent).

---

## MCP server (`server.py`)

- No `LLMClient` — the AI assistant is the LLM in Mode A.
- `wiki_write_page()` sets `_embed_dirty = True` and spawns a background thread for `qmd embed`.
- `wiki_search()` waits for the embed thread before searching.
- All tool paths are validated via `_resolve_wiki_relative_path()` — no escapes.

---

## Test conventions

- All tests use mocked LLM clients — no real API calls, no keys needed.
- Shared fixtures in `tests/conftest.py`: `tmp_wiki` (fresh `WikiStore`), `sample_source` (markdown file), `mock_llm_ingest`, `mock_llm_query`.
- `asyncio_mode = "auto"` — async tests work without explicit `@pytest.mark.asyncio`.
- Tests assert on result dataclass fields (`.pages_created`, `.answer`, etc.) and filesystem state.

---

## Key pitfalls

- **50K char limit per source**: `operations/ingest.py` auto-chunks/summarizes larger files. Don't bypass this.
- **Semantic lint is LLM-costly**: `lint --semantic` makes one LLM call per wiki. Respect `max_budget_usd`.
- **Paths config can be absolute**: `[paths]` in `wikimind.toml` may point outside the project root.
- **Page types are taxonomy only**: `type:` in frontmatter is a convention, not enforced by code (only lint flags missing fields, not wrong types).
- **PDF support is optional**: `pymupdf4llm` must be installed; ingest gracefully degrades without it.

---

## Documentation

| File | Contents |
|------|----------|
| [ARCHITECTURE.md](../ARCHITECTURE.md) | Full data flow, component graph, provider adapter pattern |
| [README.md](../README.md) | CLI usage, config reference, MCP setup for all clients |
| [docs/templates.md](../docs/templates.md) | `--template` flag and wiki folder conventions |
| [docs/search-comparison.md](../docs/search-comparison.md) | Retrieval backend trade-offs |
| [docs/qmd-setup.md](../docs/qmd-setup.md) | qmd hybrid search setup and troubleshooting |

---

## wikimind generate — for OpenCode and VSCode Integration

This project includes `wikimind generate` command to automate setup for AI clients:

```bash
wikimind generate --tool opencode   # Creates/updates AGENTS.md + opencode.json
wikimind generate --tool vscode     # Creates/updates .vscode/mcp.json for Copilot MCP
```

See [[analyses/generate-command]] in the wiki for full details.

---

<!-- wikimind:start -->
# WikiMind Knowledge Base — wikimind

This project uses a persistent wiki in `.wiki/vault/` maintained by LLMs.

## Structure

- `.wiki/vault/index.md` — Master catalog of all wiki pages. **READ THIS FIRST.**
- `.wiki/vault/log.md` — Chronological record of all wiki changes.
- `.wiki/vault/overview.md` — High-level codebase overview.
- `.wiki/vault/modules/` — Source files, classes, functions, components.
- `.wiki/vault/apis/` — Endpoints, interfaces, contracts, schemas.
- `.wiki/vault/patterns/` — Design patterns, architectural decisions, conventions.
- `.wiki/vault/decisions/` — Architecture Decision Records (ADRs).
- `.wiki/vault/sources/` — One summary page per raw source in `.wiki/raw/`.
- `.wiki/vault/analyses/` — Saved query answers, comparisons, syntheses.
- `.wiki/raw/` — Raw source documents. **Immutable — never modify these.**

## When working on this project

Follow this default order (wiki-first):

1. **Before deep-diving into source files or broad code search**, use `wiki_search` first.
2. **If relevant wiki pages exist**, read them with `wiki_read_page` and answer from wiki context.
3. **Only read raw/source files when needed** (wiki is missing details, outdated, or exact code is required).
4. **After answering questions or making discoveries**, save durable outputs with
   `wikimind query --save "your question"` (or write an analysis page via MCP tools).
5. **When answering**, cite wiki pages with [[wikilinks]] whenever possible.
6. **After significant code/source changes**, update affected wiki pages (`wiki_write_page`),
   update index if needed (`wiki_update_index`), and append log (`wiki_append_log`).
   Log entry must be a single bullet line: `- [YYYY-MM-DD] action | one-line summary`
7. **After ingesting new sources**, run `wikimind lint` (and `wikimind lint --semantic` when needed).
8. If paths are customized in `wikimind.toml`, always follow configured paths.
9. Never modify raw source documents in `.wiki/raw/`; treat them as immutable.

## Wiki page format

Every wiki page must have YAML frontmatter:

```yaml
---
title: Page Title
type: module | api | pattern | decision | source | analysis | overview
tags: [tag1, tag2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [sources/source-name]
---
```

Use [[wikilinks]] to cross-reference between pages. When new information
contradicts existing content, note the contradiction explicitly rather than
silently overwriting.

## CLI commands

```bash
wikimind ingest .wiki/raw/file.md    # Process a source into wiki pages
wikimind query "question"            # Ask the wiki a question
wikimind query --save "question"     # Ask and save the answer as a wiki page
wikimind lint                        # Health-check the wiki
wikimind lint --fix                  # Auto-fix wiki issues
wikimind lint --semantic             # Semantic check (contradictions, gaps, source ideas)
```
<!-- wikimind:end -->