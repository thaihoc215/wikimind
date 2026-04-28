"""Tests for MCP server tools."""

import asyncio
import json
from pathlib import Path

from wikimind.server import create_server


def _setup_project(root: Path) -> None:
    (root / "raw").mkdir()
    (root / "wiki").mkdir()
    (root / "wiki" / "entities").mkdir()
    (root / "wiki" / "concepts").mkdir()
    (root / "wiki" / "sources").mkdir()
    (root / "wiki" / "analyses").mkdir()
    (root / "wiki" / "index.md").write_text("# Index\n", encoding="utf-8")
    (root / "wiki" / "log.md").write_text("# Wiki Log\n", encoding="utf-8")
    (root / "wikimind.toml").write_text(
        """[project]
name = "Test Wiki"

[paths]
raw = "raw/"
wiki = "wiki/"
""",
        encoding="utf-8",
    )


def _tool_result_value(call_result) -> str:
    if isinstance(call_result, tuple) and len(call_result) == 2:
        _, meta = call_result
        if isinstance(meta, dict) and "result" in meta:
            return str(meta["result"])
    return str(call_result)


def test_server_registers_expected_tools(tmp_path: Path):
    _setup_project(tmp_path)
    server = create_server(tmp_path)

    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}

    assert names == {
        "wiki_read_index",
        "wiki_read_page",
        "wiki_search",
        "wiki_list_pages",
        "wiki_status",
        "wiki_write_page",
        "wiki_update_index",
        "wiki_append_log",
        "wiki_delete_page",
        "wiki_move_page",
    }


def test_server_write_and_read_page(tmp_path: Path):
    _setup_project(tmp_path)
    server = create_server(tmp_path)

    content = "---\ntitle: OpenAI\ntype: entity\ntags: []\ncreated: 2026-04-09\nupdated: 2026-04-09\nsources: []\n---\n\n# OpenAI"
    write_result = asyncio.run(
        server.call_tool(
            "wiki_write_page",
            {"path": "entities/openai.md", "content": content},
        )
    )
    assert "OK: created wiki/entities/openai.md" in _tool_result_value(write_result)

    read_result = asyncio.run(
        server.call_tool("wiki_read_page", {"path": "entities/openai.md"})
    )
    assert "# OpenAI" in _tool_result_value(read_result)


def test_server_rejects_path_traversal(tmp_path: Path):
    _setup_project(tmp_path)
    server = create_server(tmp_path)

    write_result = asyncio.run(
        server.call_tool(
            "wiki_write_page",
            {"path": "../escape.md", "content": "# escape"},
        )
    )
    assert "Invalid path:" in _tool_result_value(write_result)
    assert not (tmp_path / "escape.md").exists()

    read_result = asyncio.run(
        server.call_tool("wiki_read_page", {"path": "../wikimind.toml"})
    )
    assert "Invalid path:" in _tool_result_value(read_result)


def test_server_status_returns_json(tmp_path: Path):
    _setup_project(tmp_path)
    server = create_server(tmp_path)

    result = asyncio.run(server.call_tool("wiki_status", {}))
    payload = json.loads(_tool_result_value(result))
    assert "page_count" in payload
    assert "source_count" in payload


def test_server_write_page_auto_appends_md_extension(tmp_path: Path):
    """wiki_write_page should auto-append .md when the caller omits it."""
    _setup_project(tmp_path)
    server = create_server(tmp_path)

    content = "---\ntitle: Foo\ntype: entity\ntags: []\ncreated: 2026-04-09\nupdated: 2026-04-09\nsources: []\n---\n\n# Foo"
    write_result = asyncio.run(
        server.call_tool(
            "wiki_write_page",
            # deliberately omit .md
            {"path": "entities/foo", "content": content},
        )
    )
    # Tool should report the normalised path (with .md)
    assert "OK: created wiki/entities/foo.md" in _tool_result_value(write_result)
    # The file on disk must have the .md extension
    assert (tmp_path / "wiki" / "entities" / "foo.md").exists()
    # A file without .md must NOT have been created
    assert not (tmp_path / "wiki" / "entities" / "foo").exists()


def test_server_read_page_auto_appends_md_extension(tmp_path: Path):
    """wiki_read_page should fall back to path+.md when the caller omits the extension."""
    _setup_project(tmp_path)
    (tmp_path / "wiki" / "entities" / "bar.md").write_text("# Bar", encoding="utf-8")
    server = create_server(tmp_path)

    read_result = asyncio.run(
        server.call_tool("wiki_read_page", {"path": "entities/bar"})
    )
    assert "# Bar" in _tool_result_value(read_result)


def test_wiki_search_uses_configured_retriever(tmp_path: Path):
    """wiki_search should find pages by full content (BM25), not just index.md entries."""
    _setup_project(tmp_path)

    # Write a page whose content contains "authentication" but the index.md
    # entry deliberately omits that word — index_keyword would return nothing,
    # BM25 should find it.
    page_content = (
        "---\ntitle: Auth Service\ntype: entity\ntags: []\n"
        "created: 2026-04-09\nupdated: 2026-04-09\nsources: []\n---\n\n"
        "# Auth Service\n\nHandles authentication and OAuth token validation."
    )
    (tmp_path / "wiki" / "entities" / "auth-service.md").write_text(
        page_content, encoding="utf-8"
    )
    # Index entry is intentionally vague — no word from the query
    (tmp_path / "wiki" / "index.md").write_text(
        "# Index\n- [[auth-service]] — internal service\n", encoding="utf-8"
    )

    server = create_server(tmp_path)
    result = asyncio.run(
        server.call_tool("wiki_search", {"query": "authentication OAuth", "top_k": 5})
    )
    payload = json.loads(_tool_result_value(result))
    assert payload["found"] >= 1, "BM25 should find auth-service.md by its content"
    assert any("auth-service" in path for path in payload["pages"])


def test_server_delete_page(tmp_path: Path):
    """wiki_delete_page should remove the file and reject system files."""
    _setup_project(tmp_path)
    (tmp_path / "wiki" / "entities" / "to-delete.md").write_text("# Delete me", encoding="utf-8")
    server = create_server(tmp_path)

    # Happy path
    result = asyncio.run(
        server.call_tool("wiki_delete_page", {"path": "entities/to-delete.md"})
    )
    assert "OK: deleted" in _tool_result_value(result)
    assert not (tmp_path / "wiki" / "entities" / "to-delete.md").exists()

    # Non-existent page
    result = asyncio.run(
        server.call_tool("wiki_delete_page", {"path": "entities/ghost.md"})
    )
    assert "Page not found" in _tool_result_value(result)

    # Protected system file
    result = asyncio.run(
        server.call_tool("wiki_delete_page", {"path": "index.md"})
    )
    assert "Cannot delete" in _tool_result_value(result)
    assert (tmp_path / "wiki" / "index.md").exists()


def test_server_move_page(tmp_path: Path):
    """wiki_move_page should rename a page and reject invalid cases."""
    _setup_project(tmp_path)
    content = "# Moved"
    (tmp_path / "wiki" / "entities" / "old-name.md").write_text(content, encoding="utf-8")
    server = create_server(tmp_path)

    # Happy path
    result = asyncio.run(
        server.call_tool(
            "wiki_move_page",
            {"src_path": "entities/old-name.md", "dst_path": "entities/new-name.md"},
        )
    )
    assert "OK: moved" in _tool_result_value(result)
    assert not (tmp_path / "wiki" / "entities" / "old-name.md").exists()
    assert (tmp_path / "wiki" / "entities" / "new-name.md").exists()
    assert (tmp_path / "wiki" / "entities" / "new-name.md").read_text(encoding="utf-8") == content

    # Moving to a destination that already exists
    (tmp_path / "wiki" / "entities" / "existing.md").write_text("# Existing", encoding="utf-8")
    (tmp_path / "wiki" / "entities" / "src.md").write_text("# Src", encoding="utf-8")
    result = asyncio.run(
        server.call_tool(
            "wiki_move_page",
            {"src_path": "entities/src.md", "dst_path": "entities/existing.md"},
        )
    )
    assert "Destination already exists" in _tool_result_value(result)

    # Source does not exist
    result = asyncio.run(
        server.call_tool(
            "wiki_move_page",
            {"src_path": "entities/ghost.md", "dst_path": "entities/nowhere.md"},
        )
    )
    assert "Source not found" in _tool_result_value(result)

    # Auto-append .md on both sides
    (tmp_path / "wiki" / "entities" / "no-ext.md").write_text("# NoExt", encoding="utf-8")
    result = asyncio.run(
        server.call_tool(
            "wiki_move_page",
            {"src_path": "entities/no-ext", "dst_path": "entities/with-ext"},
        )
    )
    assert "OK: moved" in _tool_result_value(result)
    assert (tmp_path / "wiki" / "entities" / "with-ext.md").exists()
