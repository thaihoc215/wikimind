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

By default qmd is **global** — config and index live in your home directory and
are shared across every project on the machine:

| What | Location |
|---|---|
| Collection registry | `~/.config/qmd/index.yml` |
| All collection data (SQLite DB) | `~/.cache/qmd/index.sqlite` |
| Embedding models | `~/.cache/qmd/models/` |

`XDG_CONFIG_HOME` / `XDG_CACHE_HOME` are respected if set. The env var `QMD_CONFIG_DIR`
overrides the config location entirely.

Two ways to scope storage per project:

| Approach | Where it lives | How wikimind uses it |
|---|---|---|
| **Named index** — `qmd --index <name> ...` | `~/.config/qmd/<name>.yml` | **What wikimind does.** `init`, `ingest` and the MCP server all pass `--index <project.name>` automatically. |
| **Project-local index** — `qmd init` | `.qmd/index.yml` + `.qmd/index.sqlite` in the project | Not used by wikimind. Note that a checked-in `.qmd/index.yml` is trust-gated (see [Trust and checked-in config](#trust-and-checked-in-config)). |

Because wikimind uses a named index per project, each project's collection registry
is a separate file and cross-project bleed is not possible by default.

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
qmd collection show my-project-wiki
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
qmd_mode          = "vsearch"    # "vsearch" | "query" | "search"
qmd_bin           = "qmd"        # full path if qmd is not on PATH

# Optional, only applied when qmd_mode = "query" (the only mode that reranks):
# qmd_no_rerank       = true     # skip LLM reranking — much faster on CPU
# qmd_candidate_limit = 20       # max candidates to rerank (qmd default: 40)
```

---

## Multiple Projects: Search Scoping

Run bare `qmd vsearch <query>` and it searches **every** registered collection in
that index (all entries where `includeByDefault` is not `false`). On a machine with
several projects registered, that would mix other projects' pages into your results.

wikimind avoids this on two levels, with no setup on your part:

1. **`--index <project.name>`** — each project gets its own collection registry file
   (`~/.config/qmd/<project>.yml`), so other projects are not even visible.
2. **`-c <project.name>`** — `QmdRetriever` also scopes the search to the project's
   own collection by name.

If you register extra collections inside a project's index by hand, exclude the ones
you do not want in unscoped searches:

```bash
qmd collection exclude other-collection   # sets includeByDefault: false
qmd collection include other-collection   # re-enable
```

### Verify scope

```bash
# Confirm only the right collection is searched from any directory
qmd --index my-project vsearch "test query" --format json
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
qmd_mode             = "vsearch"   # "vsearch" | "query" | "search"
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

## Trust and Checked-in Config

Since qmd 2.8.3, a project-local `.qmd/index.yml` — the kind that travels with a
`git clone` — is **not trusted automatically**. Three fields in it can reach outside
the project and are gated:

- `update` — a bash command qmd would run on your machine
- `collections.*.path` — pointing outside the project directory
- `models.embed` / `models.rerank` / `models.generate` — non-default model URIs

On a terminal, qmd lists the gated fields and asks; approvals are recorded in
`~/.config/qmd/trusted.json`. **With no terminal — agents, CI, and the wikimind MCP
server — those fields are skipped** and in-project indexing continues.

```bash
qmd trust           # review and approve this project's gated fields
qmd trust list      # show every approved project config
qmd trust revoke    # drop the approval for this project
```

Set `QMD_TRUST_LOCAL_CONFIG=1` for CI that should allow them unattended.

**This does not affect wikimind's normal operation.** wikimind writes to a *named*
index (`~/.config/qmd/<project>.yml`), and your own `~/.config/qmd/*.yml` files are
never gated. Every qmd subprocess wikimind spawns also runs with stdin closed, so a
trust prompt can never block it — the gated fields are simply skipped.

The one thing to know: if your project has its own checked-in `.qmd/index.yml` and
you expect its `update` hook or an out-of-project collection path to work, run
`qmd trust` once by hand. wikimind will not do it for you.

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
- Run `qmd doctor` to check the index and model cache
- Run `qmd vsearch "test" --format json` manually to see raw output

**First search times out / hangs**

The model was not pre-downloaded. Run `qmd pull` to download models before starting
the wikimind MCP server. The 60s timeout in `QmdRetriever` is not enough for a
~300MB first-time download.

**Results contain pages from other projects**

Other collections in the same index are included in unscoped search. Exclude them:

```bash
qmd collection exclude other-collection-name
```
