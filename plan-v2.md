# WikiMind v2 — Lean Implementation Plan

> "The LLM incrementally builds and maintains a persistent wiki."
> — Karpathy's original idea, implemented as simply as possible.

**What changed from plan v1:** Stripped everything that isn't essential for a working product. No daemon, no event queue, no 6-step pipeline, no scheduler. Just CLI + LLM + filesystem. The system works end-to-end before we optimize.

---

## I. What WikiMind Is

A **CLI tool** that uses an LLM to build and maintain a wiki from your raw sources.

```
You drop files into raw/    →  WikiMind reads them, writes wiki pages
You ask questions            →  WikiMind reads wiki, synthesizes answers
You run lint                 →  WikiMind health-checks the wiki
```

That's it. Three operations. Everything is markdown files on disk. You browse the wiki in Obsidian (or any markdown editor). The LLM does all the bookkeeping.

---

## II. Architecture — Karpathy's 3 Layers

```
┌─────────────────────────────────────────────────────┐
│                                                      │
│  Layer 1: Raw Sources  (you write, LLM reads)       │
│  raw/                                                │
│  ├── article.md                                      │
│  ├── paper.pdf                                       │
│  └── notes.md                                        │
│                                                      │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Layer 2: Wiki  (LLM writes, you read)              │
│  wiki/                                               │
│  ├── index.md          ← master catalog              │
│  ├── log.md            ← chronological record        │
│  ├── overview.md       ← topic/project overview      │
│  ├── entities/         ← people, tools, systems      │
│  ├── concepts/         ← ideas, patterns, theories   │
│  ├── sources/          ← one summary per raw source  │
│  └── analyses/         ← saved queries, comparisons  │
│                                                      │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Layer 3: Schema  (you + LLM co-evolve)             │
│  CLAUDE.md             ← LLM instructions            │
│  wikimind.toml         ← tool configuration          │
│                                                      │
└─────────────────────────────────────────────────────┘
```

**No database.** All state lives in markdown files. index.md is the LLM's navigation tool. Frontmatter is metadata. [[wikilinks]] are the graph. This is the same approach Obsidian uses — parse on read, no external index.

---

## III. Project Structure

```
wikimind/
├── wikimind/
│   ├── __init__.py
│   ├── cli.py              # Typer CLI (init, ingest, query, lint, status)
│   ├── config.py           # Load wikimind.toml
│   ├── llm.py              # LLM client (Anthropic SDK, structured output)
│   ├── wiki.py             # Read/write wiki files, manage index + log
│   ├── operations/
│   │   ├── __init__.py
│   │   ├── ingest.py       # Source → wiki pages
│   │   ├── query.py        # Question → answer with citations
│   │   └── lint.py         # Health check + auto-fix
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── ingest.py       # Ingest system prompt + tool schema
│   │   ├── query.py        # Query system prompt + tool schema
│   │   └── lint.py         # Lint system prompt + tool schema
│   └── templates/          # Init templates (general, code, research, book)
│       ├── general/
│       │   ├── wikimind.toml
│       │   ├── CLAUDE.md
│       │   ├── index.md
│       │   └── overview.md
│       └── ... (other templates later)
│
├── tests/
│   ├── test_wiki.py        # Wiki file operations
│   ├── test_ingest.py      # Ingest with mocked LLM
│   ├── test_query.py       # Query with mocked LLM
│   ├── test_lint.py        # Lint checks
│   └── conftest.py         # Fixtures: temp wiki dir, mock LLM
│
├── pyproject.toml
└── README.md
```

**~10 source files.** That's the whole application. If it needs more, something is wrong.

---

## IV. Core Operations

### Operation 1: Ingest

**What happens when you run `wikimind ingest raw/article.md`:**

```
Step 1: Read inputs
  ├── Read raw/article.md (the source)
  ├── Read wiki/index.md (what wiki currently knows)
  └── Find & read relevant existing wiki pages
      (keyword match source content against index entries → top 5)

Step 2: Single LLM call
  ├── System prompt: "You are a wiki maintainer..."
  ├── Context: source content + index + existing pages
  └── Structured output via tool_use:
      {
        "files_to_write": [
          {"path": "sources/article-title.md", "content": "...", "action": "create"},
          {"path": "entities/some-entity.md", "content": "...", "action": "update"},
          ...
        ],
        "index_entries_to_add": ["- [[article-title]] — Summary of article"],
        "index_entries_to_remove": [],
        "log_entry": "## [2026-04-09] ingest | Article Title\n..."
      }

Step 3: Execute file operations
  ├── Write each file (create dirs if needed)
  ├── Update wiki/index.md (add/remove entries)
  ├── Append to wiki/log.md
  └── Record to .wikimind/sources.json (dedup hash)

Step 4: Report
  └── Print: "Ingested article.md → created 2 pages, updated 1"
```

**Key design decisions:**

- **One LLM call, not six.** The old plan had classifier → analyzer → planner → writer → linker → validator as separate LLM calls. That's 6x the cost and complexity. A single well-prompted call with structured output does all of this. We can decompose later if quality suffers.
- **Relevant page pre-loading.** We can't send the entire wiki to the LLM. Instead: extract keywords from the source, grep index.md for matches, read those pages. Simple and effective up to ~200 pages.
- **Structured output via tool_use.** The LLM returns JSON through Anthropic's tool_use feature. This gives us reliable, parseable output — no regex-based extraction.
- **Dedup via content hash.** `.wikimind/sources.json` stores `{source_path: sha256_hash}`. Re-ingesting unchanged files is a no-op.

### Operation 2: Query

**What happens when you run `wikimind query "How does X relate to Y?"`:**

```
Step 1: Find relevant pages
  ├── Read wiki/index.md
  └── Simple relevance: keyword match question against index
      → Select top 10 page paths

Step 2: Read context
  └── Read those 10 wiki pages

Step 3: Single LLM call
  ├── System prompt: "Answer based on wiki content, cite with [[links]]..."
  ├── Context: question + relevant wiki pages
  └── Structured output:
      {
        "answer": "Based on [[entity-a]] and [[concept-b]], ...",
        "citations": ["entities/entity-a.md", "concepts/concept-b.md"],
        "confidence": "high",
        "suggested_followups": ["What about Z?"]
      }

Step 4: Output
  ├── Print answer to terminal
  └── If --save: write to wiki/analyses/question-slug.md
      + update index.md + append log.md
```

**Write-back is critical.** `wikimind query --save "..."` files the answer back into the wiki. This is what makes knowledge compound — your explorations become part of the wiki, not lost in terminal history.

### Operation 3: Lint

**What happens when you run `wikimind lint`:**

```
Structural checks (no LLM, instant):
  ├── Orphan pages: wiki pages with zero [[inbound links]]
  ├── Broken links: [[wikilinks]] pointing to non-existent pages
  ├── Index desync: pages on disk not listed in index.md
  ├── Missing frontmatter: pages without required YAML fields
  └── Stale sources: raw files changed since their wiki summary was written

Semantic checks (one LLM call):
  ├── Contradictions between pages
  ├── Important topics mentioned but lacking their own page
  └── Suggested new sources to investigate

Auto-fix (with --fix):
  ├── Add missing pages to index.md
  ├── Remove broken links or create stub pages
  └── Regenerate summaries for stale sources
```

**Structural checks are free** — just file operations. LLM is only used for semantic checks. `wikimind lint` without `--fix` is a read-only report.

---

## V. LLM Interaction Design

### Provider: Anthropic (Claude) only for MVP

One provider. One model. No router, no fallback, no budget guard. Add those later when the core works.

### Structured Output via tool_use

Every LLM call uses Claude's tool_use to get structured JSON back. This is more reliable than asking the LLM to output raw JSON in its response.

```python
# wikimind/llm.py

import anthropic

class LLMClient:
    def __init__(self, model: str, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def call(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict | None = None,
    ) -> dict:
        """Single LLM call. Returns the tool_use input (parsed JSON)."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice or {"type": "auto"},
        )

        # Track tokens
        self.total_input_tokens += response.usage.input_tokens
        self.total_output_tokens += response.usage.output_tokens

        # Extract tool_use result
        for block in response.content:
            if block.type == "tool_use":
                return block.input

        # Fallback: no tool was called
        raise LLMError("LLM did not return structured output")

    def cost_usd(self) -> float:
        """Approximate cost based on Claude Sonnet pricing."""
        return (self.total_input_tokens * 3.0 + self.total_output_tokens * 15.0) / 1_000_000
```

### Tool Schemas (what the LLM returns)

```python
# wikimind/prompts/ingest.py

INGEST_TOOL = {
    "name": "wiki_update",
    "description": "Write wiki pages based on the ingested source.",
    "input_schema": {
        "type": "object",
        "required": ["files_to_write", "log_entry", "summary"],
        "properties": {
            "files_to_write": {
                "type": "array",
                "description": "Wiki pages to create or update.",
                "items": {
                    "type": "object",
                    "required": ["path", "content", "action"],
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path within wiki/, e.g. 'entities/auth.md'"
                        },
                        "content": {
                            "type": "string",
                            "description": "Full markdown content including YAML frontmatter"
                        },
                        "action": {
                            "type": "string",
                            "enum": ["create", "update"]
                        }
                    }
                }
            },
            "index_entries_to_add": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lines to add to index.md, e.g. '- [[page-name]] — Description'"
            },
            "index_entries_to_remove": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lines to remove from index.md (exact match)"
            },
            "log_entry": {
                "type": "string",
                "description": "Entry for log.md. Format: ## [YYYY-MM-DD] ingest | Title"
            },
            "summary": {
                "type": "string",
                "description": "One-line human summary of what was done"
            }
        }
    }
}

INGEST_SYSTEM_PROMPT = """You are a wiki maintainer. Your job is to integrate new source material \
into an existing wiki.

RULES:
- Every wiki page MUST have YAML frontmatter: title, type, tags, created, updated, sources
- Use [[wikilinks]] to cross-reference between pages
- Page types: source, entity, concept, analysis, overview
- When updating existing pages, preserve information — add to it, don't replace unless correcting errors
- If new information contradicts existing wiki content, note the contradiction explicitly
- Write in the same language as the source material
- Be concise but thorough. Summaries should capture key claims, entities, and relationships
- File paths use kebab-case: entities/some-entity.md, concepts/key-concept.md"""
```

```python
# wikimind/prompts/query.py

QUERY_TOOL = {
    "name": "wiki_answer",
    "description": "Answer a question based on wiki content.",
    "input_schema": {
        "type": "object",
        "required": ["answer", "citations"],
        "properties": {
            "answer": {
                "type": "string",
                "description": "The answer in markdown, using [[wikilinks]] for citations"
            },
            "citations": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of wiki page paths used to answer"
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "How well the wiki covers this question"
            },
            "knowledge_gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Topics the wiki should cover to better answer this"
            }
        }
    }
}
```

### Context Window Management

For MVP, simple truncation:

```python
MAX_CONTEXT_CHARS = 150_000  # ~37K tokens, safe for 200K context window

def build_context(source: str, index: str, pages: dict[str, str]) -> str:
    """Assemble LLM context, truncating if needed."""
    context_parts = [
        f"## Source to ingest\n\n{source}",
        f"## Current wiki index\n\n{index}",
    ]

    remaining = MAX_CONTEXT_CHARS - sum(len(p) for p in context_parts)

    for path, content in pages.items():
        if len(content) > remaining:
            break
        context_parts.append(f"## Existing page: {path}\n\n{content}")
        remaining -= len(content)

    return "\n\n---\n\n".join(context_parts)
```

For large sources (PDFs, long articles), chunk and summarize:
- If source > 50K chars: split into ~10K chunks, summarize each, ingest the combined summary
- PDF support: use `pymupdf4llm` to extract markdown from PDF

---

## VI. Wiki Store

```python
# wikimind/wiki.py

import hashlib
import json
import re
from pathlib import Path
from datetime import datetime

class WikiStore:
    """All wiki file operations. No database — just filesystem."""

    def __init__(self, wiki_path: Path, raw_path: Path):
        self.wiki_path = wiki_path
        self.raw_path = raw_path
        self.meta_path = wiki_path.parent / ".wikimind"  # .wikimind/ for operational data

    # ── Read ──

    def read_index(self) -> str:
        return (self.wiki_path / "index.md").read_text(encoding="utf-8")

    def read_page(self, relative_path: str) -> str:
        return (self.wiki_path / relative_path).read_text(encoding="utf-8")

    def read_source(self, source_path: Path) -> str:
        return source_path.read_text(encoding="utf-8")

    def find_relevant_pages(self, text: str, top_k: int = 5) -> dict[str, str]:
        """Find wiki pages relevant to given text using index keyword matching."""
        index = self.read_index()
        index_lines = index.strip().split("\n")

        # Extract keywords from text (simple: words > 4 chars, lowercase)
        words = set(
            w.lower() for w in re.findall(r'\b\w{4,}\b', text)
        )

        # Score each index entry by keyword overlap
        scored = []
        for line in index_lines:
            if not line.strip().startswith("- [["):
                continue
            match = re.search(r'\[\[(.+?)\]\]', line)
            if not match:
                continue
            page_name = match.group(1)
            line_words = set(w.lower() for w in re.findall(r'\b\w{4,}\b', line))
            score = len(words & line_words)
            if score > 0:
                scored.append((score, page_name))

        scored.sort(reverse=True)
        top_pages = [name for _, name in scored[:top_k]]

        # Read those pages
        result = {}
        for name in top_pages:
            path = self._resolve_page_path(name)
            if path and path.exists():
                result[str(path.relative_to(self.wiki_path))] = path.read_text(encoding="utf-8")

        return result

    def _resolve_page_path(self, page_name: str) -> Path | None:
        """Find the file for a [[wikilink]] name."""
        for md in self.wiki_path.rglob("*.md"):
            if md.stem == page_name:
                return md
        return None

    # ── Write ──

    def write_page(self, relative_path: str, content: str):
        """Write a wiki page. Creates parent directories if needed."""
        full_path = self.wiki_path / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def update_index(self, entries_to_add: list[str], entries_to_remove: list[str]):
        """Add/remove entries from index.md."""
        index_path = self.wiki_path / "index.md"
        lines = index_path.read_text(encoding="utf-8").split("\n")

        # Remove
        if entries_to_remove:
            lines = [l for l in lines if l.strip() not in entries_to_remove]

        # Add (before the last blank line, or at end)
        # Find the right category section to insert into
        for entry in entries_to_add:
            if entry.strip() not in [l.strip() for l in lines]:
                lines.append(entry)

        index_path.write_text("\n".join(lines), encoding="utf-8")

    def append_log(self, entry: str):
        """Append entry to log.md."""
        log_path = self.wiki_path / "log.md"
        current = log_path.read_text(encoding="utf-8") if log_path.exists() else "# Wiki Log\n"
        log_path.write_text(current + "\n" + entry + "\n", encoding="utf-8")

    # ── Dedup ──

    def is_already_ingested(self, source_path: Path) -> bool:
        sources = self._load_sources_json()
        content = source_path.read_text(encoding="utf-8")
        current_hash = hashlib.sha256(content.encode()).hexdigest()
        stored = sources.get(str(source_path))
        return stored is not None and stored["hash"] == current_hash

    def mark_ingested(self, source_path: Path):
        sources = self._load_sources_json()
        content = source_path.read_text(encoding="utf-8")
        sources[str(source_path)] = {
            "hash": hashlib.sha256(content.encode()).hexdigest(),
            "ingested_at": datetime.now().isoformat(),
        }
        self._save_sources_json(sources)

    def _load_sources_json(self) -> dict:
        path = self.meta_path / "sources.json"
        if path.exists():
            return json.loads(path.read_text())
        return {}

    def _save_sources_json(self, data: dict):
        self.meta_path.mkdir(exist_ok=True)
        (self.meta_path / "sources.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    # ── Lint helpers ──

    def all_pages(self) -> list[Path]:
        return list(self.wiki_path.rglob("*.md"))

    def get_page_count(self) -> int:
        return len(self.all_pages())

    def find_unprocessed_sources(self) -> list[Path]:
        sources = self._load_sources_json()
        unprocessed = []
        for raw_file in self.raw_path.rglob("*"):
            if raw_file.is_file() and str(raw_file) not in sources:
                unprocessed.append(raw_file)
        return unprocessed

    def parse_all_wikilinks(self) -> dict[str, list[str]]:
        """Build link graph by parsing markdown. Like Obsidian — no database."""
        graph = {}
        for page in self.all_pages():
            content = page.read_text(encoding="utf-8")
            links = re.findall(r'\[\[(.+?)\]\]', content)
            graph[page.stem] = links
        return graph
```

---

## VII. CLI

```python
# wikimind/cli.py

import typer
from rich.console import Console
from pathlib import Path

app = typer.Typer(name="wikimind", help="LLM-powered wiki that maintains itself")
console = Console()


@app.command()
def init(
    template: str = typer.Option("general", help="general | code | research | book"),
    name: str = typer.Option(None, help="Project/topic name"),
):
    """Initialize WikiMind in the current directory."""
    # 1. Copy template files → wikimind.toml, CLAUDE.md
    # 2. Create raw/ directory
    # 3. Create wiki/ with index.md, log.md, overview.md
    # 4. Create .wikimind/ for operational data
    # 5. If CLAUDE.md already exists, merge rather than overwrite
    console.print(f"[green]WikiMind initialized[/green] (template: {template})")
    console.print("  raw/          ← drop your source files here")
    console.print("  wiki/         ← LLM-maintained wiki (open with Obsidian)")
    console.print("  CLAUDE.md     ← LLM instructions (the 'schema')")
    console.print("  wikimind.toml ← configuration")


@app.command()
def ingest(
    path: str = typer.Argument(..., help="File or directory to ingest"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show plan without writing"),
):
    """Ingest a raw source into the wiki."""
    # Handles single file or directory (batch all files in it)


@app.command()
def query(
    question: str = typer.Argument(..., help="Question to ask the wiki"),
    save: bool = typer.Option(False, "--save", help="Save answer as wiki page"),
):
    """Ask a question against the wiki."""


@app.command()
def lint(
    fix: bool = typer.Option(False, "--fix", help="Auto-fix issues"),
):
    """Health-check the wiki."""


@app.command()
def status():
    """Show wiki stats."""
    # Page count, source count, last update, unprocessed sources


@app.command()
def cost():
    """Show LLM token usage for this session/today."""
```

---

## VIII. Config

```toml
# wikimind.toml — minimal

[project]
name = "My Research"
template = "general"

[paths]
raw = "raw/"
wiki = "wiki/"

[llm]
provider = "anthropic"
model = "claude-sonnet-4-20250514"
api_key_env = "ANTHROPIC_API_KEY"
# max_tokens_per_call = 8192

[wiki]
# Page frontmatter fields required on every wiki page
required_frontmatter = ["title", "type", "tags", "created", "updated"]

# Categories — determines wiki/ subdirectories
[wiki.categories]
entities = "People, organizations, tools, systems"
concepts = "Ideas, theories, patterns, principles"
sources = "One summary per raw source"
analyses = "Saved queries, comparisons, syntheses"
```

---

## IX. CLAUDE.md — The Schema Layer

Generated by `wikimind init`. This is what makes an LLM agent (Claude Code, Codex, etc.) aware of the wiki. It's the most important file in the system.

```markdown
# WikiMind Knowledge Base

This project uses a persistent wiki in `wiki/` maintained by LLMs.

## Structure

- `wiki/index.md` — Master catalog of all wiki pages. READ THIS FIRST.
- `wiki/log.md` — Chronological record of all wiki changes.
- `wiki/overview.md` — High-level overview of the topic/project.
- `wiki/entities/` — Pages for people, organizations, tools, systems.
- `wiki/concepts/` — Pages for ideas, theories, patterns, principles.
- `wiki/sources/` — One summary page per raw source in `raw/`.
- `wiki/analyses/` — Saved query answers, comparisons, syntheses.
- `raw/` — Raw source documents. Immutable — never modify these.

## When working on this project

1. **Before deep-diving into files**, check `wiki/index.md` — the wiki may already
   have a summary that saves you from reading multiple source files.
2. **After making significant changes**, update the relevant wiki pages to keep
   the wiki in sync. Update `wiki/index.md` if you create new pages.
3. **When answering questions**, prefer citing wiki pages with [[wikilinks]].

## Wiki page format

Every wiki page must have YAML frontmatter:

```yaml
---
title: Page Title
type: entity | concept | source | analysis | overview
tags: [tag1, tag2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [sources/source-name]
---
```

Use [[wikilinks]] to cross-reference between pages. When new information
contradicts existing content, note the contradiction explicitly rather than
silently overwriting.

## CLI commands available

- `wikimind ingest raw/file.md` — Process a source into wiki pages
- `wikimind query "question"` — Ask the wiki a question
- `wikimind query --save "question"` — Ask and save the answer as a wiki page
- `wikimind lint` — Health-check the wiki
- `wikimind lint --fix` — Auto-fix wiki issues
```

---

## X. Dependencies — Minimal

```toml
# pyproject.toml

[project]
name = "wikimind"
version = "0.1.0"
description = "LLM-powered wiki that maintains itself"
requires-python = ">=3.11"

dependencies = [
    "typer>=0.9",               # CLI framework
    "rich>=13.0",               # Terminal formatting
    "anthropic>=0.40",          # Claude API
    "python-frontmatter>=1.1",  # Parse YAML frontmatter
    "python-slugify>=8.0",      # Slugify page names
    "tomli>=2.0",               # Parse wikimind.toml (Python <3.11 compat)
]

[project.optional-dependencies]
pdf = ["pymupdf4llm>=0.0.10"]  # PDF → markdown extraction

[project.scripts]
wikimind = "wikimind.cli:app"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

**6 dependencies.** Compare to plan v1's 12+. Every dependency must justify its existence.

---

## XI. Implementation Plan

### Phase 1: Working ingest (Week 1)

**Goal:** `wikimind init && wikimind ingest raw/article.md` works end-to-end.

```
Day 1-2: Scaffold
  ├── pyproject.toml + project structure
  ├── config.py: load wikimind.toml
  ├── wiki.py: WikiStore (read/write pages, index, log)
  └── Tests: wiki store CRUD, index update, log append

Day 3-4: LLM + Ingest
  ├── llm.py: LLMClient with tool_use
  ├── prompts/ingest.py: system prompt + tool schema
  ├── operations/ingest.py: full ingest flow
  └── Tests: ingest with mocked LLM (verify file operations)

Day 5: CLI + Init
  ├── cli.py: init + ingest commands
  ├── templates/general/: wikimind.toml, CLAUDE.md, index.md, overview.md
  └── Integration test: init → ingest → verify wiki state
```

**Milestone test:**
```bash
mkdir my-research && cd my-research
wikimind init --name "AI Safety Research"
cp ~/articles/alignment-paper.md raw/
wikimind ingest raw/alignment-paper.md
# → wiki/sources/alignment-paper.md exists
# → wiki/index.md lists the new page
# → wiki/log.md has an entry
# → wiki/entities/ and wiki/concepts/ may have new pages
```

### Phase 2: Working query (Week 2)

**Goal:** `wikimind query "What are the key arguments?"` returns a good answer.

```
Day 1-2: Query operation
  ├── prompts/query.py: system prompt + tool schema
  ├── operations/query.py: full query flow
  ├── query --save: write-back to wiki
  └── Tests: query with mocked LLM

Day 3: Lint (structural only)
  ├── operations/lint.py: orphans, broken links, index desync, missing frontmatter
  ├── lint --fix: auto-repair
  └── Tests: create broken wiki state → verify lint catches + fixes

Day 4-5: Polish + edge cases
  ├── status command
  ├── cost command (from LLMClient token tracking)
  ├── Cold-start: query on empty wiki → helpful message
  ├── Large file handling: chunk + summarize for sources > 50K chars
  ├── Error handling: API failures, invalid responses, missing config
  └── Batch ingest: wikimind ingest raw/ (all files)
```

**Milestone test:**
```bash
wikimind ingest raw/paper-1.md
wikimind ingest raw/paper-2.md
wikimind query "How do these papers relate?"
wikimind query --save "Compare the methodologies"
# → wiki/analyses/compare-the-methodologies.md exists
wikimind lint
# → Reports any issues
wikimind status
# → Shows page count, source count, etc.
```

### Phase 3: MCP Server (Week 3)

**Goal:** Claude Code automatically uses the wiki through MCP tools.

```
  ├── server.py: FastMCP server (wiki_search, wiki_read, wiki_write, wiki_query)
  ├── CLI: wikimind serve --mcp
  ├── Generate .mcp.json in wikimind init
  └── Test: Claude Code connects → uses wiki tools
```

### Phase 4: Refinement (Week 4+)

```
  ├── BM25 search (when index-based matching isn't enough)
  ├── Multiple templates (code, research, book)
  ├── Lint semantic checks (contradictions — requires LLM)
  ├── Multi-provider support (OpenAI, Ollama)
  ├── Budget guard
  ├── File watcher (auto-ingest when raw/ changes)
  └── Documentation + PyPI publish
```

---

## XII. What's Intentionally Deferred

| Feature | Why deferred | When to add |
|---------|-------------|-------------|
| Daemon / file watcher | MCP + CLI is enough. Most updates happen through the LLM agent | Phase 4, if users ask for it |
| Event queue / debounce / batcher | Over-engineering for < 100 sources. Just ingest one at a time | If batch performance matters |
| 6-step pipeline | Single LLM call is simpler, cheaper, and probably good enough | Only if output quality is measurably worse |
| Model router | One model simplifies everything. Switch model in config if needed | When cost becomes a real problem |
| SQLite database | Markdown + JSON is sufficient up to ~500 pages. Obsidian proves this | When search performance degrades |
| Git hooks | MCP server + manual CLI covers the same use case less intrusively | Phase 4 for code projects |
| Semantic search / embeddings | BM25 + index.md keyword matching works for moderate scale | When wiki exceeds ~200 pages |
| HTTP API | CLI + MCP covers all use cases. REST API is for integrations | If external tools need access |

---

## XIII. Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| LLM writes bad wiki pages | `--dry-run` flag shows plan before writing. `git init` the wiki for version history. Lint catches structural issues. |
| LLM returns unparseable output | tool_use gives structured JSON. On failure: retry once. On second failure: log error, skip. |
| Source too large for context window | Detect size > 50K chars → chunk into ~10K segments → summarize each → ingest combined summary. |
| Index.md grows too large to send to LLM | At ~500 entries (~50K chars), switch to BM25 search instead of sending full index. This is a Phase 4 problem. |
| Cost runaway | Track tokens per call in LLMClient. `wikimind cost` shows spending. Add budget guard in Phase 4 if needed. |
| Wiki drift (wiki says X, but reality changed) | `wikimind lint` detects stale pages. Regular lint keeps wiki honest. |
| Concurrent writes (two ingests at once) | MVP: don't support concurrent writes. CLI is single-threaded. File-level atomicity (write to .tmp, rename) prevents corruption. |

---

## XIV. Success Criteria

**Phase 1 is done when:**
- [ ] `wikimind init` creates a valid project structure with CLAUDE.md
- [ ] `wikimind ingest raw/article.md` produces wiki pages with correct frontmatter and [[wikilinks]]
- [ ] Re-ingesting the same file is a no-op (dedup works)
- [ ] index.md and log.md are updated correctly
- [ ] All tests pass with mocked LLM

**Phase 2 is done when:**
- [ ] `wikimind query "question"` returns answers citing wiki pages
- [ ] `wikimind query --save` writes back to the wiki
- [ ] `wikimind lint` catches orphans, broken links, index desync
- [ ] `wikimind lint --fix` repairs what it can
- [ ] Ingesting 10 sources produces a coherent, interlinked wiki
- [ ] Opening wiki/ in Obsidian shows a useful graph view

**The whole thing is working when:**
A user can build a 50+ page wiki over a week of regular use, and the wiki is genuinely more useful than re-reading the raw sources every time.
