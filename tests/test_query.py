"""Tests for the query operation (mocked LLM)."""

import pytest
from pathlib import Path
from wikimind.llm import LLMError
from wikimind.wiki import WikiStore
from wikimind.operations.query import query


def _populate_wiki(store: WikiStore) -> None:
    """Add some pages so queries have something to search."""
    store.write_page(
        "sources/sample-article.md",
        (
            "---\ntitle: Sample Article\ntype: source\ntags: [llm]\n"
            "created: 2026-04-09\nupdated: 2026-04-09\nsources: []\n---\n\n"
            "# Sample Article\n\nLLM content.\n"
        ),
    )
    store.write_page(
        "entities/openai.md",
        (
            "---\ntitle: OpenAI\ntype: entity\ntags: [company]\n"
            "created: 2026-04-09\nupdated: 2026-04-09\nsources: []\n---\n\n"
            "# OpenAI\n\nAI company.\n"
        ),
    )
    store.update_index(
        entries_to_add=[
            "- [[sample-article]] — LLM article",
            "- [[openai]] — AI company",
        ],
        entries_to_remove=[],
    )


def test_query_returns_answer(tmp_wiki: WikiStore, mock_llm_query):
    _populate_wiki(tmp_wiki)
    result = query("What is OpenAI?", tmp_wiki, mock_llm_query)
    assert result.answer
    assert result.confidence in ("high", "medium", "low")


def test_query_returns_citations(tmp_wiki: WikiStore, mock_llm_query):
    _populate_wiki(tmp_wiki)
    result = query("What is OpenAI?", tmp_wiki, mock_llm_query)
    assert len(result.citations) > 0


def test_query_cold_start_empty_wiki(tmp_wiki: WikiStore, mock_llm_query):
    # Empty wiki — should return guidance without calling LLM
    result = query("What is OpenAI?", tmp_wiki, mock_llm_query)
    assert "empty" in result.answer.lower() or "ingest" in result.answer.lower()
    mock_llm_query.call.assert_not_called()


def test_query_save_creates_page(tmp_wiki: WikiStore, mock_llm_query):
    _populate_wiki(tmp_wiki)
    result = query("What is OpenAI?", tmp_wiki, mock_llm_query, save=True)
    assert result.saved_path is not None
    assert (tmp_wiki.wiki_path / result.saved_path).exists()


def test_query_save_updates_index(tmp_wiki: WikiStore, mock_llm_query):
    _populate_wiki(tmp_wiki)
    query("What is OpenAI?", tmp_wiki, mock_llm_query, save=True)
    index = tmp_wiki.read_index()
    # The saved analysis should appear in index
    assert "what-is-openai" in index or "openai" in index.lower()


def test_query_save_appends_log(tmp_wiki: WikiStore, mock_llm_query):
    _populate_wiki(tmp_wiki)
    query("What is OpenAI?", tmp_wiki, mock_llm_query, save=True)
    log = (tmp_wiki.wiki_path / "log.md").read_text(encoding="utf-8")
    assert "query" in log.lower()


def test_query_no_save_no_page_written(tmp_wiki: WikiStore, mock_llm_query):
    _populate_wiki(tmp_wiki)
    result = query("What is OpenAI?", tmp_wiki, mock_llm_query, save=False)
    assert result.saved_path is None
    assert not list((tmp_wiki.wiki_path / "analyses").rglob("*.md"))


def test_query_invalid_tool_output_raises_llm_error(
    tmp_wiki: WikiStore, mock_llm_query
):
    _populate_wiki(tmp_wiki)
    mock_llm_query.call.return_value = {
        "answer": "Some answer",
        "citations": ["entities/openai.md"],
        "confidence": "definitely",
    }

    with pytest.raises(LLMError):
        query("What is OpenAI?", tmp_wiki, mock_llm_query)
