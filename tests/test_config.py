"""Tests for configuration loading and provider-specific API key behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from wikimind.config import ConfigError, load_config


def test_openai_provider_requires_api_key_env(tmp_path: Path, monkeypatch):
    (tmp_path / "wikimind.toml").write_text(
        """[project]
name = "Test"

[paths]
raw = "raw/"
wiki = "wiki/"

[llm]
provider = "openai"
model = "gpt-4o-mini"
api_key_env = "OPENAI_API_KEY"
""",
        encoding="utf-8",
    )
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = load_config(tmp_path)
    with pytest.raises(ConfigError):
        _ = cfg.llm.api_key


def test_max_budget_usd_loads_from_toml(tmp_path: Path):
    (tmp_path / "wikimind.toml").write_text(
        """[project]
name = "Test"

[paths]
raw = "raw/"
wiki = "wiki/"

[llm]
provider = "anthropic"
model = "claude-sonnet-4-20250514"
max_budget_usd = 2.5
""",
        encoding="utf-8",
    )
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    cfg = load_config(tmp_path)
    assert cfg.llm.max_budget_usd == 2.5


def test_max_budget_usd_defaults_to_zero(tmp_path: Path):
    (tmp_path / "wikimind.toml").write_text(
        """[project]
name = "Test"

[paths]
raw = "raw/"
wiki = "wiki/"
""",
        encoding="utf-8",
    )
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    cfg = load_config(tmp_path)
    assert cfg.llm.max_budget_usd == 0.0


def test_all_templates_have_required_files():
    """All bundled templates must have wikimind.toml, CLAUDE.md, index.md, overview.md."""
    from wikimind.cli import TEMPLATES_DIR

    required = {"wikimind.toml", "CLAUDE.md", "index.md", "overview.md"}
    for template_dir in TEMPLATES_DIR.iterdir():
        if not template_dir.is_dir():
            continue
        present = {f.name for f in template_dir.iterdir()}
        missing = required - present
        assert not missing, f"Template '{template_dir.name}' missing: {missing}"


def test_ollama_provider_allows_missing_api_key(tmp_path: Path, monkeypatch):
    (tmp_path / "wikimind.toml").write_text(
        """[project]
name = "Test"

[paths]
raw = "raw/"
wiki = "wiki/"

[llm]
provider = "ollama"
model = "llama3.1"
api_key_env = "OLLAMA_API_KEY"
""",
        encoding="utf-8",
    )
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()

    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    cfg = load_config(tmp_path)
    assert cfg.llm.api_key == ""
