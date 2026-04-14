# WikiMind — Gap Analysis

> Comparing the original Karpathy wiki idea against what's implemented.
> Each gap is self-contained: background, what's missing, and concrete options.
> Work through these one by one as the project matures.

---

## What's Already Done (Baseline)

| Concept | Implementation | Status |
|---|---|---|
| 3-layer architecture (raw/wiki/schema) | `.wiki/raw/`, `.wiki/vault/`, `CLAUDE.md` | ✅ Done |
| Ingest → structured wiki pages | Single LLM call, `wiki_update` tool | ✅ Done |
| Query → cite with wikilinks + save back | `query --save` → `analyses/` | ✅ Done |
| Lint: structural checks | orphans, broken links, desync, stale | ✅ Done |
| Lint: semantic checks | `--semantic` LLM pass | ✅ Done |
| index.md as LLM navigation tool | read first, keyword + BM25 matching | ✅ Done |
| log.md as parseable chronological record | `## [YYYY-MM-DD] op \| title` format | ✅ Done |
| Dedup (skip unchanged sources) | SHA-256 content hash | ✅ Done |
| Large file chunking | >50K chars → summarize chunks | ✅ Done |
| BM25 retrieval | Okapi BM25 retriever | ✅ Done |
| Mode A (Claude Code + MCP) | 8 MCP tools, `.mcp.json` auto-gen | ✅ Done |
| Mode B (CLI standalone) | `ingest/query/lint/status/cost/watch` | ✅ Done |
| Multi-provider | Anthropic/OpenAI/Ollama adapters | ✅ Done |
| Budget guard | `max_budget_usd` per session | ✅ Done |
| Templates | general/code/research/book | ✅ Done |
| CLAUDE.md schema merge-safe update | markers, `--force` flag | ✅ Done |

---

## GAP-1 — Interactive / Conversational Ingest

**Priority:** High  
**Complexity:** Medium  
**Status:** Not started

### What the original idea says

> "The LLM reads the source, *discusses key takeaways with you*, writes a summary page...
> I prefer to ingest sources one at a time and *stay involved* — I read the summaries, check the updates,
> and *guide the LLM on what to emphasize*."

### What we have

`wikimind ingest` is fully automated and one-shot. You run it, pages appear, done.
There is no dialogue, no preview of intent, no way to say "focus on methodology"
or "connect this to [[concept-x]]" before the LLM writes. The user is a passive bystander.

### Why this matters

This is the core UX pattern Karpathy described — human + LLM in dialogue *during* ingest.
Mode A (Claude Code) handles it organically since Claude Code IS the conversation.
Mode B (CLI) treats ingest as a batch job and misses the most important part of the workflow.

### Options

**A. `--focus` flag (simplest)**
Inject user guidance into the ingest system prompt before the LLM call.
```bash
wikimind ingest paper.md --focus "focus on methodology and statistical results, ignore the intro"
wikimind ingest paper.md --focus "connect this to [[transformer-architecture]] if relevant"
```
Implementation: append `--focus` text to `INGEST_SYSTEM_PROMPT` before calling the LLM.
One-line change in `operations/ingest.py`. Already expressive enough for most use cases.

**B. `--interactive` / confirm-before-write (medium)**
After the LLM call but before writing files, print the plan (pages to create/update + summaries)
and ask: "Proceed? (y/n/guide)". If "guide", accept a free-text instruction and retry the LLM call.
```
Planning ingest of: alignment-paper.md
  → create  sources/alignment-paper.md
  → create  entities/paul-christiano.md
  → update  concepts/mesa-optimization.md

Proceed? [y/n/guide]: guide
> Also create a concept page for "eliciting latent knowledge"
Re-running with guidance...
```

**C. Post-ingest mini-REPL (ambitious)**
After ingest completes, drop into a short Q&A loop:
"Here's what I created. Ask me to adjust anything. (Enter to skip)"
User can ask "make the Paul Christiano page more detailed" → targeted follow-up LLM call.

### Recommendation
Start with **A** (`--focus`). It's one flag, minimal code, and covers 80% of the use case.
Design **B** once real users hit the limit of fire-and-forget.

---

## GAP-2 — overview.md Never Updated (Synthesis Page Stays Stale)

**Priority:** High  
**Complexity:** Low  
**Status:** Not started

### What the original idea says

> The wiki has "an overview, a synthesis" that evolves. "The wiki keeps getting richer with every source
> you add." The compounding artifact promise: everything you read makes the synthesis stronger.

### What we have

`overview.md` is created at `wikimind init` from a static template and **never touched again**.
After 20 ingests, the overview still contains boilerplate template text. The page that should
represent the current state of the entire knowledge base is always stale.

### Why this matters

The synthesis page is the highest-value artifact in the wiki — it's what you show someone to
explain what your knowledge base contains. Letting it rot contradicts the core promise of the tool.

### Options

**A. `wikimind synthesize` command (recommended)**
New command: reads all wiki pages (or top N by relevance), makes one LLM call, rewrites `overview.md`.
```bash
wikimind synthesize              # regenerate overview.md from all wiki content
wikimind synthesize --top-k 30  # use top 30 pages by BM25 relevance to current overview
```
Tool schema: `{ "overview_content": "...", "log_entry": "..." }`
This is the same pattern as query but the output target is always `overview.md`.

**B. Auto-update during ingest (opt-in)**
```bash
wikimind ingest paper.md --update-overview
```
After normal ingest, make a second LLM call to patch `overview.md` with new information.
Cost: one extra LLM call per ingest. Opt-in via flag or `wikimind.toml` setting.

**C. Lint warns when overview is stale**
If N ingests have happened since `overview.md` was last written, `wikimind lint` reports:
`overview.md has not been updated since 8 ingests — run wikimind synthesize`
Low lift, surfaces the problem without automating it.

### Recommendation
Implement **C** first (lint warning, zero cost). Then add **A** (`wikimind synthesize`) as the fix action.
**B** is too expensive per-ingest by default.

---

## GAP-3 — No Atomic MCP Ingest Tool (Mode A Incoherence)

**Priority:** High  
**Complexity:** Low  
**Status:** Not started

### What the original idea says

Mode A: "Claude Code reads `CLAUDE.md`, understands the wiki structure, and uses MCP tools
to maintain the wiki as part of its normal work."

### What we have

The MCP server exposes only low-level file tools: `wiki_write_page`, `wiki_update_index`,
`wiki_append_log`. When Claude Code does ingest via MCP, it must manually orchestrate:
1. read source file
2. decide what pages to create/update
3. call `wiki_write_page` per page (5-10 calls)
4. call `wiki_update_index`
5. call `wiki_append_log`

This is inconsistent, has no atomicity, no dedup check, no structured validation.
Every Claude Code session reinvents the ingest logic differently.

Meanwhile `wikimind ingest` does this in one atomic, validated operation.

### Options

**A. `wiki_ingest_source` MCP tool (recommended)**
Wrap the full ingest flow as an MCP tool. Claude Code calls it with a source path;
the server runs the same code as `wikimind ingest` and returns a summary.
```python
@mcp.tool()
def wiki_ingest_source(source_path: str, focus: str = "", dry_run: bool = False) -> str:
    """Trigger a full ingest of a source file. Equivalent to `wikimind ingest <path>`.
    Returns a JSON summary: pages created, pages updated, log entry.
    source_path: path relative to the raw/ directory, or absolute.
    focus: optional guidance for the LLM (e.g. 'focus on methodology').
    """
```
This requires the MCP server to have its own `LLMClient` — currently it doesn't (by design,
since Mode A relies on Claude Code as the LLM). This is the main design tension to resolve.

**B. Document the manual flow in CLAUDE.md (minimal)**
Add explicit step-by-step ingest instructions to `CLAUDE.md` so Claude Code follows a
consistent protocol even using low-level tools. Less elegant but zero code.

**C. `wiki_ingest_source` calls CLI as subprocess**
The MCP tool shells out to `wikimind ingest <path>` and returns stdout.
Avoids the LLM-in-MCP-server problem. Brittle but works.

### Recommendation
Design decision needed: should the MCP server embed its own LLM client for Mode A?
This changes the Mode A architecture significantly. Start with **B** (document the protocol)
while deciding on **A**.

---

## GAP-4 — Image / Multimodal Handling in Ingest

**Priority:** Medium  
**Complexity:** High  
**Status:** Not started

### What the original idea says

> "Download images locally... this lets the LLM view and reference images directly instead of
> relying on URLs that may break. LLMs can't natively read markdown with inline images in one pass —
> the workaround is to have the LLM read the text first, then view some or all of the referenced
> images separately to gain additional context."

### What we have

Text-only ingest. Images embedded in markdown (`![caption](path)`) are passed as raw text
references. The LLM sees `![diagram of architecture](assets/arch.png)` but never the image.
PDF extraction produces text only. No image awareness.

### Why this matters

For the Obsidian Web Clipper workflow (clip article → download images → ingest), articles often
have charts, diagrams, and screenshots that carry meaning the text doesn't. Entity and concept
pages built without image context are incomplete.

### Options

**A. Detect and warn about image references**
During ingest, scan source markdown for `![](local-path)` references.
Print a warning: "Source has 3 local images — consider passing them separately for richer context."
Zero-effort, surfaces the gap.

**B. Pass images to multimodal LLM call**
If source markdown contains local image references (`.png`, `.jpg`, `.webp`, etc.):
1. Read image bytes
2. Build a multimodal message: text content + image content blocks (Anthropic API format)
3. Single LLM call with both text and images

Requires: multimodal support in `LLMClient.call()`, only works with providers that support vision.

**C. Two-pass ingest for image-heavy sources**
Pass 1: ingest text only → create initial pages
Pass 2: for each local image referenced, make a separate vision LLM call → append findings to pages
More thorough, but 2x+ the cost.

### Recommendation
Start with **A** (detect and warn) to surface the gap. **B** is the right long-term solution
but requires multimodal API plumbing across all providers.

---

## GAP-5 — Lint Findings Are Not Persisted or Actionable

**Priority:** Medium  
**Complexity:** Low  
**Status:** Not started

### What the original idea says

> "The LLM is good at suggesting new questions to investigate and new sources to look for.
> This keeps the wiki healthy as it grows."

### What we have

`wikimind lint --semantic` produces `suggested_sources`, `suggested_missing_pages`, and
`contradictions` as terminal output. Once the command exits, the findings are gone.
There is no queue, no follow-up workflow, no way to track which suggestions were acted on.

### Options

**A. `--save` flag for lint (recommended)**
```bash
wikimind lint --semantic --save
```
Writes a `analyses/lint-report-YYYY-MM-DD.md` page into the wiki.
The findings are now *part of the wiki* — they compound, can be cited, and are visible in Obsidian.
This is one small change to `operations/lint.py` and `cli.py`.

**B. Wanted-page stubs**
`wikimind lint --fix --semantic`: for each `suggested_missing_pages` entry, create a stub page
in the appropriate category with `status: wanted` frontmatter.
The Obsidian graph then shows these as visible gaps, encouraging follow-up.

**C. `.wikimind/agenda.json`**
Persist lint findings to `.wikimind/agenda.json` and expose a `wikimind agenda` command:
```bash
wikimind agenda          # show open items (gaps, contradictions, suggested sources)
wikimind agenda --done   # mark an item resolved
```
More complex but gives the wiki an active TODO system.

### Recommendation
**A** first (`--save`). Trivial to implement, high value. **B** and **C** can come later.

---

## GAP-6 — Rich Query Output Formats

**Priority:** Medium  
**Complexity:** Medium  
**Status:** Not started

### What the original idea says

> "Answers can take different forms depending on the question — a markdown page,
> a comparison table, a slide deck (Marp), a chart (matplotlib), a canvas."

### What we have

`query` always returns a `str answer` in the QUERY_TOOL schema. Output is rendered to
terminal as plain text and optionally saved as a markdown analysis page. No format control.

### Options

**A. `--format` flag for structured output types**
```bash
wikimind query "Compare the three approaches" --format table
wikimind query "Overview of themes" --format marp
```
- `table`: instruct LLM to produce a markdown table; save as `.md`
- `marp`: instruct LLM to produce a Marp slide deck; save as `.md` with Marp front matter
- `bullets`: force a bulleted summary (good for dense questions)

Implementation: inject format instruction into the query system prompt.
The LLM already writes markdown; Marp is just markdown + front matter.

**B. Chart / data output (matplotlib)**
For quantitative questions: `wikimind query "Show token usage over time" --format chart`
This requires: extracting structured data from the answer, shelling out to matplotlib,
saving a PNG to `analyses/`. High complexity, niche use case.

**C. Canvas format**
Obsidian canvas is a JSON format for visual node graphs.
The LLM could produce a canvas layout for relationship questions.
Very complex; requires LLM to emit valid Obsidian canvas JSON.

### Recommendation
**A** with `table` and `marp` only. These are pure prompt engineering — the LLM already
knows both formats. No new dependencies. **B** and **C** are stretch goals.

---

## GAP-7 — No `wikimind log` Command

**Priority:** Low  
**Complexity:** Low  
**Status:** Not started

### What the original idea says

> "If each entry starts with a consistent prefix (`## [YYYY-MM-DD] ingest | Article Title`),
> the log becomes parseable with simple unix tools. The log gives you a timeline of the wiki's
> evolution and helps the LLM understand what's been done recently."

### What we have

`log.md` is correctly formatted. But there is no CLI to query it — you open the file manually.
The `wikimind cost` command tracks token history but not wiki content history.

### Options

**A. `wikimind log` command**
Parse `log.md` for `## [YYYY-MM-DD] op | title` headers and print them:
```bash
wikimind log                     # last 10 entries
wikimind log --last 20           # last 20 entries
wikimind log --since 2026-04-01  # entries after a date
wikimind log --op ingest         # filter by operation type (ingest/query/lint)
```
Pure string parsing of an existing file. ~50 lines of code.

### Recommendation
Straightforward addition. Do it whenever adding a new CLI command feels worthwhile.

---

## GAP-8 — Obsidian-Specific Init Configuration

**Priority:** Low  
**Complexity:** Low  
**Status:** Not started

### What the original idea says

> "Obsidian Web Clipper, graph view, Dataview plugin, Marp plugin, 'Download attachments' hotkey"
> Obsidian is named explicitly as the primary browsing UI.

### What we have

The README mentions Obsidian extensively but `wikimind init` creates no Obsidian configuration.
`init` output says "open with Obsidian" but doesn't set it up.

### Options

**A. Generate `.obsidian/app.json` at init**
Create minimal Obsidian config:
- Set attachment folder to `.wiki/raw/assets/` (for Web Clipper images)
- Set link format to `[[wikilinks]]`
- Set new file location to last used folder

**B. Add Dataview-friendly frontmatter guidance to templates**
Add `source_count`, `confidence`, `status` fields to template frontmatter so Dataview
queries like "show all concepts with >3 sources" work out of the box.

**C. Mention Obsidian setup in init output**
At minimum, the `wikimind init` summary could include:
`"Open .wiki/vault/ as an Obsidian vault for graph view and wikilink navigation."`
The README already says this; the CLI doesn't.

### Recommendation
**C** immediately (one line of output). **A** and **B** when polish becomes a priority.

---

## GAP-9 — Source Deletion Not Detected by Lint

**Priority:** Low  
**Complexity:** Low  
**Status:** Not started

### What we have

The stale source check detects raw files that have *changed* since last ingest.
But if a raw file is *deleted*, the wiki pages that cite it (`sources: [sources/deleted-paper]`)
are never flagged. The link graph becomes incorrect silently.

### Options

**A. Lint check: deleted sources**
In `operations/lint.py`: for each entry in `.wikimind/sources.json`, check if the file
still exists on disk. If not, flag it as `deleted_sources` in `LintReport`.
Report: "source `raw/paper.md` was deleted but wiki still has pages citing it."

**B. Auto-fix: mark pages as orphaned on source deletion**
With `--fix`: add a `⚠️ source deleted` notice to the top of affected wiki pages.

### Recommendation
**A** is a 10-line addition to lint. Do it alongside the stale-source check code it
already lives next to.

---

## GAP-10 — Semantic / Hybrid Search (Beyond BM25)

**Priority:** Medium  
**Complexity:** Low–Medium  
**Status:** Done

### Implementation Summary

Fully implemented as `QmdRetriever` in `wikimind/retrieval.py` with the following:

- **Three search modes** via `qmd_mode` config: `search` (BM25), `vsearch` (vector/semantic, default), `query` (full hybrid + LLM re-ranking)
- **Subprocess integration**: calls qmd CLI via `subprocess.run()` with `--json` output parsing
- **Windows compatibility**: detects npm `.CMD` wrappers and routes through Git's `sh.exe`
- **Graceful fallback**: `make_retriever()` auto-falls back to BM25 if qmd is not installed
- **Background embed in MCP server**: `server.py` uses a threading pattern (`_embed_dirty` / `_embed_thread` / `_embed_lock`) — `wiki_write_page` sets a dirty flag and fires a background `qmd embed` thread; `wiki_search` waits for any in-progress embed before searching
- **Auto-embed after CLI ingest**: `wikimind ingest` runs `qmd embed` automatically when `retrieval_backend = "qmd"`
- **Config**: `retrieval_backend = "qmd"`, `qmd_mode`, `qmd_bin` in `wikimind.toml`
- **Tests**: `test_retrieval.py` covers factory, fallback, mode validation, subprocess mocking, top_k enforcement

The sections below are preserved as design reference for the original analysis.

---

### What the original idea says

> "A search engine over the wiki pages is the most obvious one — at small scale the index file is
> enough, but as the wiki grows you want proper search. [qmd](https://github.com/tobi/qmd) is a
> good option: it's a local search engine for markdown files with hybrid BM25/vector search and
> LLM re-ranking, all on-device. It has both a CLI (so the LLM can shell out to it) and an MCP
> server (so the LLM can use it as a native tool)."

---

### Why BM25 fails at scale

Our current `BM25Retriever` is lexical — it only finds pages that share words with the query.
When the wiki grows past ~200 pages, semantic gaps become painful:

| Query | BM25 result | Semantic result |
|---|---|---|
| "machine learning" | Pages with exact words "machine learning" | Also: neural networks, gradient descent, training loop |
| "people who worked on transformers" | Weak keyword match | Entity pages for Vaswani, Bengio, etc. |
| "why did they change the approach" | Near-zero signal | Pages about methodology shifts, design decisions |

---

### Full comparison: all retrieval approaches

| | `index_keyword` | `bm25` (current default) | `qmd` CLI | Native embedding |
|---|---|---|---|---|
| **How it works** | Keyword overlap on index.md | Okapi BM25 over all pages | BM25 + local vector + local LLM re-rank | Embedding cosine similarity |
| **Finds semantic matches** | No | No | Yes | Yes |
| **LLM re-ranking** | No | No | Yes — local GGUF model, no API key | Yes — via our existing LLM client |
| **External dependencies** | None | None | Node.js + `npm install -g @tobilu/qmd` | embedding-capable API or local model |
| **Works offline** | Yes | Yes | Yes — fully local after install | No — needs embedding API (except Ollama) |
| **Integrated config** | One `wikimind.toml` | One `wikimind.toml` | One `wikimind.toml` + one-time qmd setup | One `wikimind.toml` |
| **Extra step after ingest** | None | None | `qmd embed` to refresh index | Cache auto-updates on hash change |
| **Good up to** | ~50 pages | ~200 pages | Any scale | Any scale |
| **Complexity to add** | Done | Done | Low (~60 lines) | Medium (cache + embedding calls) |

---

### What qmd is and how its pipeline works

`qmd` (by Tobi Lütke / github.com/tobi/qmd) is a **Node.js package** — a CLI tool installed
via npm or bun, not a Python library and not a Go binary. There is nothing to import into
Python. It is installed globally by the user and invoked as a shell command.

#### Installation

```bash
npm install -g @tobilu/qmd
# or
bun install -g @tobilu/qmd
# or run without installing
npx @tobilu/qmd
```

#### CLI commands — three distinct search modes

qmd exposes separate commands for each search mode, not a single `search` command:

| Command | What it does |
|---|---|
| `qmd search "query"` | BM25 lexical search only (fastest) |
| `qmd vsearch "query"` | Vector/semantic search only |
| `qmd query "query"` | **Full hybrid: BM25 + vector + LLM re-ranking** |
| `qmd embed` | Pre-compute embeddings for all indexed documents |
| `qmd collection add [path] --name [name]` | Register a directory as a searchable collection |
| `qmd mcp` | Start qmd MCP server |

All commands support `--json` for structured output and `-c [collection]` to filter by collection.

#### qmd's full pipeline (triggered by `qmd query`)

```
qmd query "machine learning" --json
  │
  ├─ Step 1: BM25 (lexical)              ← local, no API
  ├─ Step 2: Vector embedding search     ← local GGUF model via node-llama-cpp, no API
  ├─ Step 3: Merge via RRF (Reciprocal Rank Fusion)
  └─ Step 4: LLM re-ranking             ← local GGUF model via node-llama-cpp, no API
  │
  └─ prints JSON → exits
```

**All four steps run locally.** The LLM re-ranking uses a local GGUF model loaded via
`node-llama-cpp` — no external API key, no second LLM config. This eliminates the "two config
problem" mentioned earlier. qmd is fully self-contained once installed.

#### One prerequisite: collection registration

Before searching, qmd must know where the vault is. The user registers it once:

```bash
qmd collection add .wiki/vault/ --name wiki
qmd embed   # pre-compute embeddings for all pages
```

Re-running `qmd embed` after ingesting new pages keeps the index current. This could be
triggered automatically as part of `wikimind ingest` or `wikimind watch`.

#### qmd's two interfaces — same engine, different access

```
qmd (Node.js CLI)
├── CLI:        qmd query "..." --json  → runs full pipeline → prints JSON → exits
└── MCP server: qmd mcp                → long-running process → same pipeline per call
```

Both interfaces use the **same underlying search engine**. For WikiMind's purposes, **we never
need to start the qmd MCP server** — we call `qmd query` via subprocess and get identical results.

**Do NOT register qmd as a second MCP server alongside wikimind.** That creates two overlapping
search tools (`wiki_search` and `qmd_search`) and Claude Code would unpredictably pick between
them. The single `wiki_search` tool, powered internally by qmd, is the right design.

---

### Option A — `QmdRetriever`: subprocess to qmd CLI (recommended for Anthropic users)

#### What it is

`QmdRetriever` is a class **we write** in `wikimind/retrieval.py`, sitting alongside the
existing `BM25Retriever`. It is not imported from qmd — qmd has no Python library. It calls
the qmd binary the same way you would type a shell command, using Python's `subprocess`:

```
wikimind/retrieval.py
├── class KeywordIndexRetriever   ← we wrote this
├── class BM25Retriever           ← we wrote this
└── class QmdRetriever            ← we would write this
```

#### How it works

```python
import json, subprocess
from wikimind.wiki import WikiStore

class QmdRetriever:
    name = "qmd"

    def __init__(self, store: WikiStore, qmd_bin: str = "qmd"):
        self.store = store
        self.qmd_bin = qmd_bin   # "qmd" if installed globally via npm

    def retrieve(self, query: str, top_k: int) -> dict[str, str]:
        try:
            result = subprocess.run(
                # "qmd query" = full hybrid: BM25 + vector + LLM re-ranking
                # "qmd search" = BM25 only (faster but no semantic search)
                [self.qmd_bin, "query", query,
                 "--top-k", str(top_k), "--json"],
                capture_output=True, text=True,
            )
        except FileNotFoundError:
            raise RetrievalError(
                "qmd not found. Install it first:\n"
                "  npm install -g @tobilu/qmd\n"
                "Then register your vault:\n"
                "  qmd collection add .wiki/vault/ --name wiki\n"
                "  qmd embed\n"
                "Or set retrieval_backend = \"bm25\" in wikimind.toml to use the built-in retriever."
            )
        if result.returncode != 0:
            raise RetrievalError(f"qmd query failed: {result.stderr.strip()}")

        hits = json.loads(result.stdout)   # [{path, content, score}, ...]
        return {h["path"]: h["content"] for h in hits}
```

Register in `make_retriever()`:
```python
if normalized == "qmd":
    return QmdRetriever(store, qmd_bin=cfg.wiki.qmd_bin or "qmd")
```

Config in `wikimind.toml`:
```toml
[wiki]
retrieval_backend = "qmd"
# qmd_bin = "qmd"   # full path if qmd is not on PATH
```

#### The full call chain when wiki_search is invoked

```
Claude Code
    │  calls tool
    ▼
wiki_search("machine learning")                    ← wikimind MCP server
    │
    ▼
QmdRetriever.retrieve("machine learning", top_k=10)    ← our Python code
    │  subprocess.run(["qmd", "query", "--json", ...])
    ▼
qmd starts, runs full hybrid pipeline:
    ├─ BM25 over registered collection             (local)
    ├─ Vector embedding search via GGUF model      (local, node-llama-cpp)
    ├─ Merge via RRF
    └─ LLM re-ranking via GGUF model               (local, node-llama-cpp)
    prints JSON → exits
    │
    ▼
QmdRetriever parses JSON → dict[path, content]
    │
    ▼
wiki_search returns semantic results to Claude Code
```

qmd MCP server: **never started, not involved.**

#### Installation requirement

qmd is a Node.js package installed via npm (not Go, not pip). The user installs it once globally:

```bash
npm install -g @tobilu/qmd
```

Then registers the vault as a collection and pre-computes embeddings:

```bash
qmd collection add .wiki/vault/ --name wiki
qmd embed
```

`qmd embed` must be re-run after new pages are added. This could be wired into
`wikimind ingest` automatically (call `qmd embed` as a post-ingest step when
`retrieval_backend = "qmd"`).

#### No second LLM config needed

Unlike what was initially assumed, qmd's LLM re-ranking uses **local GGUF models via
node-llama-cpp** — no external API key, no separate LLM config. The entire pipeline
(BM25 + vector + re-ranking) runs locally once qmd is installed. This makes the integration
simpler than originally described: one `wikimind.toml`, one `qmd` install, everything works.

**Pros:** Full hybrid BM25 + vector + LLM re-ranking, all local, no extra API keys.
~60 lines of WikiMind code. Works for all providers including Anthropic.  
**Cons:** User must install Node.js + qmd separately. Must run `qmd embed` to keep index
current after ingesting new pages. First-run GGUF model download may be large.

---

### Option B — Native embedding retriever: use our own LLM client

Add `retrieval_backend = "embedding"` using our existing `LLMClient` — no external binary,
single config, fully integrated into `wikimind.toml`.

#### How it works

1. At ingest time: generate an embedding vector for each wiki page → cache to `.wikimind/embeddings.json`
2. At query time: embed the query → cosine-score against all cached vectors → return top-k pages

```python
class EmbeddingRetriever:
    name = "embedding"

    def __init__(self, store: WikiStore, llm: LLMClient):
        self.store = store
        self.llm = llm
        self._cache = self._load_cache()  # {path: vector}

    def retrieve(self, query: str, top_k: int) -> dict[str, str]:
        query_vec = self.llm.embed(query)          # one API call per query
        scored = [
            (cosine_similarity(query_vec, vec), path)
            for path, vec in self._cache.items()
        ]
        scored.sort(reverse=True)
        return {path: self.store.read_page(path) for _, path in scored[:top_k]}
```

Cache invalidation: regenerate a page's embedding when its content hash changes (same hash
signal already used for dedup). Most queries cost one embedding call (the query itself).

**Pros:** Single config, uses our LLM client, no external binary, semantically aware.  
**Cons:** Not all providers support embeddings — Anthropic has no public embeddings API;
OpenAI does (`text-embedding-3-small`); Ollama does locally (`nomic-embed-text`). Adds
embedding cache management.

---

### Choosing between Option A and Option B

| Situation | Recommended option |
|---|---|
| Using `provider = "anthropic"` (default) | **Option A** — Anthropic has no embeddings API; qmd is fully local and works with any provider |
| Using `provider = "openai"` | **Option B** — `text-embedding-3-small` is cheap; fully integrated; or Option A if you prefer offline |
| Using `provider = "ollama"` | **Either** — both run fully offline; Option B is simpler (no extra install) |
| Want fully offline, no API calls for search | **Option A** — qmd runs entirely local including re-ranking |
| Want everything in one config, no extra installs | **Option B** |
| Willing to install Node.js + npm package | **Option A** — gets the best search quality out of the box |

Both options plug into the existing `Retriever` abstraction (`retrieval.py`) with no changes
to ingest, query, lint, or the MCP server.

---

### When to act on this

Trigger: wiki grows past ~200 pages **and** query quality degrades (users notice missing
relevant pages). BM25 is solid at moderate scale with zero extra dependencies — do not add
this complexity before the problem is real.

---

## Backlog Summary

| ID | Gap | Priority | Complexity | Status |
|---|---|---|---|---|
| GAP-1 | Interactive ingest (`--focus`, `--interactive`) | High | Medium | Not started |
| GAP-2 | overview.md synthesis (`wikimind synthesize`) | High | Low | Not started |
| GAP-3 | Atomic MCP ingest tool (`wiki_ingest_source`) | High | Low–Medium | Not started |
| GAP-4 | Image / multimodal handling in ingest | Medium | High | Not started |
| GAP-5 | Lint findings persisted (`--save`, wanted stubs) | Medium | Low | Not started |
| GAP-6 | Rich query formats (`--format table\|marp`) | Medium | Medium | Not started |
| GAP-7 | `wikimind log` command | Low | Low | Not started |
| GAP-8 | Obsidian init config + frontmatter guidance | Low | Low | Not started |
| GAP-9 | Deleted source detection in lint | Low | Low | Not started |
| GAP-10 | qmd hybrid/semantic search integration | Medium | Low–Medium | **Done** |
