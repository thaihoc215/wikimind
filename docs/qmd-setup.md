# WikiMind + qmd Setup Guide

> How to configure wikimind to use qmd for semantic/hybrid search.

---

## When to Use qmd

Stay on the default `bm25` backend unless your wiki has grown past ~200 pages.
At that scale, BM25 starts missing relevant pages because they use different words
than the query. qmd adds semantic (vector) search that finds pages by meaning, not
just token overlap. See `docs/search-comparison.md` for the full decision matrix.

| Wiki size | Recommended backend |
|---|---|
| 0–200 pages | `bm25` (default) — no extra setup |
| 200+ pages | `qmd` — enables semantic/hybrid search |

---

## Where qmd Stores Data

qmd is **fully global** — there is no per-project `.qmd/` folder. All storage is
shared across all projects on the machine:

| What | Location |
|---|---|
| Collection registry | `~/.config/qmd/index.yml` |
| All collection data (SQLite DB) | `~/.cache/qmd/index.sqlite` |
| Embedding models | `~/.cache/qmd/models/` |

`XDG_CONFIG_HOME` / `XDG_CACHE_HOME` are respected if set. The env var `QMD_CONFIG_DIR`
overrides the config location entirely.

After setup you can inspect the state with:

```bash
cat ~/.config/qmd/index.yml      # see registered collections
ls ~/.cache/qmd/                 # index.sqlite + models/
```

---

## Installation

```bash
npm install -g @tobilu/qmd
qmd --version
```

### Pre-download Embedding Models

The first `qmd vsearch` or `qmd query` will trigger a model download (~300MB by
default) if the model is not already cached. With the 60s subprocess timeout used
by wikimind, this **silently fails**. Pre-download before using wikimind:

```bash
qmd pull            # download all default models to ~/.cache/qmd/models/
qmd pull --refresh  # force re-download
```

> **Note:** `qmd embed` does NOT download the model if there is nothing to embed
> (vacuously exits early with "All content hashes already have embeddings"). Always
> use `qmd pull` for the initial setup.

---

## Per-Project Setup

### Step 1 — Register the vault as a collection

```bash
# Run from inside the project directory (or anywhere — the path is what matters)
qmd collection add .wiki/vault/ --name my-project-wiki
```

This writes an entry to `~/.config/qmd/index.yml`. You can verify:

```bash
qmd collection list
qmd collection info my-project-wiki
```

### Step 2 — Embed the vault

```bash
qmd embed
```

Writes embeddings into `~/.cache/qmd/index.sqlite`. Re-run after bulk ingests if
you need fresh embeddings immediately (wikimind handles this automatically — see
[Auto-embed After Ingest](#auto-embed-after-ingest) below).

### Step 3 — Configure wikimind.toml

```toml
[wiki]
retrieval_backend = "qmd"
qmd_mode          = "vsearch"    # "vsearch" | "query"
qmd_bin           = "qmd"        # full path if qmd is not on PATH
```

---

## Multiple Projects: The Cross-Collection Problem

Because all collections share a single `~/.cache/qmd/index.sqlite`, running
`qmd vsearch <query>` without a `-c` flag searches **all** registered collections
by default (all entries in `index.yml` where `includeByDefault` is not `false`).

wikimind's `QmdRetriever` currently does **not** pass `-c <collection-name>`, which
means on a machine with multiple projects registered, search results will include
pages from other projects' wikis.

### Workaround: exclude other collections from default search

```bash
# Mark all collections you do NOT want included in default search
qmd collection update other-project-wiki --exclude
```

This sets `includeByDefault: false` in `~/.config/qmd/index.yml` for that entry.
Only collections without this flag are searched by default.

```bash
# Re-enable a collection for default search
qmd collection update other-project-wiki --include
```

### Verify scope

```bash
# Confirm only the right collection is searched from any directory
qmd vsearch "test query" --json
```

Check that returned `file` URIs are all under `qmd://<your-collection-name>/`.

---

## Full wikimind.toml Example (qmd mode)

```toml
[project]
name = "my-project"
template = "general"

[paths]
raw  = ".wiki/raw/"
wiki = ".wiki/vault/"

[llm]
provider    = "anthropic"
model       = "claude-sonnet-4-20250514"
api_key_env = "ANTHROPIC_API_KEY"

[wiki]
required_frontmatter = ["title", "type", "tags", "created", "updated"]
retrieval_backend    = "qmd"
qmd_mode             = "vsearch"   # "vsearch" | "query"
qmd_bin              = "qmd"       # full path if not on PATH

[wiki.categories]
entities  = "People, organizations, tools, systems"
concepts  = "Ideas, theories, patterns, principles"
sources   = "One summary per raw source"
analyses  = "Saved queries, comparisons, syntheses"
```

### qmd_mode options

| Value | What runs | Quality | Speed |
|---|---|---|---|
| `vsearch` | Vector/semantic search only | Medium–High | ~500ms–3s |
| `query` | BM25 + vector + LLM re-ranking | Highest | ~1s–10s |
| `search` | BM25 only (same as built-in bm25) | Medium | ~200–800ms |

`vsearch` is the recommended default. Use `query` if result quality matters more than
latency (large wikis, complex queries). Avoid `search` — it adds subprocess overhead
with no quality gain over the built-in `bm25` backend.

---

## Auto-embed After Ingest

### CLI mode — automatic

When `retrieval_backend = "qmd"`, `wikimind ingest` automatically runs `qmd embed`
after the batch completes. No manual step needed.

```bash
wikimind ingest .wiki/raw/my-file.md
# → writes pages → qmd embed runs automatically ✓
```

### MCP mode — automatic (background)

When an AI assistant writes a page via `wiki_write_page`, the server starts `qmd embed`
in a background thread and returns immediately. If an embed is already running, the dirty
flag stays set so the next search triggers a follow-up embed for pages written during
the first run.

```
AI calls wiki_write_page → file written → background embed starts → returns immediately ✓
AI calls wiki_write_page → file written → embed already running  → returns immediately ✓
AI calls wiki_search     → waits for background embed if still running → search ✓
```

Key design choices:
- Dirty flag is cleared **before** the subprocess starts. A write arriving mid-embed
  re-sets the flag, guaranteeing a follow-up embed for those pages.
- `wiki_search` waits for the background thread before querying.
- Embed is best-effort: if qmd times out (120s), search continues with stale index.

### Summary

| How pages are written | qmd embed triggered | Semantic search up to date? |
|---|---|---|
| `wikimind ingest` (CLI) | After each batch | Yes ✓ |
| `wikimind watch` (CLI) | After each batch | Yes ✓ |
| `wiki_write_page` (MCP / AI) | Lazy, before next search | Yes ✓ |

Only run `qmd embed` manually for the initial setup or if you add/edit files outside
of wikimind entirely.

---

## Troubleshooting

**qmd binary not found**

```
Warning: qmd binary 'qmd' not found on PATH. Falling back to BM25 retriever.
```

Install qmd or set the full path:

```toml
[wiki]
qmd_bin = "/usr/local/bin/qmd"
```

**qmd returns empty results**

- Verify the collection is registered: `qmd collection list`
- Run `qmd embed` and confirm it processes files (not an early "all embedded" exit)
- Run `qmd vsearch "test" --json` manually to see raw output

**First search times out / hangs**

The model was not pre-downloaded. Run `qmd pull` to download models before starting
the wikimind MCP server. The 60s timeout in `QmdRetriever` is not enough for a
~300MB first-time download.

**Results contain pages from other projects**

Other collections are included in default search. Exclude them:

```bash
qmd collection update other-project-name --exclude
```
