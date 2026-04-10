"""Tests for the ingest operation (mocked LLM)."""

import pytest
from pathlib import Path
from wikimind.llm import LLMError
from wikimind.wiki import WikiStore
from wikimind.operations.ingest import ingest


def test_ingest_creates_pages(
    tmp_wiki: WikiStore, sample_source: Path, mock_llm_ingest
):
    result = ingest(sample_source, tmp_wiki, mock_llm_ingest)

    assert result.pages_created == 2
    assert result.pages_updated == 0
    assert "Ingested" in result.summary or result.summary != ""

    # Pages exist on disk
    assert (tmp_wiki.wiki_path / "sources" / "sample-article.md").exists()
    assert (tmp_wiki.wiki_path / "entities" / "openai.md").exists()


def test_ingest_updates_index(
    tmp_wiki: WikiStore, sample_source: Path, mock_llm_ingest
):
    ingest(sample_source, tmp_wiki, mock_llm_ingest)
    index = tmp_wiki.read_index()
    assert "[[sample-article]]" in index
    assert "[[openai]]" in index


def test_ingest_appends_log(tmp_wiki: WikiStore, sample_source: Path, mock_llm_ingest):
    ingest(sample_source, tmp_wiki, mock_llm_ingest)
    log = (tmp_wiki.wiki_path / "log.md").read_text(encoding="utf-8")
    assert "ingest" in log.lower()


def test_ingest_marks_as_ingested(
    tmp_wiki: WikiStore, sample_source: Path, mock_llm_ingest
):
    assert not tmp_wiki.is_already_ingested(sample_source)
    ingest(sample_source, tmp_wiki, mock_llm_ingest)
    assert tmp_wiki.is_already_ingested(sample_source)


def test_ingest_dedup_skips_unchanged(
    tmp_wiki: WikiStore, sample_source: Path, mock_llm_ingest
):
    ingest(sample_source, tmp_wiki, mock_llm_ingest)
    call_count_before = mock_llm_ingest.call.call_count

    # Second ingest of unchanged file — should skip
    result = ingest(sample_source, tmp_wiki, mock_llm_ingest)
    assert "Skipped" in result.summary
    assert mock_llm_ingest.call.call_count == call_count_before  # no new LLM calls


def test_ingest_force_reingest(
    tmp_wiki: WikiStore, sample_source: Path, mock_llm_ingest
):
    ingest(sample_source, tmp_wiki, mock_llm_ingest)
    call_count_before = mock_llm_ingest.call.call_count

    # Force re-ingest
    result = ingest(sample_source, tmp_wiki, mock_llm_ingest, force=True)
    assert mock_llm_ingest.call.call_count > call_count_before


def test_ingest_dry_run_no_files_written(
    tmp_wiki: WikiStore, sample_source: Path, mock_llm_ingest
):
    result = ingest(sample_source, tmp_wiki, mock_llm_ingest, dry_run=True)
    assert "[DRY RUN]" in result.summary
    # No files should have been written
    assert not (tmp_wiki.wiki_path / "sources" / "sample-article.md").exists()


def test_ingest_missing_file(tmp_wiki: WikiStore, mock_llm_ingest, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        ingest(tmp_path / "nonexistent.md", tmp_wiki, mock_llm_ingest)


def test_ingest_invalid_tool_output_raises_llm_error(
    tmp_wiki: WikiStore, sample_source: Path, mock_llm_ingest
):
    mock_llm_ingest.call.return_value = {
        "files_to_write": [{"path": "sources/x.md", "content": "# missing action"}],
        "log_entry": "## [2026-04-09] ingest | Broken",
        "summary": "broken",
    }

    with pytest.raises(LLMError):
        ingest(sample_source, tmp_wiki, mock_llm_ingest)


def test_ingest_pdf_without_pymupdf_raises_llm_error(
    tmp_wiki: WikiStore, mock_llm_ingest, tmp_path: Path
):
    """Ingesting a .pdf file without pymupdf4llm installed raises a clear LLMError."""
    pdf_file = tmp_path / "raw" / "paper.pdf"
    pdf_file.parent.mkdir(exist_ok=True)
    pdf_file.write_bytes(b"%PDF-1.4 fake pdf content")

    import sys
    import builtins

    real_import = builtins.__import__

    def block_pymupdf(name, *args, **kwargs):
        if name == "pymupdf4llm":
            raise ImportError("No module named 'pymupdf4llm'")
        return real_import(name, *args, **kwargs)

    import builtins
    builtins.__import__ = block_pymupdf
    try:
        with pytest.raises(LLMError, match="pip install wikimind\\[pdf\\]"):
            ingest(pdf_file, tmp_wiki, mock_llm_ingest)
    finally:
        builtins.__import__ = real_import
