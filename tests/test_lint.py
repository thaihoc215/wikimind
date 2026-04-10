"""Tests for the lint operation (structural checks only, no LLM)."""

import pytest
from pathlib import Path
from wikimind.llm import LLMError
from wikimind.wiki import WikiStore
from wikimind.operations.lint import lint, fix


def _make_page(store: WikiStore, path: str, content: str) -> None:
    store.write_page(path, content)


def _valid_frontmatter(title: str, page_type: str = "entity") -> str:
    return (
        f"---\ntitle: {title}\ntype: {page_type}\ntags: [test]\n"
        f"created: 2026-04-09\nupdated: 2026-04-09\nsources: []\n---\n\n"
        f"# {title}\n\nContent.\n"
    )


def test_lint_clean_wiki_has_no_issues(tmp_wiki: WikiStore):
    # Add a page that's in the index and has valid frontmatter
    _make_page(tmp_wiki, "entities/entity-a.md", _valid_frontmatter("Entity A"))
    # Point to it from another page so it's not an orphan
    _make_page(
        tmp_wiki,
        "overview.md",
        "---\ntitle: Overview\ntype: overview\ntags: []\ncreated: 2026-04-09\nupdated: 2026-04-09\nsources: []\n---\n\nSee [[entity-a]].",
    )
    tmp_wiki.update_index(
        entries_to_add=["- [[entity-a]] — Entity A"],
        entries_to_remove=[],
    )
    report = lint(tmp_wiki)
    assert not report.broken_links
    assert not report.index_missing
    assert not report.missing_frontmatter


def test_lint_detects_broken_links(tmp_wiki: WikiStore):
    _make_page(
        tmp_wiki,
        "entities/page-with-broken-link.md",
        _valid_frontmatter("Page") + "\nSee [[nonexistent-page]].",
    )
    tmp_wiki.update_index(
        entries_to_add=["- [[page-with-broken-link]] — Has broken link"],
        entries_to_remove=[],
    )
    report = lint(tmp_wiki)
    broken_targets = [link for _, link in report.broken_links]
    assert "nonexistent-page" in broken_targets


def test_lint_detects_orphan_pages(tmp_wiki: WikiStore):
    _make_page(tmp_wiki, "entities/orphan.md", _valid_frontmatter("Orphan"))
    tmp_wiki.update_index(
        entries_to_add=["- [[orphan]] — No one links to me"],
        entries_to_remove=[],
    )
    report = lint(tmp_wiki)
    orphan_stems = [Path(p).stem for p in report.orphan_pages]
    assert "orphan" in orphan_stems


def test_lint_detects_index_desync(tmp_wiki: WikiStore):
    # Page on disk but not in index
    _make_page(tmp_wiki, "entities/unlisted.md", _valid_frontmatter("Unlisted"))
    # Do NOT add to index
    report = lint(tmp_wiki)
    missing_stems = [Path(p).stem for p in report.index_missing]
    assert "unlisted" in missing_stems


def test_lint_detects_missing_frontmatter(tmp_wiki: WikiStore):
    _make_page(
        tmp_wiki, "entities/no-frontmatter.md", "# No Frontmatter\n\nJust content.\n"
    )
    tmp_wiki.update_index(
        entries_to_add=["- [[no-frontmatter]] — Missing frontmatter"],
        entries_to_remove=[],
    )
    report = lint(tmp_wiki)
    pages_missing = [p for p, _ in report.missing_frontmatter]
    assert any("no-frontmatter" in p for p in pages_missing)


def test_lint_resolves_explicit_path_wikilinks(tmp_wiki: WikiStore):
    _make_page(tmp_wiki, "entities/openai.md", _valid_frontmatter("OpenAI Entity"))
    _make_page(
        tmp_wiki,
        "concepts/openai.md",
        _valid_frontmatter("OpenAI Concept", page_type="concept"),
    )
    _make_page(
        tmp_wiki,
        "overview.md",
        "---\ntitle: Overview\ntype: overview\ntags: []\ncreated: 2026-04-09\nupdated: 2026-04-09\nsources: []\n---\n\nSee [[entities/openai]].",
    )
    tmp_wiki.update_index(
        entries_to_add=[
            "- [[entities/openai]] — Entity page",
            "- [[concepts/openai]] — Concept page",
        ],
        entries_to_remove=[],
    )

    report = lint(tmp_wiki)
    assert not any(target == "entities/openai" for _, target in report.broken_links)


def test_fix_adds_missing_index_entries(tmp_wiki: WikiStore):
    _make_page(tmp_wiki, "entities/unlisted.md", _valid_frontmatter("Unlisted"))
    report = lint(tmp_wiki)
    assert report.index_missing

    fixed = fix(report, tmp_wiki)
    assert fixed > 0

    index = tmp_wiki.read_index()
    assert "[[unlisted]]" in index


def test_fix_creates_stub_for_broken_links(tmp_wiki: WikiStore):
    _make_page(
        tmp_wiki,
        "entities/source-page.md",
        _valid_frontmatter("Source") + "\nSee [[missing-entity]].",
    )
    tmp_wiki.update_index(
        entries_to_add=["- [[source-page]] — Has broken link"],
        entries_to_remove=[],
    )
    report = lint(tmp_wiki)
    assert report.broken_links

    fix(report, tmp_wiki)
    # Stub should now exist
    assert (tmp_wiki.wiki_path / "entities" / "missing-entity.md").exists()


def test_empty_wiki_has_no_issues(tmp_wiki: WikiStore):
    report = lint(tmp_wiki)
    # An empty wiki (just index.md and log.md) should have no issues
    assert not report.broken_links
    assert not report.orphan_pages


def test_semantic_lint_populates_findings(tmp_wiki: WikiStore, mock_llm_lint):
    _make_page(tmp_wiki, "entities/openai.md", _valid_frontmatter("OpenAI"))
    _make_page(
        tmp_wiki,
        "concepts/alignment.md",
        _valid_frontmatter("Alignment", page_type="concept"),
    )
    _make_page(
        tmp_wiki,
        "overview.md",
        "---\ntitle: Overview\ntype: overview\ntags: []\ncreated: 2026-04-09\nupdated: 2026-04-09\nsources: []\n---\n\nSee [[openai]] and [[alignment]].",
    )
    tmp_wiki.update_index(
        entries_to_add=[
            "- [[openai]] — Entity",
            "- [[alignment]] — Concept",
        ],
        entries_to_remove=[],
    )

    report = lint(tmp_wiki, llm=mock_llm_lint, semantic=True)

    assert report.semantic_contradictions
    assert report.semantic_missing_pages == ["safety-benchmarks", "model-evals"]
    assert report.semantic_suggested_sources
    mock_llm_lint.call.assert_called_once()


def test_semantic_lint_not_called_by_default(tmp_wiki: WikiStore, mock_llm_lint):
    _make_page(tmp_wiki, "entities/openai.md", _valid_frontmatter("OpenAI"))
    lint(tmp_wiki, llm=mock_llm_lint, semantic=False)
    mock_llm_lint.call.assert_not_called()


def test_semantic_lint_requires_llm(tmp_wiki: WikiStore):
    with pytest.raises(ValueError):
        lint(tmp_wiki, semantic=True)


def test_semantic_lint_invalid_tool_output_raises_llm_error(
    tmp_wiki: WikiStore, mock_llm_lint
):
    _make_page(tmp_wiki, "entities/openai.md", _valid_frontmatter("OpenAI"))
    mock_llm_lint.call.return_value = {
        "contradictions": [{"pages": ["entities/openai.md"]}],
        "missing_pages": [],
        "suggested_sources": [],
    }

    with pytest.raises(LLMError):
        lint(tmp_wiki, llm=mock_llm_lint, semantic=True)


def test_lint_detects_stale_sources(tmp_wiki: WikiStore):
    # Create a raw source and mark it as ingested
    raw_file = tmp_wiki.raw_path / "article.md"
    raw_file.write_text("# Original\n\nOriginal content.", encoding="utf-8")
    tmp_wiki.mark_ingested(raw_file)

    # Report should be clean immediately after ingestion
    report = lint(tmp_wiki)
    assert raw_file not in [Path(s) for s in report.stale_sources]

    # Modify the raw file so it's now stale
    raw_file.write_text("# Changed\n\nModified content.", encoding="utf-8")
    report = lint(tmp_wiki)
    assert any("article.md" in s for s in report.stale_sources)


def test_lint_no_stale_sources_for_unprocessed(tmp_wiki: WikiStore):
    # A raw file that was never ingested should NOT appear as stale
    raw_file = tmp_wiki.raw_path / "never-ingested.md"
    raw_file.write_text("# New file\n\nNot ingested yet.", encoding="utf-8")
    report = lint(tmp_wiki)
    assert not any("never-ingested" in s for s in report.stale_sources)
