"""WikiMind MCP Server.

Exposes wiki filesystem operations as MCP tools so Claude Code (or any
MCP-compatible LLM client) can read and write the wiki directly.

The LLM (Claude Code) handles all the intelligence — what to write, how to
cross-reference, what to update. This server just provides clean, structured
access to the wiki files.

No ANTHROPIC_API_KEY required when used through Claude Code.

Usage:
    wikimind serve              # stdio mode (default, for Claude Code)
    wikimind serve --transport sse  # HTTP/SSE mode
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from wikimind.config import ConfigError, load_config
from wikimind.retrieval import make_retriever
from wikimind.wiki import WikiStore


def create_server(root: Path | None = None) -> FastMCP:
    """Create the MCP server bound to the wiki at `root` (defaults to cwd)."""
    try:
        cfg = load_config(root)
    except ConfigError as e:
        raise RuntimeError(f"WikiMind config error: {e}") from e

    store = WikiStore(cfg.wiki_path, cfg.raw_path)
    retriever = make_retriever(store, backend=cfg.wiki.retrieval_backend)
    mcp = FastMCP(
        "wikimind",
        instructions=(
            "WikiMind wiki tools. Read wiki/index.md first to understand what "
            "pages exist, then read specific pages for details. Use write tools "
            "to update the wiki after analysis or discoveries."
        ),
    )

    # ── Read tools ────────────────────────────────────────────────────────

    @mcp.tool()
    def wiki_read_index() -> str:
        """Read wiki/index.md — the master catalog of all wiki pages.
        Always start here to understand what the wiki contains before querying.
        """
        return store.read_index()

    @mcp.tool()
    def wiki_read_page(path: str) -> str:
        """Read a specific wiki page by its relative path (e.g. 'entities/openai.md').
        Use wiki_read_index first to discover available page paths.
        """
        try:
            return store.read_page(path)
        except FileNotFoundError:
            return f"Page not found: {path}"
        except ValueError as e:
            return f"Invalid path: {e}"

    @mcp.tool()
    def wiki_search(query: str, top_k: int = 10) -> str:
        """Search wiki pages relevant to a query using the configured retrieval backend.
        Returns a JSON object mapping page paths to their content.
        Use this before answering questions to find the most relevant pages.

        Args:
            query: The search query or question
            top_k: Maximum number of pages to return (default 10)
        """
        pages = retriever.retrieve(query, top_k=top_k)
        if not pages:
            return json.dumps({"found": 0, "pages": {}})
        return json.dumps({"found": len(pages), "pages": pages}, ensure_ascii=False)

    @mcp.tool()
    def wiki_list_pages() -> str:
        """List all wiki pages with their paths.
        Returns a JSON array of relative paths (e.g. ['entities/openai.md', ...]).
        """
        pages = store.all_pages()
        paths = [str(p.relative_to(store.wiki_path)).replace("\\", "/") for p in pages]
        return json.dumps(paths)

    @mcp.tool()
    def wiki_status() -> str:
        """Get wiki statistics: page count, source count, last updated.
        Returns a JSON object with wiki health summary.
        """
        return json.dumps(
            {
                "page_count": store.get_page_count(),
                "source_count": store.get_source_count(),
                "unprocessed_sources": len(store.find_unprocessed_sources()),
                "last_updated": store.get_last_updated(),
                "wiki_path": str(store.wiki_path),
                "raw_path": str(store.raw_path),
            }
        )

    # ── Write tools ───────────────────────────────────────────────────────

    @mcp.tool()
    def wiki_write_page(path: str, content: str) -> str:
        """Write (create or update) a wiki page.

        IMPORTANT: Every wiki page MUST have YAML frontmatter:
            ---
            title: Page Title
            type: entity | concept | source | analysis | overview
            tags: [tag1, tag2]
            created: YYYY-MM-DD
            updated: YYYY-MM-DD
            sources: []
            ---

        Use [[wikilinks]] to cross-reference between pages.
        File paths use kebab-case: entities/some-entity.md

        Args:
            path: Relative path within wiki/ (e.g. 'entities/openai.md')
            content: Full markdown content including YAML frontmatter
        """
        try:
            action = "updated" if store.page_exists(path) else "created"
            store.write_page(path, content)
            return f"OK: {action} wiki/{path}"
        except ValueError as e:
            return f"Invalid path: {e}"

    @mcp.tool()
    def wiki_update_index(
        entries_to_add: list[str], entries_to_remove: list[str]
    ) -> str:
        """Add or remove entries from wiki/index.md.

        Entry format: '- [[page-name]] — One-line description of the page'

        Args:
            entries_to_add: Lines to add to index.md
            entries_to_remove: Lines to remove from index.md (exact match)
        """
        store.update_index(entries_to_add, entries_to_remove)
        return f"OK: added {len(entries_to_add)}, removed {len(entries_to_remove)} index entries"

    @mcp.tool()
    def wiki_append_log(entry: str) -> str:
        """Append an entry to wiki/log.md (the chronological wiki record).

        Entry format: '## [YYYY-MM-DD] <operation> | <title>\\n\\nDetails.'
        Examples:
            '## [2026-04-09] ingest | Article Title\\n\\nCreated 3 pages.'
            '## [2026-04-09] query | How does X relate to Y?\\n\\nSaved to analyses/'

        Args:
            entry: The log entry to append
        """
        store.append_log(entry)
        return "OK: log entry appended"

    return mcp


def run_server(root: Path | None = None, transport: str = "stdio") -> None:
    """Start the MCP server."""
    server = create_server(root)
    server.run(transport=transport)
