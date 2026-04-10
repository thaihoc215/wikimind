"""Ingest operation: source → wiki pages."""

from __future__ import annotations

from pathlib import Path

from wikimind.llm_schema import (
    LLMOutputValidationError,
    IngestToolOutput,
    parse_ingest_tool_output,
)
from wikimind.llm import LLMClient, LLMError
from wikimind.prompts.ingest import INGEST_SYSTEM_PROMPT, INGEST_TOOL
from wikimind.retrieval import KeywordIndexRetriever, Retriever
from wikimind.wiki import WikiStore

# Sources larger than this get chunked before ingesting
MAX_SOURCE_CHARS = 50_000


class IngestResult:
    def __init__(self, pages_created: int, pages_updated: int, summary: str):
        self.pages_created = pages_created
        self.pages_updated = pages_updated
        self.summary = summary

    def __repr__(self) -> str:
        return (
            f"IngestResult(created={self.pages_created}, "
            f"updated={self.pages_updated}, summary={self.summary!r})"
        )


def ingest(
    source_path: Path,
    store: WikiStore,
    llm: LLMClient,
    retriever: Retriever | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> IngestResult:
    """Ingest a single source file into the wiki."""
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # Dedup check
    if not force and store.is_already_ingested(source_path):
        return IngestResult(
            pages_created=0,
            pages_updated=0,
            summary=f"Skipped (already ingested, unchanged): {source_path.name}",
        )

    retriever = retriever or KeywordIndexRetriever(store)

    # Read source
    source_content = _read_source(source_path)

    # Chunk if too large
    if len(source_content) > MAX_SOURCE_CHARS:
        source_content = _summarize_large_source(source_content, source_path.name, llm)

    # Find relevant existing wiki pages
    relevant_pages = retriever.retrieve(source_content, top_k=5)

    # Build LLM context
    context = store.build_ingest_context(source_content, relevant_pages)

    # Single LLM call
    raw_result = llm.call(
        system=INGEST_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context}],
        tools=[INGEST_TOOL],
        tool_choice={"type": "tool", "name": "wiki_update"},
    )
    try:
        result = parse_ingest_tool_output(raw_result)
    except LLMOutputValidationError as e:
        raise LLMError(f"Invalid ingest tool output: {e}") from e

    if dry_run:
        return _dry_run_result(result)

    # Execute file operations
    pages_created = 0
    pages_updated = 0
    for file_op in result.files_to_write:
        store.write_page(file_op.path, file_op.content)
        action = file_op.action
        if action == "create":
            pages_created += 1
        else:
            pages_updated += 1

    # Update index
    store.update_index(
        entries_to_add=result.index_entries_to_add,
        entries_to_remove=result.index_entries_to_remove,
    )

    # Append to log
    log_entry = result.log_entry
    if log_entry:
        store.append_log(log_entry)

    # Mark as ingested
    store.mark_ingested(source_path)

    return IngestResult(
        pages_created=pages_created,
        pages_updated=pages_updated,
        summary=result.summary,
    )


def _read_source(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _read_pdf(path)
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_bytes().decode("latin-1")


def _read_pdf(path: Path) -> str:
    try:
        import pymupdf4llm  # type: ignore[import]
    except ImportError as exc:
        raise LLMError(
            f"PDF support requires the 'pdf' extra: pip install wikimind[pdf]\n"
            f"  (pymupdf4llm not found: {exc})"
        ) from exc
    try:
        md = pymupdf4llm.to_markdown(str(path))
    except Exception as exc:
        raise LLMError(f"Failed to extract text from PDF '{path.name}': {exc}") from exc
    if not md or not md.strip():
        raise LLMError(f"PDF '{path.name}' produced no extractable text.")
    return md


def _summarize_large_source(content: str, name: str, llm: LLMClient) -> str:
    """Chunk a large source and summarize each chunk, then combine."""
    chunk_size = 10_000
    chunks = [content[i : i + chunk_size] for i in range(0, len(content), chunk_size)]

    summarize_tool = {
        "name": "chunk_summary",
        "description": "Summarize a chunk of text.",
        "input_schema": {
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Key points from this chunk (bullet list)",
                }
            },
        },
    }

    summaries = []
    for i, chunk in enumerate(chunks, 1):
        try:
            result = llm.call(
                system="Summarize the key information from this text chunk. Be concise.",
                messages=[
                    {
                        "role": "user",
                        "content": f"Chunk {i}/{len(chunks)} of '{name}':\n\n{chunk}",
                    }
                ],
                tools=[summarize_tool],
                tool_choice={"type": "tool", "name": "chunk_summary"},
            )
            summaries.append(result.get("summary", ""))
        except LLMError:
            summaries.append(f"[Chunk {i} summarization failed]")

    combined = "\n\n".join(f"### Chunk {i + 1}\n{s}" for i, s in enumerate(summaries))
    return f"# Combined Summary of: {name}\n\n{combined}"


def _dry_run_result(result: IngestToolOutput) -> IngestResult:
    files = result.files_to_write
    created = sum(1 for f in files if f.action == "create")
    updated = sum(1 for f in files if f.action == "update")
    return IngestResult(
        pages_created=created,
        pages_updated=updated,
        summary=f"[DRY RUN] {result.summary}",
    )
