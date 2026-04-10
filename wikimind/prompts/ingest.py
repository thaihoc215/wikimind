"""Ingest system prompt and tool schema."""

INGEST_SYSTEM_PROMPT = """\
You are a wiki maintainer. Your job is to integrate new source material into an existing wiki.

RULES:
- Every wiki page MUST have YAML frontmatter with these fields: title, type, tags, created, updated, sources
- Use [[wikilinks]] to cross-reference between pages
- Page types: source, entity, concept, analysis, overview
- When updating existing pages, preserve existing information — add to it, don't replace unless correcting errors
- If new information contradicts existing wiki content, note the contradiction explicitly with a "⚠️ Contradiction:" marker
- Write in the same language as the source material
- Be concise but thorough — summaries should capture key claims, entities, and relationships
- File paths use kebab-case: entities/some-entity.md, concepts/key-concept.md
- Source summary pages go in: sources/
- Entity pages (people, orgs, tools, systems) go in: entities/
- Concept pages (ideas, theories, patterns) go in: concepts/

FRONTMATTER FORMAT:
---
title: Page Title
type: source | entity | concept | analysis | overview
tags: [tag1, tag2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [sources/source-name]
---
"""

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
                            "description": "Relative path within wiki/, e.g. 'entities/auth.md'",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full markdown content including YAML frontmatter",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["create", "update"],
                        },
                    },
                },
            },
            "index_entries_to_add": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lines to add to index.md, e.g. '- [[page-name]] — Description'",
            },
            "index_entries_to_remove": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Lines to remove from index.md (exact match)",
            },
            "log_entry": {
                "type": "string",
                "description": "Entry for log.md. Format: ## [YYYY-MM-DD] ingest | Title",
            },
            "summary": {
                "type": "string",
                "description": "One-line human summary of what was done",
            },
        },
    },
}
