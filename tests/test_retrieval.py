"""Tests for retrieval backend abstraction."""

import json
import warnings
from unittest.mock import MagicMock, patch

import pytest

from wikimind.config import WikiConfig
from wikimind.retrieval import BM25Retriever, QmdRetriever, RetrievalError, make_retriever
from wikimind.wiki import WikiStore


def test_make_retriever_default_backend(tmp_wiki: WikiStore):
    tmp_wiki.write_page("entities/openai.md", "# OpenAI")
    tmp_wiki.update_index(
        entries_to_add=["- [[openai]] — AI lab"],
        entries_to_remove=[],
    )

    retriever = make_retriever(tmp_wiki, backend="index_keyword")
    pages = retriever.retrieve("openai", top_k=5)
    assert "entities/openai.md" in pages


def test_make_retriever_rejects_unknown_backend(tmp_wiki: WikiStore):
    with pytest.raises(RetrievalError):
        make_retriever(tmp_wiki, backend="vector")


def test_make_retriever_bm25_backend(tmp_wiki: WikiStore):
    tmp_wiki.write_page(
        "entities/openai.md",
        "# OpenAI\n\nOpenAI works on large language models and RLHF.",
    )
    tmp_wiki.write_page(
        "entities/anthropic.md",
        "# Anthropic\n\nAnthropic focuses on constitutional AI.",
    )

    retriever = make_retriever(tmp_wiki, backend="bm25")
    assert isinstance(retriever, BM25Retriever)

    pages = retriever.retrieve("rlhf openai", top_k=2)
    assert pages
    first_path = next(iter(pages.keys()))
    assert first_path == "entities/openai.md"


def test_bm25_retriever_ignores_empty_query(tmp_wiki: WikiStore):
    tmp_wiki.write_page("entities/openai.md", "# OpenAI")
    retriever = BM25Retriever(tmp_wiki)
    assert retriever.retrieve("   ", top_k=5) == {}


# ── QmdRetriever tests ────────────────────────────────────────────────────────


def test_qmd_retriever_fallback_to_bm25(tmp_wiki: WikiStore):
    """When qmd binary is not found, make_retriever falls back to BM25 with a warning."""
    config = WikiConfig(retrieval_backend="qmd", qmd_mode="vsearch", qmd_bin="qmd")
    with patch("wikimind.retrieval.shutil.which", return_value=None):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            retriever = make_retriever(tmp_wiki, backend="qmd", wiki_config=config)
            assert isinstance(retriever, BM25Retriever)
            assert len(w) == 1
            assert "falling back" in str(w[0].message).lower()


def test_make_retriever_qmd_backend(tmp_wiki: WikiStore):
    """Factory creates QmdRetriever when qmd binary is available."""
    config = WikiConfig(retrieval_backend="qmd", qmd_mode="vsearch", qmd_bin="qmd")
    with patch("wikimind.retrieval.shutil.which", return_value="/usr/local/bin/qmd"):
        retriever = make_retriever(tmp_wiki, backend="qmd", wiki_config=config)
        assert isinstance(retriever, QmdRetriever)
        assert retriever.mode == "vsearch"


@pytest.mark.parametrize("mode", ["search", "vsearch", "query"])
def test_qmd_retriever_modes(tmp_wiki: WikiStore, mode: str):
    """Each qmd mode uses the correct subcommand and parses results."""
    retriever = QmdRetriever(tmp_wiki, mode=mode, qmd_bin="qmd")
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps([
        {"path": "entities/openai.md", "content": "# OpenAI", "score": 0.95}
    ])

    with patch("wikimind.retrieval.subprocess.run", return_value=mock_result) as mock_run:
        pages = retriever.retrieve("openai", top_k=5)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "qmd"
        assert cmd[1] == mode
        assert cmd[2] == "openai"
        assert "--json" in cmd
        assert "entities/openai.md" in pages


def test_qmd_retriever_invalid_mode(tmp_wiki: WikiStore):
    """QmdRetriever rejects invalid modes at construction time."""
    with pytest.raises(RetrievalError, match="Invalid qmd_mode"):
        QmdRetriever(tmp_wiki, mode="invalid")


def test_qmd_retriever_empty_query(tmp_wiki: WikiStore):
    """QmdRetriever returns empty dict for blank queries and top_k=0."""
    retriever = QmdRetriever(tmp_wiki, mode="vsearch")
    assert retriever.retrieve("   ", top_k=5) == {}
    assert retriever.retrieve("hello", top_k=0) == {}


def test_qmd_retriever_subprocess_failure(tmp_wiki: WikiStore):
    """QmdRetriever returns empty dict when subprocess exits with non-zero code."""
    retriever = QmdRetriever(tmp_wiki, mode="vsearch")
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch("wikimind.retrieval.subprocess.run", return_value=mock_result):
        assert retriever.retrieve("test query", top_k=5) == {}


def test_qmd_retriever_top_k_respected(tmp_wiki: WikiStore):
    """QmdRetriever limits results to top_k even when subprocess returns more."""
    retriever = QmdRetriever(tmp_wiki, mode="vsearch")
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps([
        {"path": f"entities/page{i}.md", "content": f"# Page {i}", "score": 1.0 - i * 0.1}
        for i in range(5)
    ])

    with patch("wikimind.retrieval.subprocess.run", return_value=mock_result):
        pages = retriever.retrieve("test", top_k=2)
        assert len(pages) == 2
