<!-- wikimind:start -->
# WikiMind Knowledge Base — {{PROJECT_NAME}}

This project uses a persistent wiki in `.wiki/vault/` maintained by LLMs.

## Structure

- `.wiki/vault/index.md` — Master catalog of all wiki pages. Start here when the user asks you to use the wiki.
- `.wiki/vault/log.md` — Chronological record of all wiki changes.
- `.wiki/vault/overview.md` — High-level research overview.
- `.wiki/vault/papers/` — Academic papers, preprints, technical reports.
- `.wiki/vault/concepts/` — Theories, methods, frameworks, algorithms.
- `.wiki/vault/authors/` — Researchers, labs, institutions.
- `.wiki/vault/datasets/` — Datasets, benchmarks, corpora.
- `.wiki/vault/sources/` — One summary page per raw source in `.wiki/raw/`.
- `.wiki/vault/analyses/` — Literature reviews, comparisons, syntheses.
- `.wiki/raw/` — Raw source documents. **Immutable — never modify these.**

## When to use the wiki

The wiki is **opt-in**: interact with WikiMind only when the user asks for it
(e.g. they mention the wiki / WikiMind, ask to look something up in it, or ask to save or update it).

1. **Do not consult the wiki by default.** For ordinary tasks, work directly from the source code
   and project files — do not call `wiki_search`, `wiki_read_index`, or `wiki_read_page` unless the user asks.
2. **When the user asks you to use the wiki**, search it with `wiki_search`, read relevant pages with
   `wiki_read_page`, and fall back to source files only if the wiki is missing details or outdated.
3. **When answering from the wiki**, cite wiki pages with [[wikilinks]].
4. **Write to the wiki only on explicit user request.** Do not save answers,
   discoveries, analyses, or code-change notes unless the user asks.
5. **When explicitly asked to save or update wiki content**, always go through the wiki MCP tools —
   `wiki_write_page`, `wiki_move_page` (move/rename), `wiki_delete_page`, `wiki_update_index` — never
   `mv`/`sed`/`cat >>` or plain file writes: only these refresh the search index.
6. **After ingesting new sources**, run `wikimind lint` (and `wikimind lint --semantic` when needed).
7. If paths are customized in `wikimind.toml`, always follow configured paths.
8. Never modify raw source documents in `.wiki/raw/`; treat them as immutable.

## Wiki page format

Every wiki page must have YAML frontmatter:

```yaml
---
title: Page Title
type: paper | concept | author | dataset | source | analysis | overview
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
wikimind ingest .wiki/raw/paper.pdf  # Process a PDF paper into wiki pages
wikimind ingest .wiki/raw/notes.md   # Process markdown notes
wikimind query "question"            # Ask the wiki a question
wikimind query --save "question"     # Ask and save the answer as a wiki page
wikimind lint                        # Health-check the wiki
wikimind lint --fix                  # Auto-fix wiki issues
wikimind lint --semantic             # Semantic check (contradictions, gaps, source ideas)
```
<!-- wikimind:end -->
