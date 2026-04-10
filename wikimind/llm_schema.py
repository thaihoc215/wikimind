"""Typed validation for LLM tool outputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


class LLMOutputValidationError(ValueError):
    """Raised when a tool output does not match expected schema."""


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LLMOutputValidationError(f"{field} must be an object.")
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise LLMOutputValidationError(f"{field} must be a list.")
    return value


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise LLMOutputValidationError(f"{field} must be a string.")
    text = value.strip()
    if not text:
        raise LLMOutputValidationError(f"{field} must be non-empty.")
    return text


def _optional_str(value: Any, field: str, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise LLMOutputValidationError(f"{field} must be a string when provided.")
    return value


def _optional_list_str(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    raw = _require_list(value, field)
    out: list[str] = []
    for idx, item in enumerate(raw):
        out.append(_require_str(item, f"{field}[{idx}]"))
    return out


def _validate_relative_wiki_path(path: str, field: str) -> str:
    normalized = path.replace("\\", "/").strip()
    if not normalized:
        raise LLMOutputValidationError(f"{field} must be non-empty.")

    pure = PurePosixPath(normalized)
    if pure.is_absolute():
        raise LLMOutputValidationError(f"{field} must be relative to wiki/.")
    if ".." in pure.parts:
        raise LLMOutputValidationError(f"{field} cannot contain '..'.")

    return normalized


@dataclass(frozen=True)
class IngestFileWrite:
    path: str
    content: str
    action: str


@dataclass(frozen=True)
class IngestToolOutput:
    files_to_write: list[IngestFileWrite]
    index_entries_to_add: list[str]
    index_entries_to_remove: list[str]
    log_entry: str
    summary: str


def parse_ingest_tool_output(data: Any) -> IngestToolOutput:
    payload = _require_dict(data, "ingest output")

    raw_files = _require_list(payload.get("files_to_write"), "files_to_write")
    files_to_write: list[IngestFileWrite] = []
    for idx, raw_item in enumerate(raw_files):
        item = _require_dict(raw_item, f"files_to_write[{idx}]")
        path = _validate_relative_wiki_path(
            _require_str(item.get("path"), f"files_to_write[{idx}].path"),
            f"files_to_write[{idx}].path",
        )
        content = _require_str(item.get("content"), f"files_to_write[{idx}].content")
        action = _require_str(item.get("action"), f"files_to_write[{idx}].action")
        if action not in {"create", "update"}:
            raise LLMOutputValidationError(
                f"files_to_write[{idx}].action must be 'create' or 'update'."
            )
        files_to_write.append(
            IngestFileWrite(path=path, content=content, action=action)
        )

    index_entries_to_add = _optional_list_str(
        payload.get("index_entries_to_add"), "index_entries_to_add"
    )
    index_entries_to_remove = _optional_list_str(
        payload.get("index_entries_to_remove"), "index_entries_to_remove"
    )
    log_entry = _require_str(payload.get("log_entry"), "log_entry")
    summary = _require_str(payload.get("summary"), "summary")

    return IngestToolOutput(
        files_to_write=files_to_write,
        index_entries_to_add=index_entries_to_add,
        index_entries_to_remove=index_entries_to_remove,
        log_entry=log_entry,
        summary=summary,
    )


@dataclass(frozen=True)
class QueryToolOutput:
    answer: str
    citations: list[str]
    confidence: str
    knowledge_gaps: list[str]


def parse_query_tool_output(data: Any) -> QueryToolOutput:
    payload = _require_dict(data, "query output")

    answer = _require_str(payload.get("answer"), "answer")
    citations = [
        _require_str(item, f"citations[{idx}]")
        for idx, item in enumerate(_require_list(payload.get("citations"), "citations"))
    ]
    confidence = _require_str(payload.get("confidence"), "confidence").lower()
    if confidence not in {"high", "medium", "low"}:
        raise LLMOutputValidationError("confidence must be high, medium, or low.")
    knowledge_gaps = _optional_list_str(payload.get("knowledge_gaps"), "knowledge_gaps")

    return QueryToolOutput(
        answer=answer,
        citations=citations,
        confidence=confidence,
        knowledge_gaps=knowledge_gaps,
    )


@dataclass(frozen=True)
class LintContradiction:
    pages: list[str]
    description: str


@dataclass(frozen=True)
class LintToolOutput:
    contradictions: list[LintContradiction]
    missing_pages: list[str]
    suggested_sources: list[str]


def parse_lint_tool_output(data: Any) -> LintToolOutput:
    payload = _require_dict(data, "lint output")

    raw_contradictions = _list_strict_objects(
        payload.get("contradictions"), "contradictions"
    )
    contradictions: list[LintContradiction] = []
    for idx, item in enumerate(raw_contradictions):
        pages = _optional_list_str(item.get("pages"), f"contradictions[{idx}].pages")
        description = _require_str(
            item.get("description"), f"contradictions[{idx}].description"
        )
        contradictions.append(LintContradiction(pages=pages, description=description))

    missing_pages = [
        _require_str(item, f"missing_pages[{idx}]")
        for idx, item in enumerate(
            _require_list(payload.get("missing_pages"), "missing_pages")
        )
    ]
    suggested_sources = [
        _require_str(item, f"suggested_sources[{idx}]")
        for idx, item in enumerate(
            _require_list(payload.get("suggested_sources"), "suggested_sources")
        )
    ]

    return LintToolOutput(
        contradictions=contradictions,
        missing_pages=missing_pages,
        suggested_sources=suggested_sources,
    )


def _list_strict_objects(value: Any, field: str) -> list[dict[str, Any]]:
    raw = _require_list(value, field)
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw):
        out.append(_require_dict(item, f"{field}[{idx}]"))
    return out
