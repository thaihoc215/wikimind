"""CLI behavior tests."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from wikimind import cli as cli_module
from wikimind.cli import _update_claude_md, _WIKIMIND_START, _WIKIMIND_END
from wikimind.operations.ingest import IngestResult


runner = CliRunner()


# ── _update_claude_md unit tests ──────────────────────────────────────────────


def test_update_claude_md_creates_when_missing(tmp_path: Path):
    dest = tmp_path / "CLAUDE.md"
    status = _update_claude_md(
        dest, f"{_WIKIMIND_START}\n# WikiMind\n{_WIKIMIND_END}", force=False
    )
    assert status == "created"
    assert _WIKIMIND_START in dest.read_text()


def test_update_claude_md_appends_when_no_wikimind_section(tmp_path: Path):
    dest = tmp_path / "CLAUDE.md"
    dest.write_text("# My Project\n\nCustom instructions.", encoding="utf-8")
    status = _update_claude_md(
        dest, f"{_WIKIMIND_START}\n# WikiMind\n{_WIKIMIND_END}", force=False
    )
    assert status == "merged"
    content = dest.read_text()
    assert "My Project" in content
    assert "WikiMind" in content


def test_update_claude_md_skips_when_no_markers_and_no_force(tmp_path: Path):
    dest = tmp_path / "CLAUDE.md"
    dest.write_text(
        "# My Project\n\n# WikiMind Knowledge Base\nold content", encoding="utf-8"
    )
    status = _update_claude_md(
        dest,
        f"{_WIKIMIND_START}\n# WikiMind\nnew content\n{_WIKIMIND_END}",
        force=False,
    )
    assert status == "skipped"
    assert "old content" in dest.read_text()


def test_update_claude_md_replaces_old_format_with_force(tmp_path: Path):
    dest = tmp_path / "CLAUDE.md"
    dest.write_text(
        "# My custom instructions\n\n---\n\n# WikiMind Knowledge Base\nold wikimind content",
        encoding="utf-8",
    )
    new_section = (
        f"{_WIKIMIND_START}\n# WikiMind Knowledge Base\nnew content\n{_WIKIMIND_END}"
    )
    status = _update_claude_md(dest, new_section, force=True)
    assert status == "updated"
    content = dest.read_text()
    assert "My custom instructions" in content  # preserved
    assert "old wikimind content" not in content  # replaced
    assert "new content" in content


def test_update_claude_md_replaces_between_markers(tmp_path: Path):
    dest = tmp_path / "CLAUDE.md"
    dest.write_text(
        f"# My custom instructions\n\n{_WIKIMIND_START}\n# WikiMind (general)\nold\n{_WIKIMIND_END}\n\nmore custom",
        encoding="utf-8",
    )
    new_section = f"{_WIKIMIND_START}\n# WikiMind (code)\nnew\n{_WIKIMIND_END}"
    status = _update_claude_md(
        dest, new_section, force=False
    )  # force not needed when markers exist
    assert status == "updated"
    content = dest.read_text()
    assert "My custom instructions" in content  # preserved
    assert "more custom" in content  # preserved
    assert "WikiMind (general)" not in content  # replaced
    assert "WikiMind (code)" in content


def test_init_creates_template_specific_directories(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        cli_module.app, ["init", "--template", "code", "--name", "Test"]
    )
    assert result.exit_code == 0
    vault = tmp_path / ".wiki" / "vault"
    assert (vault / "modules").exists()
    assert (vault / "apis").exists()
    assert (vault / "patterns").exists()
    assert (vault / "decisions").exists()


def test_init_force_replaces_wikimind_section(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # First init with general
    runner.invoke(cli_module.app, ["init", "--template", "general", "--name", "Test"])
    claude_after_general = (tmp_path / "CLAUDE.md").read_text()
    assert "entities/" in claude_after_general

    # Second init with code --force
    result = runner.invoke(
        cli_module.app, ["init", "--template", "code", "--force", "--name", "Test"]
    )
    assert result.exit_code == 0
    assert "Updated" in result.output
    claude_after_code = (tmp_path / "CLAUDE.md").read_text()
    assert "modules/" in claude_after_code  # code template content
    assert "entities/" not in claude_after_code  # general template content gone


def test_init_without_force_skips_old_format_wikimind_section(
    tmp_path: Path, monkeypatch
):
    """Without markers (old format), second init without --force should skip CLAUDE.md."""
    monkeypatch.chdir(tmp_path)
    # Write a CLAUDE.md that looks like old format (no markers)
    claude = tmp_path / "CLAUDE.md"
    claude.write_text(
        "# My custom instructions\n\n---\n\n# WikiMind Knowledge Base\nold content",
        encoding="utf-8",
    )
    # Also write wikimind.toml so init doesn't fail
    (tmp_path / "wikimind.toml").write_text(
        '[project]\nname = "Test"\n[paths]\nraw = ".wiki/raw/"\nwiki = ".wiki/vault/"\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        cli_module.app, ["init", "--template", "code", "--name", "Test"]
    )
    assert result.exit_code == 0
    assert "Skipped" in result.output
    assert "old content" in claude.read_text()  # not replaced


def test_init_with_markers_replaces_without_force(tmp_path: Path, monkeypatch):
    """When markers are present, second init always replaces — --force not needed."""
    monkeypatch.chdir(tmp_path)
    # First init with general — writes markers
    runner.invoke(cli_module.app, ["init", "--template", "general", "--name", "Test"])
    # Second init with code — no --force needed because markers exist
    result = runner.invoke(
        cli_module.app, ["init", "--template", "code", "--name", "Test"]
    )
    assert result.exit_code == 0
    assert "Updated" in result.output
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "modules/" in content  # code template applied
    assert "entities/" not in content  # general content replaced


class _DummyLLM:
    def token_summary(self):
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        }


def _write_minimal_project(root: Path) -> None:
    (root / "raw").mkdir()
    (root / "wiki").mkdir()
    (root / "wikimind.toml").write_text(
        """[project]
name = "CLI Test"

[paths]
raw = "raw/"
wiki = "wiki/"

[llm]
provider = "anthropic"
model = "claude-sonnet-4-20250514"
api_key_env = "ANTHROPIC_API_KEY"
""",
        encoding="utf-8",
    )


def test_ingest_batch_exits_non_zero_if_any_file_fails(tmp_path: Path, monkeypatch):
    _write_minimal_project(tmp_path)
    (tmp_path / "raw" / "ok.md").write_text("# ok", encoding="utf-8")
    (tmp_path / "raw" / "fail.md").write_text("# fail", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "_make_llm", lambda cfg: _DummyLLM())

    def _fake_ingest(
        source_path, store, llm, retriever=None, dry_run=False, force=False
    ):
        if source_path.name == "fail.md":
            raise RuntimeError("boom")
        return IngestResult(pages_created=1, pages_updated=0, summary="ok")

    monkeypatch.setattr("wikimind.operations.ingest.ingest", _fake_ingest)

    result = runner.invoke(cli_module.app, ["ingest", "raw"])
    assert result.exit_code == 1
    assert "Ingest summary" in result.output
    assert "1 failed" in result.output


def test_ingest_batch_returns_zero_when_all_files_succeed(tmp_path: Path, monkeypatch):
    _write_minimal_project(tmp_path)
    (tmp_path / "raw" / "a.md").write_text("# a", encoding="utf-8")
    (tmp_path / "raw" / "b.md").write_text("# b", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "_make_llm", lambda cfg: _DummyLLM())

    def _fake_ingest(
        source_path, store, llm, retriever=None, dry_run=False, force=False
    ):
        return IngestResult(pages_created=1, pages_updated=0, summary="ok")

    monkeypatch.setattr("wikimind.operations.ingest.ingest", _fake_ingest)

    result = runner.invoke(cli_module.app, ["ingest", "raw"])
    assert result.exit_code == 0
    assert "2 succeeded" in result.output
    assert "0 failed" in result.output


# ── generate command tests ────────────────────────────────────────────────────


def test_generate_opencode_creates_agents_md_from_claude_md(
    tmp_path: Path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    claude = tmp_path / "CLAUDE.md"
    claude.write_text(
        f"{_WIKIMIND_START}\n# WikiMind\nsome instructions\n{_WIKIMIND_END}\n",
        encoding="utf-8",
    )
    result = runner.invoke(cli_module.app, ["generate", "--tool", "opencode"])
    assert result.exit_code == 0
    agents = tmp_path / "AGENTS.md"
    assert agents.exists()
    content = agents.read_text()
    assert "WikiMind" in content
    assert "some instructions" in content


def test_generate_opencode_updates_existing_agents_md(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        f"{_WIKIMIND_START}\n# WikiMind\nnew content\n{_WIKIMIND_END}\n",
        encoding="utf-8",
    )
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        f"# My own notes\n\n{_WIKIMIND_START}\n# WikiMind\nold content\n{_WIKIMIND_END}\n",
        encoding="utf-8",
    )
    result = runner.invoke(cli_module.app, ["generate", "--tool", "opencode"])
    assert result.exit_code == 0
    content = agents.read_text()
    assert "new content" in content
    assert "old content" not in content
    assert "My own notes" in content  # custom content preserved


def test_generate_opencode_fails_without_claude_md(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_module.app, ["generate", "--tool", "opencode"])
    assert result.exit_code != 0


def test_generate_vscode_creates_mcp_json(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_module.app, ["generate", "--tool", "vscode"])
    assert result.exit_code == 0
    mcp_path = tmp_path / ".vscode" / "mcp.json"
    assert mcp_path.exists()
    import json

    config = json.loads(mcp_path.read_text())
    assert "servers" in config
    assert "wikimind" in config["servers"]
    server = config["servers"]["wikimind"]
    assert server["args"] == ["serve"]
    assert "cwd" in server


def test_generate_vscode_updates_existing_mcp_json(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import json

    vscode_dir = tmp_path / ".vscode"
    vscode_dir.mkdir()
    mcp_path = vscode_dir / "mcp.json"
    mcp_path.write_text(
        json.dumps({"servers": {"other-tool": {"command": "other", "args": []}}}),
        encoding="utf-8",
    )
    result = runner.invoke(cli_module.app, ["generate", "--tool", "vscode"])
    assert result.exit_code == 0
    config = json.loads(mcp_path.read_text())
    assert "wikimind" in config["servers"]
    assert "other-tool" in config["servers"]  # existing entry preserved


def test_generate_unknown_tool_exits_nonzero(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_module.app, ["generate", "--tool", "unknown"])
    assert result.exit_code != 0


# ── generate opencode.json tests ─────────────────────────────────────────────


def test_generate_opencode_creates_opencode_json(tmp_path: Path, monkeypatch):
    """opencode.json is created from scratch when it does not exist."""
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        f"{_WIKIMIND_START}\n# WikiMind\ncontent\n{_WIKIMIND_END}\n",
        encoding="utf-8",
    )
    result = runner.invoke(cli_module.app, ["generate", "--tool", "opencode"])
    assert result.exit_code == 0

    oc = tmp_path / "opencode.json"
    assert oc.exists(), "opencode.json should be created"
    config = json.loads(oc.read_text())
    assert config.get("$schema") == "https://opencode.ai/config.json"
    mcp = config.get("mcp", {})
    assert "wikimind" in mcp
    entry = mcp["wikimind"]
    assert entry["type"] == "local"
    assert entry["enabled"] is True
    assert isinstance(entry["command"], list)
    assert entry["command"][-1] == "serve"


def test_generate_opencode_updates_existing_opencode_json(tmp_path: Path, monkeypatch):
    """wikimind MCP entry is added to an existing opencode.json without clobbering other keys."""
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        f"{_WIKIMIND_START}\n# WikiMind\ncontent\n{_WIKIMIND_END}\n",
        encoding="utf-8",
    )
    # Pre-existing opencode.json with a different MCP server
    existing = {
        "$schema": "https://opencode.ai/config.json",
        "theme": "dark",
        "mcp": {
            "other-tool": {
                "type": "local",
                "command": ["other", "run"],
                "enabled": True,
            }
        },
    }
    (tmp_path / "opencode.json").write_text(
        json.dumps(existing, indent=4), encoding="utf-8"
    )

    result = runner.invoke(cli_module.app, ["generate", "--tool", "opencode"])
    assert result.exit_code == 0

    config = json.loads((tmp_path / "opencode.json").read_text())
    # wikimind entry added
    assert "wikimind" in config["mcp"]
    # existing keys preserved
    assert "other-tool" in config["mcp"]
    assert config.get("theme") == "dark"


def test_generate_opencode_overwrites_existing_wikimind_entry(
    tmp_path: Path, monkeypatch
):
    """An outdated wikimind entry in opencode.json is replaced."""
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        f"{_WIKIMIND_START}\n# WikiMind\ncontent\n{_WIKIMIND_END}\n",
        encoding="utf-8",
    )
    existing = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "wikimind": {
                "type": "local",
                "command": ["old/path/wikimind.exe", "serve"],
                "enabled": False,
            }
        },
    }
    (tmp_path / "opencode.json").write_text(
        json.dumps(existing, indent=4), encoding="utf-8"
    )

    result = runner.invoke(cli_module.app, ["generate", "--tool", "opencode"])
    assert result.exit_code == 0

    config = json.loads((tmp_path / "opencode.json").read_text())
    entry = config["mcp"]["wikimind"]
    assert entry["enabled"] is True  # updated to True
    assert "old/path" not in entry["command"][0]


def test_generate_opencode_reads_exe_from_mcp_json(tmp_path: Path, monkeypatch):
    """Executable path is sourced from .mcp.json when it exists and the path is valid."""
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        f"{_WIKIMIND_START}\n# WikiMind\ncontent\n{_WIKIMIND_END}\n",
        encoding="utf-8",
    )
    # Create a fake executable so the path existence check passes
    fake_exe = tmp_path / "fake_wikimind.exe"
    fake_exe.write_text("", encoding="utf-8")

    mcp_config = {
        "mcpServers": {
            "wikimind": {
                "command": str(fake_exe),
                "args": ["serve"],
                "cwd": str(tmp_path),
            }
        }
    }
    (tmp_path / ".mcp.json").write_text(json.dumps(mcp_config), encoding="utf-8")

    result = runner.invoke(cli_module.app, ["generate", "--tool", "opencode"])
    assert result.exit_code == 0

    config = json.loads((tmp_path / "opencode.json").read_text())
    cmd = config["mcp"]["wikimind"]["command"]
    assert str(fake_exe) in cmd[0]


def test_generate_opencode_adds_schema_to_existing_json_without_it(
    tmp_path: Path, monkeypatch
):
    """$schema is inserted when opencode.json exists but lacks it."""
    import json

    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text(
        f"{_WIKIMIND_START}\n# WikiMind\ncontent\n{_WIKIMIND_END}\n",
        encoding="utf-8",
    )
    (tmp_path / "opencode.json").write_text(json.dumps({"mcp": {}}), encoding="utf-8")

    result = runner.invoke(cli_module.app, ["generate", "--tool", "opencode"])
    assert result.exit_code == 0

    config = json.loads((tmp_path / "opencode.json").read_text())
    assert config.get("$schema") == "https://opencode.ai/config.json"
