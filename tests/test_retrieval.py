"""Tests for retrieval backend abstraction."""

import pytest

from wikimind.retrieval import BM25Retriever, RetrievalError, make_retriever
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
