# WikiMind

An LLM-powered wiki that maintains itself. Drop in source files, ask questions,
get a structured, interlinked knowledge base that grows richer with every source you add.

> Inspired by [Andrej Karpathy's LLM wiki idea](idea.md): instead of re-deriving knowledge
> from raw documents on every question (RAG), the LLM incrementally builds and maintains a
> persistent wiki. The wiki is a **compounding artifact**.

---

## How it works

```
Raw sources (you add)  →  Wiki (LLM writes)  →  You read + explore
      .wiki/raw/               .wiki/vault/          Obsidian / any editor
```

Three layers:
1. **`.wiki/raw/`** — your source documents (articles, papers, notes). LLM reads, never modifies.
2. **`.wiki/vault/`** — LLM-generated markdown: summaries, entity pages, concept pages, cross-references.
3. **Schema/instructions file** — tells the AI how the wiki is structured and what conventions to follow.
   - Claude Code → `CLAUDE.md`
   - GitHub Copilot → `.github/copilot-instructions.md`
   - OpenCode / Cursor / others → `AGENTS.md` or tool-specific equivalent

   `wikimind init` generates `CLAUDE.md` by default. Copy or symlink as needed for your tool.

---

## Two modes

| Mode | How | API key? |
|------|-----|----------|
| **A — MCP (any AI assistant)** | Your AI client reads the schema file and uses WikiMind MCP tools (`wiki_read_page`, `wiki_write_page`, etc.) to maintain the wiki as part of its normal work. Works with Claude Code, GitHub Copilot, Cursor, OpenCode, and any MCP-compatible client. | Not needed for Claude Code; depends on client for others |
| **B — CLI standalone** | Run `wikimind ingest/query/lint` directly. WikiMind calls your configured LLM provider. | Depends on provider |

Both modes write to the same wiki directory and are fully compatible.

---

## Installation

### From source (development)

```bash
git clone <repo>
cd wikimind
python -m venv .venv # macOS / Linux
py -m venv .venv # Windows

# Activate
source .venv/bin/activate        # macOS / Linux / Git Bash
source .venv/Scripts/activate           # Windows PowerShell / cmd

pip install -e .
pip install -e ".[pdf]"          # optional: adds PDF ingestion support
```

The `wikimind` command works while the venv is active. To use it across all your
projects without activating a venv every session, install via `pipx` instead:

```bash
pip install pipx
pipx install -e ~/path/to/wikimind   # permanent global CLI
```

### From a wheel (distribute to other machines)

Build once from the repo:

```bash
python -m pip install --upgrade build
python -m build
# → dist/wikimind-0.1.0-py3-none-any.whl
```

Install anywhere from the wheel:

```bash
# Recommended: isolated global CLI
pipx install dist/wikimind-0.1.0-py3-none-any.whl

# Alternative: inside a venv
pip install dist/wikimind-0.1.0-py3-none-any.whl
```

Helper build scripts are in `scripts/` (`build-wheel.sh` for macOS/Linux/Git Bash,
`build-wheel.ps1` for PowerShell).

---

## Quick start

### Mode A — MCP (AI assistant)

```bash
cd my-project
wikimind init --name "My Research"
# Creates: .wiki/, CLAUDE.md, wikimind.toml, .mcp.json
cp ~/articles/paper.md .wiki/raw/
```

Then connect your AI client (see [MCP setup](#mcp-setup-for-ai-clients) below) and tell it:
> "Please ingest `.wiki/raw/paper.md` into the wiki"

The AI reads the schema file and uses WikiMind tools — no `ANTHROPIC_API_KEY` needed
when using Claude Code (it IS the LLM). Other clients may require their own key.

### Mode B — CLI

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or OPENAI_API_KEY for OpenAI

wikimind init --name "AI Safety Research"
cp ~/papers/alignment.md .wiki/raw/
wikimind ingest .wiki/raw/alignment.md
wikimind query "What are the key arguments about AI alignment?"
wikimind query --save "Compare the methodologies across papers"
wikimind lint
```

---

## Commands

### `wikimind init`

```bash
wikimind init                          # uses directory name
wikimind init --name "My Research"
wikimind init --template research      # general (default) | code | research | book
```

Creates: `.wiki/raw/`, `.wiki/vault/`, `CLAUDE.md`, `wikimind.toml`, `.mcp.json`.

- `CLAUDE.md` — schema/instructions for Claude Code. For other AI tools, copy or symlink:
  - GitHub Copilot: `cp CLAUDE.md .github/copilot-instructions.md`
  - OpenCode / generic: `cp CLAUDE.md AGENTS.md`
  - Cursor: `cp CLAUDE.md .cursorrules`
- If `CLAUDE.md` already exists, `wikimind init` appends its wiki section rather than overwriting.

---

### `wikimind ingest`

```bash
wikimind ingest .wiki/raw/article.md          # ingest a file
wikimind ingest .wiki/raw/                    # ingest all files in raw/
wikimind ingest .wiki/raw/article.md --dry-run   # preview without writing
wikimind ingest .wiki/raw/article.md --force     # re-ingest even if unchanged
```

What happens: read source → find relevant wiki pages (via retrieval backend) → one LLM call → write pages → update `index.md` + `log.md` → record hash (skips unchanged files on re-run).

Large files (>50K chars) are auto-chunked and summarized first.  
If `retrieval_backend = "qmd"`, runs `qmd embed` automatically after ingest to keep the search index current.

---

### `wikimind query`

```bash
wikimind query "What are the key themes?"
wikimind query "How does X relate to Y?" --save       # save answer as wiki page
wikimind query "Compare methodologies" --save --top-k 15
```

Returns answer with `[[wikilink]]` citations, confidence level, and knowledge gaps.
`--save` writes the answer to `wiki/analyses/` so good syntheses compound in the wiki.

---

### `wikimind lint`

```bash
wikimind lint             # structural checks (no LLM)
wikimind lint --fix       # auto-fix index desync + broken link stubs
wikimind lint --semantic  # + one LLM call: contradictions, missing pages, source suggestions
```

Structural checks: orphan pages, broken links, index desync, missing frontmatter, stale sources.

---

### `wikimind serve`

```bash
wikimind serve                    # stdio transport (default, used by Claude Code)
wikimind serve --transport sse    # HTTP/SSE transport (for Cursor, Copilot, other clients)
```

Starts the MCP server that exposes WikiMind tools to AI assistants. You don't run
this manually — your AI client starts it automatically via its MCP config.

**MCP tools exposed:**

| Tool | Description |
|------|-------------|
| `wiki_read_index` | Read `index.md` — start here |
| `wiki_read_page` | Read a page by path |
| `wiki_search` | Find relevant pages by query (uses configured retrieval backend) |
| `wiki_list_pages` | List all page paths |
| `wiki_write_page` | Create or update a page |
| `wiki_update_index` | Add/remove index entries |
| `wiki_append_log` | Append to `log.md` |
| `wiki_status` | Wiki stats |

Read/write paths are sandboxed to the configured wiki directory — `../` and absolute paths are rejected.

---

### `wikimind status` / `wikimind cost` / `wikimind watch`

```bash
wikimind status           # page count, source count, last updated, paths
wikimind cost             # cumulative LLM token usage (last 10 runs)
wikimind cost --last 20
wikimind watch            # auto-ingest new/changed files in raw/ every 5s
wikimind watch --interval 30
```

---

## MCP setup for AI clients

WikiMind's MCP server works with any MCP-compatible AI assistant. Two transport modes:
- **stdio** (default) — client spawns the server as a subprocess. Used by Claude Code, Cursor, OpenCode.
- **SSE** — client connects to a running HTTP server. Used by some web-based clients.

`wikimind init` auto-generates `.mcp.json` for Claude Code. For other tools, configure manually using the examples below. Replace `wikimind` with the full venv path if not installed globally.

---

### Claude Code

Reads `.mcp.json` from the project root automatically — nothing extra needed after `wikimind init`.

**`.mcp.json`** (auto-generated, edit if needed):
```json
{
  "mcpServers": {
    "wikimind": {
      "command": "wikimind",
      "args": ["serve"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

Also copy the schema file so Claude reads the wiki instructions:
```bash
# Already created by wikimind init — no action needed
# CLAUDE.md is read automatically by Claude Code
```

---

### GitHub Copilot (VS Code)

**Step 1** — Add MCP server to VS Code settings:

`.vscode/mcp.json` (workspace) or user `settings.json`:
```json
{
  "servers": {
    "wikimind": {
      "type": "stdio",
      "command": "wikimind",
      "args": ["serve"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

**Step 2** — Copy the schema file to the Copilot instructions location:
```bash
mkdir -p .github
cp CLAUDE.md .github/copilot-instructions.md
```

Copilot reads `.github/copilot-instructions.md` automatically for repo-level instructions.

---

### Cursor

**Step 1** — Add MCP server to `.cursor/mcp.json` (project) or global Cursor MCP settings:
```json
{
  "mcpServers": {
    "wikimind": {
      "command": "wikimind",
      "args": ["serve"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

**Step 2** — Copy the schema file:
```bash
cp CLAUDE.md .cursorrules
```

---

### OpenCode

**Step 1** — Add MCP server to `opencode.json` in the project root:
```json
{
  "mcp": {
    "wikimind": {
      "type": "local",
      "command": ["wikimind", "serve"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

**Step 2** — Copy the schema file:
```bash
cp CLAUDE.md AGENTS.md
```

OpenCode reads `AGENTS.md` automatically.

---

### Other MCP clients (HTTP/SSE)

For clients that connect to a running HTTP server rather than spawning a subprocess:

```bash
# Start the server once, keep it running
wikimind serve --transport sse
# Listening at http://localhost:8000/sse
```

Point your client at `http://localhost:8000/sse`.

---

> **Schema file tip:** The generated `CLAUDE.md` contains the wiki structure, page
> format, and workflow instructions. Whichever file your AI tool reads (see table above),
> make sure it has this content — that's what makes the AI maintain the wiki correctly.

---

## Configuration

### `wikimind.toml`

```toml
[project]
name = "My Research"
template = "general"

[paths]
raw = ".wiki/raw/"
wiki = ".wiki/vault/"

[llm]
provider = "anthropic"              # anthropic | openai | ollama
model = "claude-sonnet-4-20250514"
api_key_env = "ANTHROPIC_API_KEY"   # OPENAI_API_KEY for openai; optional for ollama
# base_url = ""                      # optional: custom API base URL
# max_tokens_per_call = 8192
# max_budget_usd = 5.0               # per-session spending cap (0 = no limit)

[wiki]
required_frontmatter = ["title", "type", "tags", "created", "updated"]
retrieval_backend = "bm25"          # bm25 | index_keyword | qmd
# qmd_mode = "vsearch"               # search | vsearch | query (default: vsearch)
# qmd_bin = "qmd"                    # path to qmd binary if not on PATH

[wiki.categories]
entities = "People, organizations, tools, systems"
concepts = "Ideas, theories, patterns, principles"
sources = "One summary per raw source"
analyses = "Saved queries, comparisons, syntheses"
```

**Retrieval backends:**

| Backend | Algorithm | Best for | Dependencies |
|---------|-----------|----------|--------------|
| `index_keyword` | Keyword overlap on `index.md` | < 50 pages, fastest | None |
| `bm25` | Okapi BM25 over all pages | 50–200 pages (default) | None |
| `qmd` | Hybrid: BM25 + vector + local LLM re-ranking | 200+ pages | Node.js + qmd CLI |

**qmd search modes** (set via `qmd_mode`):

| Mode | What it does |
|------|-------------|
| `vsearch` | Vector/semantic search — finds conceptually related pages even with different words (default) |
| `query` | Full hybrid: BM25 + vector + local LLM re-ranking — best quality, slowest |
| `search` | BM25 lexical only — same algorithm as our built-in BM25 backend, no benefit over it |

All qmd modes run **fully locally** — no extra API key required. qmd downloads a
local GGUF model on first run for embeddings and re-ranking.

**qmd one-time setup:**

```bash
# 1. Install qmd globally (requires Node.js)
npm install -g @tobilu/qmd
# or: bun install -g @tobilu/qmd

# 2. Register the wiki vault as a qmd collection (once per project)
cd your-project
qmd collection add .wiki/vault/ --name wiki

# 3. Pre-compute embeddings
qmd embed
```

**After setup**, set in `wikimind.toml`:

```toml
[wiki]
retrieval_backend = "qmd"
# qmd_mode = "vsearch"   # default — change to "query" for best quality
```

`wikimind ingest` automatically reruns `qmd embed` after each ingest batch so the
index stays current. You only need to run `qmd embed` manually after bulk changes.

**Fallback:** If `retrieval_backend = "qmd"` but qmd is not installed, WikiMind
automatically falls back to BM25 with a warning — no crash, no broken workflow.

**Provider notes:**
- `anthropic` — requires `ANTHROPIC_API_KEY`
- `openai` — requires `OPENAI_API_KEY` (`api_key_env = "OPENAI_API_KEY"`)
- `ollama` — local, no API key required

Switch provider example:

```toml
[llm]
provider = "ollama"
model = "llama3.1"
```

---

## Wiki structure

```
.wiki/vault/
├── index.md          # master catalog — LLM reads this first
├── log.md            # append-only change history
├── overview.md       # high-level synthesis
├── entities/         # people, organizations, tools, systems
├── concepts/         # ideas, theories, patterns, principles
├── sources/          # one summary per raw source
└── analyses/         # saved query answers, comparisons, syntheses
```

Every page has YAML frontmatter:

```yaml
---
title: Page Title
type: entity | concept | source | analysis | overview
tags: [tag1, tag2]
created: 2026-04-09
updated: 2026-04-09
sources: [sources/source-name]
---
```

Pages cross-reference each other with `[[wikilinks]]`. The pre-built link graph is
what makes the wiki valuable — not re-derived on every query.

---

## Tips

- **Browse in Obsidian** — open `.wiki/vault/` as an Obsidian vault. Graph view, clickable wikilinks, visible orphans.
- **Save good answers** — `wikimind query --save "..."` files the answer back as a wiki page. Don't let syntheses disappear into terminal history.
- **git init the wiki** — the wiki is just markdown. `git diff` shows what changed, `git checkout` reverts it.
- **`--dry-run` before trusting a new source** — preview what the LLM would write without committing.
- **Run lint periodically** — `wikimind lint --fix` handles mechanical fixes as the wiki grows.

---

## Roadmap

| Feature | Status |
|---------|--------|
| `ingest`, `query`, `lint`, `serve`, `watch`, `cost`, `status` | Done |
| `init` — templates: general, code, research, book | Done |
| MCP server — works with Claude Code, GitHub Copilot, Cursor, OpenCode | Done |
| Retrieval backends: `bm25`, `index_keyword` | Done |
| `qmd` hybrid/semantic search backend (vector + LLM re-ranking, fully local) | Done |
| MCP `wiki_search` uses configured retrieval backend | Done |
| Dedup (skip unchanged sources), large file chunking, PDF support | Done |
| Provider adapters: Anthropic / OpenAI / Ollama | Done |
| Budget guard (`max_budget_usd`) | Done |
| PyPI publish | Planned |

See [GAPS.md](GAPS.md) for the full gap analysis and planned improvements.
