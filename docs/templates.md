# WikiMind Templates

When you run `wikimind init`, you can optionally specify a template. Templates define how the LLM categorizes and organizes the knowledge base by setting up specific folders (categories) and giving the LLM tailored instructions via `CLAUDE.md` and `wikimind.toml`.

```bash
wikimind init --template general   # (default)
wikimind init --template code
wikimind init --template research
wikimind init --template book
```

This document explains what each template is designed for and how it structures your wiki.

---

## 1. `general` (Default)
**Best for:** Personal wikis, general note-taking, or topic deep-dives.

This is the standard layout. It splits the world into concrete "things" and abstract "ideas." It's flexible enough for almost any use case if you don't have a specific domain in mind.

**Categories (Folders):**
- `entities/` — Concrete things: People, organizations, tools, systems.
- `concepts/` — Abstract things: Ideas, theories, patterns, principles.
- `sources/` — One summary page per raw source you ingest.
- `analyses/` — Saved queries (`wikimind query --save`), comparisons, syntheses.

---

## 2. `code`
**Best for:** Documenting software projects, codebases, or software architecture.

This template treats WikiMind as an architectural knowledge base. Rather than generating low-level docstrings, the LLM extracts system boundaries, API contracts, design patterns, and architectural decisions from your code or design docs.

**Categories (Folders):**
- `modules/` — Source files, classes, functions, components.
- `apis/` — API documentation overview: endpoints, request/response shapes, examples, summaries.
- `apis/api-detail/` — API detail: business flow overview, business logic deep-dives, API layer internals.
- `patterns/` — Design patterns, architectural decisions, conventions.
- `decisions/` — Architecture Decision Records (ADRs).
- `diagrams/` — All diagrams: Mermaid, UML, PlantUML, draw.io, etc.
- `diagrams/apis/` — Diagrams specific to API flows and contracts.
- `sources/` — One summary page per raw source.
- `analyses/` — Saved queries, comparisons, syntheses.

---

## 3. `research`
**Best for:** Academic work, literature reviews, or tracking industry papers.

This template is optimized for ingesting academic PDFs (or markdown conversions of them). The LLM is instructed to extract methodologies, trace citations to authors/labs, and catalog datasets or benchmarks mentioned in the papers.

**Categories (Folders):**
- `papers/` — Academic papers, preprints, technical reports.
- `concepts/` — Theories, methods, frameworks, algorithms.
- `authors/` — Researchers, labs, institutions.
- `datasets/` — Datasets, benchmarks, corpora.
- `sources/` — One summary page per raw source.
- `analyses/` — Saved queries, comparisons, syntheses.

---

## 4. `book`
**Best for:** Literature analysis, novel outlining, or deep-reading non-fiction.

This template is designed for narrative and thematic extraction. If you ingest chapters of a book, the LLM will map out character arcs, extract notable quotes, and tie events to overarching themes.

**Categories (Folders):**
- `chapters/` — Chapter summaries and key events.
- `characters/` — Character profiles and development arcs.
- `themes/` — Major themes, motifs, and symbols.
- `quotes/` — Notable passages and excerpts.
- `sources/` — One summary page per raw source.
- `analyses/` — Saved queries, comparisons, syntheses.

---

## Customizing Templates

Templates are just starting points. You are not locked into these structures! If you want to create your own custom layout:

1. Run `wikimind init` (with any template).
2. Open `wikimind.toml` and edit the `[wiki.categories]` block. For example:
   ```toml
   [wiki.categories]
   meetings = "Meeting notes and transcripts"
   projects = "Active projects and milestones"
   tasks = "Action items and follow-ups"
   sources = "One summary per raw source"
   ```
3. Open `CLAUDE.md` and update the `## Structure` section to explain your new categories to the LLM.
4. Run `wikimind ingest` — the LLM will automatically adapt and create pages in your new categories!