<!-- wikimind:start -->
# WikiMind Knowledge Base — {{PROJECT_NAME}}

This project uses a persistent wiki in `.wiki/vault/` maintained by LLMs.

## Structure

- `.wiki/vault/index.md` — Master catalog of all wiki pages. **READ THIS FIRST.**
- `.wiki/vault/log.md` — Chronological record of all wiki changes.
- `.wiki/vault/overview.md` — High-level book overview and synopsis.
- `.wiki/vault/chapters/` — Chapter summaries and key events.
- `.wiki/vault/characters/` — Character profiles and development arcs.
- `.wiki/vault/themes/` — Major themes, motifs, and symbols.
- `.wiki/vault/quotes/` — Notable passages and excerpts.
- `.wiki/vault/sources/` — One summary page per raw source in `.wiki/raw/`.
- `.wiki/vault/analyses/` — Saved query answers, character analyses, thematic studies.
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
type: chapter | character | theme | quote | source | analysis | overview
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
wikimind ingest .wiki/raw/chapter.md # Process a chapter into wiki pages
wikimind query "question"            # Ask the wiki a question
wikimind query --save "question"     # Ask and save the answer as a wiki page
wikimind lint                        # Health-check the wiki
wikimind lint --fix                  # Auto-fix wiki issues
wikimind lint --semantic             # Semantic check (contradictions, gaps, source ideas)
```
<!-- wikimind:end -->
