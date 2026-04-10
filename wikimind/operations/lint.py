"""Lint operation: structural wiki health checks + optional LLM semantic checks."""

from __future__ import annotations

import re
from pathlib import Path

import frontmatter

from wikimind.llm import LLMClient, LLMError
from wikimind.llm_schema import LLMOutputValidationError, parse_lint_tool_output
from wikimind.prompts.lint import LINT_SYSTEM_PROMPT, LINT_TOOL
from wikimind.wiki import WikiStore


class LintReport:
    def __init__(self):
        self.orphan_pages: list[str] = []
        self.broken_links: list[tuple[str, str]] = []  # (page, broken_link)
        self.index_missing: list[str] = []  # pages on disk but not in index
        self.missing_frontmatter: list[
            tuple[str, list[str]]
        ] = []  # (page, missing_fields)
        self.stale_sources: list[str] = []
        self.semantic_contradictions: list[tuple[list[str], str]] = []
        self.semantic_missing_pages: list[str] = []
        self.semantic_suggested_sources: list[str] = []

    @property
    def has_structural_issues(self) -> bool:
        return bool(
            self.orphan_pages
            or self.broken_links
            or self.index_missing
            or self.missing_frontmatter
            or self.stale_sources
        )

    @property
    def has_semantic_findings(self) -> bool:
        return bool(
            self.semantic_contradictions
            or self.semantic_missing_pages
            or self.semantic_suggested_sources
        )

    @property
    def has_issues(self) -> bool:
        return self.has_structural_issues or self.has_semantic_findings

    def issue_count(self) -> int:
        return (
            len(self.orphan_pages)
            + len(self.broken_links)
            + len(self.index_missing)
            + len(self.missing_frontmatter)
            + len(self.stale_sources)
            + len(self.semantic_contradictions)
            + len(self.semantic_missing_pages)
            + len(self.semantic_suggested_sources)
        )


def lint(
    store: WikiStore,
    required_frontmatter: list[str] | None = None,
    llm: LLMClient | None = None,
    semantic: bool = False,
    max_semantic_pages: int = 40,
    max_context_chars: int = 150_000,
) -> LintReport:
    """Run structural lint checks and optional semantic checks with one LLM call."""
    report = LintReport()
    required_fields = required_frontmatter or [
        "title",
        "type",
        "tags",
        "created",
        "updated",
    ]

    if semantic and llm is None:
        raise ValueError("Semantic lint requested but no LLM client was provided.")

    if not store.wiki_path.exists():
        return report

    pages = store.all_pages()
    if not pages:
        return report

    # Build canonical page path set and link registry
    page_paths = {str(p.relative_to(store.wiki_path)).replace("\\", "/") for p in pages}

    # Build link graph
    link_graph = store.parse_all_wikilinks()
    link_registry = store.build_link_registry()

    # 1. Broken links: [[wikilinks]] pointing to non-existent pages
    for page in pages:
        rel_page = str(page.relative_to(store.wiki_path)).replace("\\", "/")
        links = link_graph.get(rel_page, [])
        for target in links:
            resolved = store.resolve_wikilink(target, registry=link_registry)
            if resolved is None:
                report.broken_links.append((rel_page, target))

    # 2. Orphan pages: wiki pages with zero inbound [[wikilinks]]
    # Exclude navigation pages (index, log) from counting as sources of inbound links,
    # since they're catalogs — a link in index.md shouldn't save a page from being orphaned.
    nav_pages = {"index.md", "log.md"}
    inbound: dict[str, int] = {path: 0 for path in page_paths}
    for source_path, links in link_graph.items():
        if Path(source_path).name in nav_pages:
            continue
        for target in links:
            resolved = store.resolve_wikilink(target, registry=link_registry)
            if resolved in inbound:
                inbound[resolved] += 1

    # index.md, log.md, overview.md are not expected to have inbound links
    skip_orphan_check = {"index.md", "log.md", "overview.md"}
    for page in pages:
        rel = str(page.relative_to(store.wiki_path)).replace("\\", "/")
        if page.name in skip_orphan_check:
            continue
        if inbound.get(rel, 0) == 0:
            report.orphan_pages.append(rel)

    # 3. Index desync: pages on disk not listed in index.md
    index_text = store.read_index()
    index_targets = [
        store.normalize_wikilink_target(raw)
        for raw in re.findall(r"\[\[(.+?)\]\]", index_text)
    ]
    index_resolved_paths = {
        resolved
        for resolved in (
            store.resolve_wikilink(target, registry=link_registry)
            for target in index_targets
            if target
        )
        if resolved is not None
    }
    for page in pages:
        if page.name in skip_orphan_check:
            continue
        rel = str(page.relative_to(store.wiki_path)).replace("\\", "/")
        if rel not in index_resolved_paths:
            report.index_missing.append(rel)

    # 4. Stale sources: raw files changed since last ingest
    for stale_path in store.find_stale_sources():
        report.stale_sources.append(str(stale_path))

    # 5. Missing frontmatter
    for page in pages:
        if page.name in skip_orphan_check:
            continue
        try:
            post = frontmatter.load(str(page))
            missing = [f for f in required_fields if f not in post.metadata]
            if missing:
                rel = str(page.relative_to(store.wiki_path)).replace("\\", "/")
                report.missing_frontmatter.append((rel, missing))
        except Exception:
            rel = str(page.relative_to(store.wiki_path)).replace("\\", "/")
            report.missing_frontmatter.append((rel, required_fields))

    if semantic and llm is not None:
        context = _build_semantic_context(
            store,
            max_pages=max_semantic_pages,
            max_chars=max_context_chars,
        )
        if context.strip():
            result = llm.call(
                system=LINT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": context}],
                tools=[LINT_TOOL],
                tool_choice={"type": "tool", "name": "wiki_lint_report"},
            )
            try:
                parsed = parse_lint_tool_output(result)
            except LLMOutputValidationError as e:
                raise LLMError(f"Invalid lint tool output: {e}") from e

            report.semantic_contradictions = [
                (item.pages, item.description) for item in parsed.contradictions
            ]
            report.semantic_missing_pages = parsed.missing_pages
            report.semantic_suggested_sources = parsed.suggested_sources

    return report


def _build_semantic_context(
    store: WikiStore,
    max_pages: int,
    max_chars: int,
) -> str:
    """Assemble context for one semantic lint LLM call."""
    index_text = store.read_index()
    parts = [f"## Wiki Index\n\n{index_text}"]
    remaining = max_chars - len(parts[0])
    included = 0

    pages = sorted(store.all_pages(), key=lambda p: str(p).lower())
    for page in pages:
        if included >= max_pages:
            break
        if page.name in {"index.md", "log.md"}:
            continue

        rel = str(page.relative_to(store.wiki_path)).replace("\\", "/")
        content = page.read_text(encoding="utf-8", errors="replace")
        chunk = f"## Wiki Page: {rel}\n\n{content}"
        if len(chunk) > remaining:
            break

        parts.append(chunk)
        remaining -= len(chunk)
        included += 1

    return "\n\n---\n\n".join(parts)


def fix(report: LintReport, store: WikiStore) -> int:
    """Auto-fix what can be fixed without the LLM. Returns count of fixes applied."""
    fixes = 0

    # Fix index desync: add missing pages to index.md
    if report.index_missing:
        entries_to_add = []
        for rel_path in report.index_missing:
            stem = Path(rel_path).stem
            entries_to_add.append(f"- [[{stem}]] — (auto-added by lint)")
        store.update_index(entries_to_add=entries_to_add, entries_to_remove=[])
        fixes += len(entries_to_add)

    # Fix broken links: create stub pages for missing targets
    missing_targets = {link for _, link in report.broken_links}
    for target in missing_targets:
        # Guess the category from the context (default to entities/)
        stub_path = f"entities/{target}.md"
        if not store.page_exists(stub_path):
            from datetime import datetime

            today = datetime.now().strftime("%Y-%m-%d")
            stub_content = f"""---
title: {target}
type: entity
tags: []
created: {today}
updated: {today}
sources: []
---

# {target}

*Stub page created by lint --fix. Add content here.*
"""
            store.write_page(stub_path, stub_content)
            store.update_index(
                entries_to_add=[f"- [[{target}]] — (stub, needs content)"],
                entries_to_remove=[],
            )
            fixes += 1

    return fixes
