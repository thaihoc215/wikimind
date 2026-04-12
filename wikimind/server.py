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
import logging
import shutil
import subprocess
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from wikimind.config import ConfigError, load_config
from wikimind.retrieval import make_retriever
from wikimind.wiki import WikiStore


def _setup_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("wikimind.server")
    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    return logger


def create_server(root: Path | None = None) -> FastMCP:
    """Create the MCP server bound to the wiki at `root` (defaults to cwd)."""
    try:
        cfg = load_config(root)
    except ConfigError as e:
        raise RuntimeError(f"WikiMind config error: {e}") from e

    log_path = cfg.wiki_path.parent / ".wikimind" / "server.log"
    logger = _setup_logger(log_path)

    store = WikiStore(cfg.wiki_path, cfg.raw_path)
    retriever = make_retriever(store, backend=cfg.wiki.retrieval_backend, wiki_config=cfg.wiki, root=cfg.root)
    logger.info("server started | backend=%s qmd_mode=%s wiki=%s", cfg.wiki.retrieval_backend, cfg.wiki.qmd_mode, cfg.wiki_path)

    # ── qmd background embed state ────────────────────────────────────────
    # _embed_dirty: True when pages have been written since the last embed.
    # _embed_thread: the currently running background embed thread, or None.
    # _embed_lock:   guards both of the above.
    #
    # Flow:
    #   wiki_write_page → set dirty, _trigger_embed() → returns immediately
    #   background thread → clears dirty before subprocess (so mid-embed writes
    #                        set it again), runs qmd embed, then exits
    #   wiki_search → _wait_for_embed() short-circuits if no thread running,
    #                 otherwise waits; then searches with a current index
    _embed_dirty = [False]
    _embed_thread: list[threading.Thread | None] = [None]
    _embed_lock = threading.Lock()

    def _run_embed() -> None:
        """Background worker: runs qmd embed then clears state."""
        with _embed_lock:
            _embed_dirty[0] = False  # clear BEFORE subprocess so mid-embed writes re-set it
        qmd_bin = cfg.wiki.qmd_bin or "qmd"
        if shutil.which(qmd_bin):
            logger.info("embed | start")
            try:
                result = subprocess.run(
                    [qmd_bin, "embed"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    cwd=str(cfg.root),
                    timeout=120,
                    check=False,
                )
                if result.returncode != 0:
                    logger.warning("embed | exit_code=%d stderr=%r", result.returncode, result.stderr[:200])
                else:
                    logger.info("embed | done")
            except subprocess.TimeoutExpired:
                logger.warning("embed | timed out after 120s")
            except Exception as exc:
                logger.warning("embed | error: %s", exc)
        with _embed_lock:
            _embed_thread[0] = None

    def _trigger_embed() -> None:
        """Fire-and-forget: start a background embed if dirty and none is running."""
        with _embed_lock:
            if not _embed_dirty[0]:
                return
            if _embed_thread[0] is not None and _embed_thread[0].is_alive():
                return  # already in progress; it will embed all pages written so far
            t = threading.Thread(target=_run_embed, daemon=True)
            _embed_thread[0] = t
            t.start()

    def _wait_for_embed() -> None:
        """Block until any in-progress background embed finishes (no-op if idle)."""
        with _embed_lock:
            t = _embed_thread[0]
        if t is not None:
            t.join(timeout=125)

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
            content = store.read_page(path)
            logger.info("wiki_read_page | path=%r bytes=%d", path, len(content))
            return content
        except FileNotFoundError:
            # Retry with .md extension — LLM may pass wikilink paths without extension
            if not path.endswith(".md"):
                try:
                    content = store.read_page(path + ".md")
                    logger.info("wiki_read_page | path=%r bytes=%d (auto .md)", path, len(content))
                    return content
                except (FileNotFoundError, ValueError):
                    pass
            logger.warning("wiki_read_page | not_found path=%r", path)
            return f"Page not found: {path}"
        except ValueError as e:
            logger.warning("wiki_read_page | invalid_path path=%r error=%s", path, e)
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
        _wait_for_embed()
        logger.info("wiki_search | algo=%s query=%r top_k=%d", retriever.name, query, top_k)
        pages = retriever.retrieve(query, top_k=top_k)
        logger.info("wiki_search | found=%d pages=%s", len(pages), list(pages.keys()))
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
            logger.info("wiki_write_page | %s path=%r bytes=%d", action, path, len(content))
            with _embed_lock:
                _embed_dirty[0] = True
            _trigger_embed()  # fire-and-forget; does not block
            return f"OK: {action} wiki/{path}"
        except ValueError as e:
            logger.warning("wiki_write_page | invalid_path path=%r error=%s", path, e)
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
        logger.info("wiki_update_index | added=%d removed=%d", len(entries_to_add), len(entries_to_remove))
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
        logger.info("wiki_append_log | entry=%r", entry[:80])
        return "OK: log entry appended"

    return mcp


def run_server(root: Path | None = None, transport: str = "stdio") -> None:
    """Start the MCP server."""
    server = create_server(root)
    server.run(transport=transport)
