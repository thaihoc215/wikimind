"""Tests for WikiStore file operations."""

import os
import pytest
from pathlib import Path
from wikimind.wiki import WikiStore


def test_read_index_empty(tmp_wiki: WikiStore):
    assert "Index" in tmp_wiki.read_index()


def test_write_and_read_page(tmp_wiki: WikiStore):
    tmp_wiki.write_page("entities/test.md", "# Test\n\nContent here.")
    content = tmp_wiki.read_page("entities/test.md")
    assert "Content here" in content


def test_write_page_creates_directories(tmp_wiki: WikiStore):
    tmp_wiki.write_page("deep/nested/page.md", "# Deep")
    assert (tmp_wiki.wiki_path / "deep" / "nested" / "page.md").exists()


def test_update_index_adds_entries(tmp_wiki: WikiStore):
    tmp_wiki.update_index(
        entries_to_add=["- [[my-page]] — My description"],
        entries_to_remove=[],
    )
    index = tmp_wiki.read_index()
    assert "[[my-page]]" in index


def test_update_index_removes_entries(tmp_wiki: WikiStore):
    tmp_wiki.update_index(
        entries_to_add=["- [[old-page]] — Old"],
        entries_to_remove=[],
    )
    tmp_wiki.update_index(
        entries_to_add=[],
        entries_to_remove=["- [[old-page]] — Old"],
    )
    index = tmp_wiki.read_index()
    assert "[[old-page]]" not in index


def test_update_index_no_duplicates(tmp_wiki: WikiStore):
    entry = "- [[my-page]] — Description"
    tmp_wiki.update_index(entries_to_add=[entry], entries_to_remove=[])
    tmp_wiki.update_index(entries_to_add=[entry], entries_to_remove=[])
    count = tmp_wiki.read_index().count("[[my-page]]")
    assert count == 1


def test_append_log(tmp_wiki: WikiStore):
    tmp_wiki.append_log("## [2026-04-09] ingest | Test Article\n\nDone.")
    log = (tmp_wiki.wiki_path / "log.md").read_text(encoding="utf-8")
    assert "Test Article" in log


def test_dedup_new_source(tmp_wiki: WikiStore, sample_source: Path):
    assert not tmp_wiki.is_already_ingested(sample_source)


def test_dedup_after_mark(tmp_wiki: WikiStore, sample_source: Path):
    tmp_wiki.mark_ingested(sample_source)
    assert tmp_wiki.is_already_ingested(sample_source)


def test_dedup_changed_source(tmp_wiki: WikiStore, sample_source: Path):
    tmp_wiki.mark_ingested(sample_source)
    # Modify source content
    sample_source.write_text("# Modified content\n", encoding="utf-8")
    assert not tmp_wiki.is_already_ingested(sample_source)


def test_all_pages(tmp_wiki: WikiStore):
    tmp_wiki.write_page("entities/a.md", "# A")
    tmp_wiki.write_page("concepts/b.md", "# B")
    pages = tmp_wiki.all_pages()
    stems = [p.stem for p in pages]
    assert "a" in stems
    assert "b" in stems


def test_find_relevant_pages(tmp_wiki: WikiStore):
    tmp_wiki.write_page("entities/openai.md", "# OpenAI\nAI company.")
    tmp_wiki.update_index(
        entries_to_add=["- [[openai]] — AI research company building GPT"],
        entries_to_remove=[],
    )
    relevant = tmp_wiki.find_relevant_pages(
        "What is OpenAI doing with language models?"
    )
    assert "entities/openai.md" in relevant


def test_parse_all_wikilinks(tmp_wiki: WikiStore):
    tmp_wiki.write_page("entities/a.md", "# A\nSee [[b]] and [[c]].")
    tmp_wiki.write_page("entities/b.md", "# B\nSee [[a]].")
    graph = tmp_wiki.parse_all_wikilinks()
    assert "b" in graph["entities/a.md"]
    assert "c" in graph["entities/a.md"]
    assert "a" in graph["entities/b.md"]


def test_resolve_wikilink_with_path_collisions(tmp_wiki: WikiStore):
    tmp_wiki.write_page("entities/openai.md", "# OpenAI entity")
    tmp_wiki.write_page("concepts/openai.md", "# OpenAI concept")

    # Bare stem is ambiguous; explicit path should resolve.
    assert tmp_wiki.resolve_wikilink("openai") is None
    assert tmp_wiki.resolve_wikilink("entities/openai") == "entities/openai.md"
    assert tmp_wiki.resolve_wikilink("concepts/openai") == "concepts/openai.md"


def test_get_page_count(tmp_wiki: WikiStore):
    initial = tmp_wiki.get_page_count()
    tmp_wiki.write_page("entities/x.md", "# X")
    assert tmp_wiki.get_page_count() == initial + 1


def test_find_unprocessed_sources(tmp_wiki: WikiStore, sample_source: Path):
    # Before ingesting, should be unprocessed
    unprocessed = tmp_wiki.find_unprocessed_sources()
    assert sample_source in unprocessed

    # After marking, should be gone
    tmp_wiki.mark_ingested(sample_source)
    unprocessed_after = tmp_wiki.find_unprocessed_sources()
    assert sample_source not in unprocessed_after


def test_write_page_rejects_path_traversal(tmp_wiki: WikiStore):
    with pytest.raises(ValueError):
        tmp_wiki.write_page("../escape.md", "# Escape")


def test_read_page_rejects_path_traversal(tmp_wiki: WikiStore):
    with pytest.raises(ValueError):
        tmp_wiki.read_page("../outside.md")


def test_page_exists_rejects_path_traversal(tmp_wiki: WikiStore):
    assert not tmp_wiki.page_exists("../outside.md")


def test_find_unprocessed_sources_handles_relative_ingest_key(
    tmp_wiki: WikiStore, sample_source: Path
):
    project_root = tmp_wiki.wiki_path.parent
    old_cwd = Path.cwd()
    try:
        os.chdir(project_root)
        tmp_wiki.mark_ingested(Path("raw") / sample_source.name)
    finally:
        os.chdir(old_cwd)

    unprocessed = tmp_wiki.find_unprocessed_sources()
    assert sample_source not in unprocessed


def test_find_stale_sources_detects_changed_file(
    tmp_wiki: WikiStore, sample_source: Path
):
    tmp_wiki.mark_ingested(sample_source)
    # No stale sources right after ingestion
    assert tmp_wiki.find_stale_sources() == []

    # Modify the source file
    sample_source.write_text("# Changed content\n\nThis is different now.", encoding="utf-8")
    stale = tmp_wiki.find_stale_sources()
    assert sample_source in stale


def test_find_stale_sources_ignores_unprocessed(
    tmp_wiki: WikiStore, sample_source: Path
):
    # File was never ingested — should not appear as stale
    stale = tmp_wiki.find_stale_sources()
    assert sample_source not in stale


def test_record_and_read_cost_history(tmp_wiki: WikiStore):
    tmp_wiki.record_cost("ingest", 1000, 500, 0.0105)
    tmp_wiki.record_cost("query", 800, 300, 0.0069)

    history = tmp_wiki.read_cost_history()
    assert history["total_input_tokens"] == 1800
    assert history["total_output_tokens"] == 800
    assert len(history["records"]) == 2
    assert history["records"][0]["command"] == "ingest"
    assert history["records"][1]["command"] == "query"
    assert history["total_cost_usd"] == round(0.0105 + 0.0069, 6)


def test_read_cost_history_returns_empty_when_no_file(tmp_wiki: WikiStore):
    history = tmp_wiki.read_cost_history()
    assert history["records"] == []
    assert history["total_input_tokens"] == 0


def test_is_already_ingested_handles_mixed_path_styles(
    tmp_wiki: WikiStore, sample_source: Path
):
    tmp_wiki.mark_ingested(sample_source)

    project_root = tmp_wiki.wiki_path.parent
    old_cwd = Path.cwd()
    try:
        os.chdir(project_root)
        rel = Path("raw") / sample_source.name
        assert tmp_wiki.is_already_ingested(rel)
    finally:
        os.chdir(old_cwd)


# ── delete_page / move_page ────────────────────────────────────────────────

def test_delete_page_removes_index_entry(tmp_wiki: WikiStore):
    """Deleting a page should automatically remove its index.md entry."""
    tmp_wiki.write_page("entities/gone.md", "# Gone")
    tmp_wiki.update_index(["- [[gone]] — will be removed"], [])
    assert "[[gone]]" in tmp_wiki.read_index()

    tmp_wiki.delete_page("entities/gone.md")

    assert not (tmp_wiki.wiki_path / "entities" / "gone.md").exists()
    assert "[[gone]]" not in tmp_wiki.read_index()


def test_delete_page_removes_full_path_index_entry(tmp_wiki: WikiStore):
    """Index entry using full path form [[entities/gone]] is also removed."""
    tmp_wiki.write_page("entities/gone.md", "# Gone")
    tmp_wiki.update_index(["- [[entities/gone]] — full path form"], [])

    tmp_wiki.delete_page("entities/gone.md")

    assert "[[entities/gone]]" not in tmp_wiki.read_index()


def test_move_page_rewrites_index_entry(tmp_wiki: WikiStore):
    """Moving a page should rewrite its [[wikilink]] in index.md."""
    tmp_wiki.write_page("entities/old.md", "# Old")
    tmp_wiki.update_index(["- [[old]] — the old page"], [])

    tmp_wiki.move_page("entities/old.md", "entities/new.md")

    index = tmp_wiki.read_index()
    assert "[[new]]" in index
    assert "[[old]]" not in index


def test_move_page_rewrites_wikilinks_in_other_pages(tmp_wiki: WikiStore):
    """Moving a page should update [[wikilinks]] that reference it in other pages."""
    tmp_wiki.write_page("entities/target.md", "# Target")
    tmp_wiki.write_page(
        "concepts/referrer.md",
        "# Referrer\n\nSee [[target]] for details. Also [[target#section|label]].",
    )

    tmp_wiki.move_page("entities/target.md", "entities/renamed.md")

    referrer = tmp_wiki.read_page("concepts/referrer.md")
    assert "[[renamed]]" in referrer
    assert "[[renamed#section|label]]" in referrer
    assert "[[target]]" not in referrer


def test_move_page_does_not_rewrite_unrelated_links(tmp_wiki: WikiStore):
    """Moving a page must not corrupt wikilinks to unrelated pages."""
    tmp_wiki.write_page("entities/foo.md", "# Foo")
    tmp_wiki.write_page("entities/bar.md", "# Bar")
    tmp_wiki.write_page("concepts/page.md", "# Page\n\nSee [[foo]] and [[bar]].")

    tmp_wiki.move_page("entities/foo.md", "entities/foo-renamed.md")

    content = tmp_wiki.read_page("concepts/page.md")
    assert "[[foo-renamed]]" in content
    assert "[[bar]]" in content  # unrelated link untouched


def test_move_page_rewrites_full_path_wikilinks(tmp_wiki: WikiStore):
    """[[entities/old]] form is also rewritten."""
    tmp_wiki.write_page("entities/old.md", "# Old")
    tmp_wiki.write_page("concepts/ref.md", "# Ref\n\nSee [[entities/old]].")

    tmp_wiki.move_page("entities/old.md", "entities/new.md")

    content = tmp_wiki.read_page("concepts/ref.md")
    assert "[[new]]" in content
    assert "[[entities/old]]" not in content
