"""Load and validate wikimind.toml configuration."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjectConfig:
    name: str
    template: str = "general"


@dataclass
class PathsConfig:
    raw: str = ".wiki/raw/"
    wiki: str = ".wiki/vault/"


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str = ""
    max_tokens_per_call: int = 8192
    max_budget_usd: float = 0.0  # 0 = no limit

    @property
    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        provider = self.provider.strip().lower()
        if provider in {"anthropic", "openai"} and not key:
            raise ConfigError(
                f"Missing API key. Set the {self.api_key_env} environment variable."
            )
        return key


@dataclass
class WikiConfig:
    required_frontmatter: list[str] = field(
        default_factory=lambda: ["title", "type", "tags", "created", "updated"]
    )
    retrieval_backend: str = "bm25"
    categories: dict[str, str] = field(
        default_factory=lambda: {
            "entities": "People, organizations, tools, systems",
            "concepts": "Ideas, theories, patterns, principles",
            "sources": "One summary per raw source",
            "analyses": "Saved queries, comparisons, syntheses",
        }
    )


@dataclass
class Config:
    project: ProjectConfig
    paths: PathsConfig
    llm: LLMConfig
    wiki: WikiConfig

    # Resolved absolute paths (set after loading)
    root: Path = field(default_factory=Path.cwd)

    @property
    def raw_path(self) -> Path:
        return self.root / self.paths.raw

    @property
    def wiki_path(self) -> Path:
        return self.root / self.paths.wiki


class ConfigError(Exception):
    pass


def load_config(root: Path | None = None) -> Config:
    """Load wikimind.toml from root directory (defaults to cwd)."""
    root = root or Path.cwd()
    config_path = root / "wikimind.toml"

    if not config_path.exists():
        raise ConfigError(
            f"wikimind.toml not found in {root}. Run 'wikimind init' first."
        )

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    project_data = data.get("project", {})
    if "name" not in project_data:
        raise ConfigError("wikimind.toml missing [project] name field.")

    project = ProjectConfig(
        name=project_data["name"],
        template=project_data.get("template", "general"),
    )

    paths_data = data.get("paths", {})
    paths = PathsConfig(
        raw=paths_data.get("raw", ".wiki/raw/"),
        wiki=paths_data.get("wiki", ".wiki/vault/"),
    )

    llm_data = data.get("llm", {})
    llm = LLMConfig(
        provider=llm_data.get("provider", "anthropic"),
        model=llm_data.get("model", "claude-sonnet-4-20250514"),
        api_key_env=llm_data.get("api_key_env", "ANTHROPIC_API_KEY"),
        base_url=llm_data.get("base_url", ""),
        max_tokens_per_call=llm_data.get("max_tokens_per_call", 8192),
        max_budget_usd=float(llm_data.get("max_budget_usd", 0.0)),
    )

    wiki_data = data.get("wiki", {})
    wiki = WikiConfig(
        required_frontmatter=wiki_data.get(
            "required_frontmatter", ["title", "type", "tags", "created", "updated"]
        ),
        retrieval_backend=wiki_data.get("retrieval_backend", "bm25"),
        categories=wiki_data.get(
            "categories",
            {
                "entities": "People, organizations, tools, systems",
                "concepts": "Ideas, theories, patterns, principles",
                "sources": "One summary per raw source",
                "analyses": "Saved queries, comparisons, syntheses",
            },
        ),
    )

    cfg = Config(project=project, paths=paths, llm=llm, wiki=wiki, root=root)
    return cfg
