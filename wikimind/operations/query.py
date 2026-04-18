"""Query operation: question → answer with citations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from slugify import slugify

from wikimind.llm import LLMClient, LLMError
from wikimind.llm_schema import LLMOutputValidationError, parse_query_tool_output
from wikimind.prompts.query import QUERY_SYSTEM_PROMPT, QUERY_TOOL
from wikimind.retrieval import KeywordIndexRetriever, Retriever
from wikimind.wiki import WikiStore


class QueryResult:
    def __init__(
        self,
        answer: str,
        citations: list[str],
        confidence: str,
        knowledge_gaps: list[str],
        saved_path: str | None = None,
    ):
        self.answer = answer
        self.citations = citations
        self.confidence = confidence
        self.knowledge_gaps = knowledge_gaps
        self.saved_path = saved_path


def query(
    question: str,
    store: WikiStore,
    llm: LLMClient,
    retriever: Retriever | None = None,
    save: bool = False,
    top_k: int = 10,
) -> QueryResult:
    """Answer a question using the wiki."""
    retriever = retriever or KeywordIndexRetriever(store)

    # Cold-start check
    if store.get_page_count() == 0:
        try:
            raw_display = str(store.raw_path.relative_to(Path.cwd())).replace("\\", "/")
        except ValueError:
            raw_display = str(store.raw_path).replace("\\", "/")
        raw_display = raw_display.rstrip("/")

        return QueryResult(
            answer=(
                "The wiki is empty. Ingest some sources first:\n\n"
                f"```\nwikimind ingest {raw_display}/your-file.md\n```"
            ),
            citations=[],
            confidence="low",
            knowledge_gaps=["No sources have been ingested yet."],
        )

    # Find relevant pages
    relevant_pages = retriever.retrieve(question, top_k=top_k)

    if not relevant_pages:
        return QueryResult(
            answer=(
                "No relevant wiki pages found for this question. "
                "Try ingesting more sources or rephrasing your question."
            ),
            citations=[],
            confidence="low",
            knowledge_gaps=["Wiki has no pages matching this question's keywords."],
        )

    # Build context
    context = store.build_query_context(question, relevant_pages)

    # Single LLM call
    raw_result = llm.call(
        system=QUERY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        tools=[QUERY_TOOL],
        tool_choice={"type": "tool", "name": "wiki_answer"},
    )
    try:
        result = parse_query_tool_output(raw_result)
    except LLMOutputValidationError as e:
        raise LLMError(f"Invalid query tool output: {e}") from e

    answer = result.answer
    citations = result.citations
    confidence = result.confidence
    knowledge_gaps = result.knowledge_gaps

    saved_path = None
    if save and answer:
        saved_path = _save_answer(question, answer, citations, knowledge_gaps, store)

    return QueryResult(
        answer=answer,
        citations=citations,
        confidence=confidence,
        knowledge_gaps=knowledge_gaps,
        saved_path=saved_path,
    )


def _save_answer(
    question: str,
    answer: str,
    citations: list[str],
    knowledge_gaps: list[str],
    store: WikiStore,
) -> str:
    """Save the answer as a wiki page in analyses/ and update index + log."""
    today = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(question)[:60]
    page_path = f"analyses/{slug}.md"

    citations_section = ""
    if citations:
        citations_section = "\n## Sources\n\n" + "\n".join(
            f"- [[{Path(c).stem}]]" for c in citations
        )

    gaps_section = ""
    if knowledge_gaps:
        gaps_section = "\n## Knowledge Gaps\n\n" + "\n".join(
            f"- {g}" for g in knowledge_gaps
        )

    content = f"""---
title: "{question}"
type: analysis
tags: [query, analysis]
created: {today}
updated: {today}
sources: []
---

# {question}

{answer}
{citations_section}
{gaps_section}
"""

    store.write_page(page_path, content)
    store.update_index(
        entries_to_add=[f"- [[{slug}]] — {question[:80]}"],
        entries_to_remove=[],
    )
    store.append_log(f"- [{today}] query | {question[:60]} → {Path(page_path).name}")

    return page_path
