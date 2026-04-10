"""Shared fixtures for WikiMind tests."""

import pytest
from pathlib import Path
from wikimind.wiki import WikiStore


@pytest.fixture
def tmp_wiki(tmp_path: Path) -> WikiStore:
    """A WikiStore backed by a fresh temp directory."""
    wiki_dir = tmp_path / "wiki"
    raw_dir = tmp_path / "raw"
    wiki_dir.mkdir()
    raw_dir.mkdir()
    (wiki_dir / "entities").mkdir()
    (wiki_dir / "concepts").mkdir()
    (wiki_dir / "sources").mkdir()
    (wiki_dir / "analyses").mkdir()

    # Minimal index and log
    (wiki_dir / "index.md").write_text("# Index\n", encoding="utf-8")
    (wiki_dir / "log.md").write_text("# Wiki Log\n", encoding="utf-8")

    return WikiStore(wiki_dir, raw_dir)


@pytest.fixture
def sample_source(tmp_path: Path) -> Path:
    """A sample markdown source file."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(exist_ok=True)
    src = raw_dir / "sample-article.md"
    src.write_text(
        "# The Rise of Large Language Models\n\n"
        "Large language models (LLMs) like GPT-4 and Claude have transformed NLP.\n"
        "Key players include OpenAI, Anthropic, and Google DeepMind.\n"
        "Transformers, introduced in 2017 by Vaswani et al., are the foundation.\n",
        encoding="utf-8",
    )
    return src


@pytest.fixture
def mock_llm_ingest(mocker):
    """Mocked LLMClient that returns a valid ingest tool_use response."""
    from wikimind.llm import LLMClient

    mock = mocker.MagicMock(spec=LLMClient)
    mock.call.return_value = {
        "files_to_write": [
            {
                "path": "sources/sample-article.md",
                "content": (
                    "---\n"
                    "title: The Rise of Large Language Models\n"
                    "type: source\n"
                    "tags: [llm, nlp, ai]\n"
                    "created: 2026-04-09\n"
                    "updated: 2026-04-09\n"
                    "sources: []\n"
                    "---\n\n"
                    "# The Rise of Large Language Models\n\n"
                    "Summary of key points about LLMs.\n"
                    "See also: [[openai]], [[anthropic]]\n"
                ),
                "action": "create",
            },
            {
                "path": "entities/openai.md",
                "content": (
                    "---\n"
                    "title: OpenAI\n"
                    "type: entity\n"
                    "tags: [company, ai]\n"
                    "created: 2026-04-09\n"
                    "updated: 2026-04-09\n"
                    "sources: [sources/sample-article]\n"
                    "---\n\n"
                    "# OpenAI\n\nAI research company, creator of GPT-4.\n"
                ),
                "action": "create",
            },
        ],
        "index_entries_to_add": [
            "- [[sample-article]] — Summary of LLM article",
            "- [[openai]] — AI research company",
        ],
        "index_entries_to_remove": [],
        "log_entry": "## [2026-04-09] ingest | The Rise of Large Language Models\n\nCreated 2 pages.",
        "summary": "Ingested LLM article, created source + entity pages.",
    }
    mock.token_summary.return_value = {
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "cost_usd": 0.0105,
    }
    return mock


@pytest.fixture
def mock_llm_query(mocker):
    """Mocked LLMClient that returns a valid query tool_use response."""
    from wikimind.llm import LLMClient

    mock = mocker.MagicMock(spec=LLMClient)
    mock.call.return_value = {
        "answer": (
            "According to [[sample-article]], large language models are built on "
            "the Transformer architecture introduced in 2017. Key companies include "
            "[[openai]] and [[anthropic]]."
        ),
        "citations": ["sources/sample-article.md", "entities/openai.md"],
        "confidence": "high",
        "knowledge_gaps": ["Specific model benchmarks not covered"],
    }
    mock.token_summary.return_value = {
        "input_tokens": 800,
        "output_tokens": 300,
        "total_tokens": 1100,
        "cost_usd": 0.0069,
    }
    return mock


@pytest.fixture
def mock_llm_lint(mocker):
    """Mocked LLMClient that returns a semantic lint report."""
    from wikimind.llm import LLMClient

    mock = mocker.MagicMock(spec=LLMClient)
    mock.call.return_value = {
        "contradictions": [
            {
                "pages": ["entities/openai.md", "concepts/alignment.md"],
                "description": "Different timelines are stated for model release dates.",
            }
        ],
        "missing_pages": ["safety-benchmarks", "model-evals"],
        "suggested_sources": [
            "A recent benchmark survey paper",
            "Official model release notes",
        ],
    }
    mock.token_summary.return_value = {
        "input_tokens": 1200,
        "output_tokens": 400,
        "total_tokens": 1600,
        "cost_usd": 0.0096,
    }
    return mock
