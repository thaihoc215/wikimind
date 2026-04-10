# WikiMind

An LLM-powered wiki that maintains itself. Drop in source files, ask questions,
get a structured, interlinked knowledge base that grows richer with every source
you add.

> Inspired by [Andrej Karpathy's LLM wiki idea](idea.md): instead of re-deriving
> knowledge from raw documents on every question (RAG), the LLM incrementally
> builds and maintains a persistent wiki. The wiki is a compounding artifact.

---

## How it works

```
Raw sources (you add)   →   Wiki (LLM writes)   →   You read + explore
      raw/                      wiki/                   Obsidian / any editor
```

Three layers:
1. **`.wiki/raw/`** — your source documents (articles, papers, notes). Immutable — LLM reads, never modifies.
2. **`.wiki/vault/`** — LLM-generated markdown files: summaries, entity pages, concept pages, cross-references.
3. **`CLAUDE.md`** — the "schema": tells the LLM how the wiki is structured and what conventions to follow.

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed architecture, data flows, and MCP tool workflows.

---

## Two modes

### Mode A — Claude Code + MCP (no API key needed)

Open your project in Claude Code. WikiMind registers as an MCP server via
`.mcp.json`. Claude Code reads `CLAUDE.md`, understands the wiki structure, and
uses MCP tools (`wiki_read_page`, `wiki_write_page`, etc.) to maintain the wiki
as part of its normal work.

**Claude Code IS the LLM** — no separate `ANTHROPIC_API_KEY` required.

### Mode B — CLI (standalone; API key may be needed)

Use `wikimind ingest/query/lint` commands directly from the terminal. WikiMind
calls your configured provider on your behalf (`anthropic`, `openai`, or
`ollama`). API key requirements depend on provider.

Both modes write to the same wiki directory and are fully compatible.

Default hidden layout created by `wikimind init`:
- `.wiki/raw/` — immutable sources
- `.wiki/vault/` — LLM-maintained wiki pages
- `.wiki/.wikimind/` — operational metadata

---

## Installation

### Development install (editable)

```bash
# Clone and set up virtual environment
git clone <repo>
cd wikimind
python -m venv .venv

# Activate venv
source .venv/bin/activate       # macOS/Linux
.venv\Scripts\activate          # Windows

# Install
pip install -e .
```

This mode links the installed command to your source checkout.

### Using `wikimind` across different project folders

After a development install, the `wikimind` command only works when the venv is
active. If you `cd` to another project and the venv is not active, you'll get
`command not found`.

**Option A — Activate the venv before switching folders (per-session):**

```bash
# Activate once per terminal session
source ~/Desktop/project/wikimind/.venv/Scripts/activate   # Git Bash / macOS / Linux
# or
source ~/Desktop/project/wikimind/.venv/bin/activate       # macOS / Linux

# Now wikimind works anywhere in this session
cd ~/my-other-project
wikimind init
```

**Option B — Install globally with `pipx` (recommended, permanent):**

```bash
# Install pipx if you don't have it
pip install pipx

# Install wikimind globally from your local repo (editable)
pipx install -e ~/Desktop/project/wikimind

# wikimind is now available everywhere, always — no venv activation needed
cd ~/my-other-project
wikimind init
```

`pipx` creates an isolated environment just for the `wikimind` CLI and adds it
to your system PATH permanently. This is the cleanest approach for CLI tools you
want to use across projects.

### Install without source checkout (local/other machine)

Build a distributable wheel once:

```bash
python -m pip install --upgrade build
python -m build
# -> dist/wikimind-0.1.0-py3-none-any.whl
```

Then install that wheel on any machine:

```bash
# Option A: global isolated CLI (recommended)
pipx install dist/wikimind-0.1.0-py3-none-any.whl

# Option B: inside a virtual environment
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
.venv\Scripts\activate          # Windows
pip install dist/wikimind-0.1.0-py3-none-any.whl
```

After that, you can run `wikimind` directly (no source repo required).

Helper scripts (from repo root):

```bash
# macOS/Linux/Git Bash
bash scripts/build-wheel.sh

# PowerShell
powershell -ExecutionPolicy Bypass -File scripts/build-wheel.ps1
```

Both scripts build `dist/*.whl` and auto-detect `.venv` Python when available.

**Optional — PDF support:**
```bash
pip install -e ".[pdf]"
```

With the `pdf` extra installed, `wikimind ingest file.pdf` extracts markdown
from the PDF via `pymupdf4llm` before ingesting. Without it, ingesting a `.pdf`
raises a clear error with install instructions.

---

## Quick start

### With Claude Code (Mode A — recommended)

```bash
# 1. Initialize WikiMind in your project directory
cd my-project
wikimind init --name "My Research"

# 2. Drop sources into .wiki/raw/
cp ~/articles/paper.md .wiki/raw/

# 3. Open the project in Claude Code
# Claude Code reads CLAUDE.md and connects to WikiMind MCP server automatically

# 4. Tell Claude Code to ingest:
#    "Please ingest .wiki/raw/paper.md into the wiki"
#    Claude Code uses wiki_write_page, wiki_update_index, wiki_append_log tools

# 5. Browse the wiki in Obsidian
#    open .wiki/vault/ in Obsidian to see the graph view
```

No `ANTHROPIC_API_KEY` needed for this workflow.

### With CLI (Mode B)

```bash
# If using default Anthropic provider, set API key
export ANTHROPIC_API_KEY=sk-ant-...   # macOS/Linux
set ANTHROPIC_API_KEY=sk-ant-...      # Windows

# Initialize
wikimind init --name "AI Safety Research"

# Add a source and ingest it
cp ~/papers/alignment.md .wiki/raw/
wikimind ingest .wiki/raw/alignment.md

# Ask questions
wikimind query "What are the key arguments about AI alignment?"
wikimind query --save "Compare the methodologies across papers"

# Health check
wikimind lint
```

To use OpenAI instead of Anthropic, set in `wikimind.toml`:

```toml
[llm]
provider = "openai"
model = "gpt-4o-mini"
api_key_env = "OPENAI_API_KEY"
```

To use local Ollama:

```toml
[llm]
provider = "ollama"
model = "llama3.1"
# base_url = "http://localhost:11434"  # optional override
```

---

## Commands reference

### `wikimind init`

Initialize WikiMind in the current directory.

```bash
wikimind init                          # uses directory name as project name
wikimind init --name "My Research"     # explicit project name
wikimind init --template general       # general (default) | code | research | book
```

Creates:
- `.wiki/raw/` — drop your source files here
- `.wiki/vault/` — LLM-maintained wiki (index.md, log.md, overview.md + subdirs)
- `CLAUDE.md` — LLM instructions (the schema layer)
- `wikimind.toml` — tool configuration
- `.mcp.json` — Claude Code MCP config (auto-generated)

If `CLAUDE.md` already exists (e.g. you ran `wikimind init` in an existing
Claude Code project), WikiMind **appends** the wiki section rather than
overwriting.

---

### `wikimind ingest`

Ingest a source file (or directory) into the wiki.

```bash
wikimind ingest .wiki/raw/article.md         # ingest a single file
wikimind ingest .wiki/raw/                   # ingest all files in raw path
wikimind ingest .wiki/raw/article.md --dry-run  # preview: show what would be written
wikimind ingest .wiki/raw/article.md --force    # re-ingest even if file unchanged
```

What happens:
1. Read the source file
2. Use configured retrieval backend to find relevant existing wiki pages (`bm25` by default)
3. Single LLM call with structured output → list of files to write
4. Write wiki pages (source summary, entity pages, concept pages)
5. Update `.wiki/vault/index.md`, append to `.wiki/vault/log.md`
6. Record source hash for dedup (skips unchanged files on re-run)

Large files (>50K chars) are chunked and summarized before ingesting.

Batch ingest (`wikimind ingest .wiki/raw/`) prints a per-run summary and exits non-zero
if any file fails.

---

### `wikimind query`

Ask a question against the wiki.

```bash
wikimind query "What are the key themes?"
wikimind query "How does X relate to Y?" --save
wikimind query "Compare the methodologies" --save --top-k 15
```

Options:
- `--save` — save the answer as a wiki page in `wiki/analyses/`
- `--top-k N` — number of wiki pages to consider (default 10)

What happens:
1. Use configured retrieval backend (`bm25` or `index_keyword`) → find top relevant pages
2. Single LLM call → answer with [[wikilink]] citations + confidence level
3. Print answer to terminal
4. If `--save`: write answer to `wiki/analyses/<slug>.md` + update index + log

**Write-back is the key insight.** `--save` makes your explorations compound in
the wiki just like ingested sources do. Valuable analyses don't disappear into
terminal history.

Output shows:
- Confidence level (high / medium / low — how well the wiki covers this)
- Citations (wiki pages used)
- Knowledge gaps (what to ingest next to answer this better)

---

### `wikimind lint`

Health-check the wiki for structural issues, with optional semantic analysis.

```bash
wikimind lint          # report issues (read-only)
wikimind lint --fix    # report + auto-fix what can be fixed
wikimind lint --semantic  # one LLM call: contradictions + missing topic pages + source suggestions
```

Structural checks (no LLM, instant):
- **Orphan pages** — wiki pages with zero inbound [[wikilinks]]
- **Broken links** — [[wikilinks]] pointing to non-existent pages
- **Index desync** — pages on disk not listed in `.wiki/vault/index.md`
- **Missing frontmatter** — pages without required YAML fields
- **Stale sources** — raw files that have changed since their wiki summary was written

Auto-fix (`--fix`) handles:
- Adds missing pages to `.wiki/vault/index.md`
- Creates stub pages for broken link targets

Semantic checks (`--semantic`, one LLM call):
- Contradictions between pages
- Important topics mentioned but lacking their own page
- Suggested new sources to fill knowledge gaps

Note: `--semantic` uses your configured CLI provider (API key requirements depend on provider) and findings are currently report-only (no auto-fix).

Run lint regularly as the wiki grows to keep it healthy.

---

### `wikimind serve`

Start the MCP server for Claude Code integration.

```bash
wikimind serve                    # stdio mode (Claude Code uses this via .mcp.json)
wikimind serve --transport sse    # HTTP/SSE mode (for other MCP clients)
```

**You don't run this manually** — Claude Code starts it automatically via
`.mcp.json`. But you can run it to test the connection.

MCP tools exposed to Claude Code:

| Tool | Description |
|------|-------------|
| `wiki_read_index` | Read the configured wiki index (`index.md`) — always start here |
| `wiki_read_page` | Read a specific wiki page by path (relative to configured wiki root) |
| `wiki_search` | Find relevant pages by keyword (returns content) |
| `wiki_list_pages` | List all wiki page paths |
| `wiki_write_page` | Create or update a wiki page (relative to configured wiki root) |
| `wiki_update_index` | Add/remove entries from the configured `index.md` |
| `wiki_append_log` | Append an entry to the configured `log.md` |
| `wiki_status` | Get wiki stats (page count, source count, last updated) |

MCP read/write paths are sandboxed to the configured wiki directory. Attempts to use
`../` or absolute paths are rejected.

---

### `wikimind status`

Show wiki statistics.

```bash
wikimind status
```

Output: page count, source count, unprocessed sources, last updated, paths, model.

---

### `wikimind cost`

Show cumulative LLM token usage across all past CLI runs.

```bash
wikimind cost           # show all-time totals + last 10 commands
wikimind cost --last 20 # show last 20 commands
```

Usage is persisted to `.wikimind/cost.json` after every `ingest`, `query`,
`lint --semantic`, and `watch` run. The `cost` command reads that file and
displays a summary table. If `max_budget_usd` is set, it also shows how much
of the budget has been consumed.

Note: USD estimate is modeled for Anthropic pricing only; other providers show $0.00.

---

### `wikimind watch`

Watch `raw/` for new or changed files and auto-ingest them.

```bash
wikimind watch                  # poll every 5 seconds (default)
wikimind watch --interval 30    # poll every 30 seconds
wikimind watch --force          # re-ingest even if file is unchanged
```

Uses stdlib polling — no extra dependencies. Detects:
- **New files** (never ingested before)
- **Changed files** (content differs from last ingest — same as stale-source lint)

Stop with Ctrl+C. Token cost is persisted to `.wikimind/cost.json` after each
auto-ingest batch.

---

## Configuration

### `wikimind.toml`

```toml
[project]
name = "My Research"
template = "general"

[paths]
raw = ".wiki/raw/"      # where you drop source files
wiki = ".wiki/vault/"   # where the LLM writes wiki pages

[llm]
provider = "anthropic"                # anthropic | openai | ollama
model = "claude-sonnet-4-20250514"    # example; change per provider
api_key_env = "ANTHROPIC_API_KEY"     # OPENAI_API_KEY for openai; optional for ollama
# base_url = ""                        # optional override (OpenAI: https://api.openai.com/v1, Ollama: http://localhost:11434)
# max_tokens_per_call = 8192
# max_budget_usd = 5.0                 # per-session spending cap (0 = no limit)

[wiki]
required_frontmatter = ["title", "type", "tags", "created", "updated"]
retrieval_backend = "bm25"            # bm25 | index_keyword

[wiki.categories]
entities = "People, organizations, tools, systems"
concepts = "Ideas, theories, patterns, principles"
sources = "One summary per raw source"
analyses = "Saved queries, comparisons, syntheses"
```

Provider notes:
- `anthropic`: requires `ANTHROPIC_API_KEY`.
- `openai`: requires `OPENAI_API_KEY` (set `api_key_env = "OPENAI_API_KEY"`).
- `ollama`: local provider, API key not required by default.

Retriever notes:
- `bm25`: full-text lexical BM25 ranking over wiki pages (default, better at larger scale).
- `index_keyword`: lightweight index.md keyword match (fast, simple for very small wikis).

### `CLAUDE.md` (the schema layer)

The most important file. Generated by `wikimind init`. Tells the LLM:
- Where the wiki lives and how it's structured
- Required page format (YAML frontmatter, [[wikilinks]])
- What to do when ingesting, querying, or maintaining the wiki
- Which CLI commands are available

You and the LLM co-evolve this file over time. Add domain-specific conventions
as you discover what works for your use case.

`wikimind init` will create `CLAUDE.md` if it doesn't exist. If it already
exists, WikiMind appends its section instead of overwriting your existing
project instructions.

### `.mcp.json`

Auto-generated by `wikimind init`. Points Claude Code to the `wikimind serve`
command. Do not edit manually unless you need a custom path.

If WikiMind is installed globally (for example via `pipx`), you can use
`"command": "wikimind"` instead of an absolute `.venv` path.

```json
{
  "mcpServers": {
    "wikimind": {
      "command": "/path/to/.venv/Scripts/wikimind",
      "args": ["serve"],
      "cwd": "/path/to/your/project"
    }
  }
}
```

Client setup notes:
- Claude Code: usually no manual MCP setup needed after `wikimind init` because
  `.mcp.json` is auto-generated.
- Existing projects: if `.mcp.json` already exists, `wikimind init` leaves it
  unchanged (you can merge manually if needed).
- Other MCP clients (for example GitHub Copilot MCP workflows): configure the
  equivalent MCP server entry manually in that client's own settings, typically
  with `command: wikimind`, `args: ["serve"]`, and `cwd` set to your project.

GitHub Copilot MCP example (client-managed config):

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

Note: exact file location/format can vary by client version and host app.

---

## Wiki structure

```
.wiki/vault/
├── index.md          # Master catalog — LLM reads this first on every operation
├── log.md            # Append-only chronological record of all wiki changes
├── overview.md       # High-level synthesis of the topic (LLM maintains)
├── entities/         # People, organizations, tools, systems
│   └── openai.md
├── concepts/         # Ideas, theories, patterns, principles
│   └── transformer-architecture.md
├── sources/          # One summary page per raw source
│   └── attention-is-all-you-need.md
└── analyses/         # Saved query answers, comparisons, syntheses
    └── compare-methodologies.md
```

Every wiki page has YAML frontmatter:

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

Pages cross-reference each other with `[[wikilinks]]`. The link graph is what
makes the wiki valuable — it's pre-built, not re-derived on every query.

---

## Workflow tips

**Use Obsidian to browse the wiki.**
Open `.wiki/vault/` as an Obsidian vault. The graph view shows which pages are hubs
and which are orphans. [[wikilinks]] are clickable. The wiki becomes genuinely
navigable.

**Save good answers.**
`wikimind query --save "..."` files the answer back as a wiki page. Syntheses
and comparisons you discover are valuable — don't let them disappear into
terminal history.

**Ingest one source at a time** (especially early on).
Stay involved: read the summaries, check the updates, guide the LLM on what
to emphasize. You can batch-ingest with `wikimind ingest .wiki/raw/` but you get
better results when you're in the loop.

**Run lint periodically.**
As the wiki grows, orphan pages and broken links accumulate. `wikimind lint`
catches these before they become a problem. `wikimind lint --fix` handles the
mechanical fixes.

**git init the wiki.**
The wiki is just markdown files. Version history is free. If the LLM writes
something bad, `git diff` shows what changed and `git checkout` reverts it.

**Use `--dry-run` before trusting a new source.**
`wikimind ingest .wiki/raw/file.md --dry-run` shows what the LLM would write without
actually writing it. Useful for checking a new source type or after changing
`CLAUDE.md`.

---

## Use cases

- **Research** — going deep on a topic over weeks: reading papers, articles,
  reports, and incrementally building a comprehensive wiki with an evolving thesis.
- **Reading a book** — file each chapter as you go, building out pages for
  characters, themes, plot threads, and how they connect.
- **Personal knowledge** — tracking goals, health, self-improvement by filing
  journal entries, articles, podcast notes.
- **Team/business** — internal wiki maintained by LLMs, fed by Slack threads,
  meeting transcripts, project documents.
- **Code projects** — used alongside Claude Code: as Claude analyzes code,
  it writes architectural notes, decision records, and entity pages to the wiki.

---

## Roadmap

| Feature | Status |
|---------|--------|
| `wikimind ingest` | Done |
| `wikimind query` | Done |
| `wikimind lint` (structural + stale sources) | Done |
| `wikimind lint --semantic` (contradictions, gaps) | Done (report-only) |
| `wikimind serve` (MCP server) | Done |
| `wikimind watch` (auto-ingest new/stale files) | Done |
| `wikimind cost` (persistent token history) | Done |
| `wikimind init` — templates: general, code, research, book | Done |
| Dedup (skip unchanged sources) | Done |
| Large file chunking (>50K chars) | Done |
| PDF support (`pip install -e ".[pdf]"`) | Done |
| Retrieval abstraction (`bm25` + `index_keyword` backends) | Done |
| MCP `wiki_search` uses configured retrieval backend | Done |
| Provider adapter architecture (Anthropic/OpenAI/Ollama) | Done |
| Budget guard (`max_budget_usd` in config) | Done |
| PyPI publish | Planned |
