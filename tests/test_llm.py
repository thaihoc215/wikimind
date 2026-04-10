"""Tests for LLM client configuration behavior."""

import json

import pytest

from wikimind.llm import LLMClient, LLMError


def test_llmclient_rejects_unsupported_provider_name():
    with pytest.raises(LLMError):
        LLMClient(model="x", api_key="test", provider="unknown")


def test_llmclient_openai_requires_api_key():
    with pytest.raises(LLMError):
        LLMClient(model="gpt-4o-mini", api_key="", provider="openai")


def test_llmclient_ollama_allows_empty_api_key():
    client = LLMClient(model="llama3.1", api_key="", provider="ollama")
    assert client.provider == "ollama"


def test_budget_guard_blocks_call_when_limit_reached(monkeypatch):
    """LLMClient raises LLMError before making a call when budget is exhausted."""
    client = LLMClient(
        model="llama3.1", api_key="", provider="ollama", max_budget_usd=0.01
    )
    # Simulate already having spent $0.01 in prior calls
    client.total_input_tokens = 1_000_000  # cost_usd() uses Anthropic pricing (0.0 for ollama)
    # For ollama, cost_usd() returns 0.0, so we test with anthropic pricing path
    anthropic_client = LLMClient(
        model="claude-sonnet-4-20250514",
        api_key="test",
        provider="anthropic",
        max_budget_usd=0.001,
    )
    # Manually set tokens so cost_usd() > max_budget_usd
    anthropic_client.total_input_tokens = 100_000  # 100K * $3/1M = $0.30 >> $0.001
    with pytest.raises(LLMError, match="Budget limit"):
        anthropic_client.call(
            system="s",
            messages=[{"role": "user", "content": "q"}],
            tools=[{"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}],
        )


def test_budget_guard_disabled_when_zero(monkeypatch):
    """max_budget_usd=0 means no limit — call proceeds (or fails for other reasons)."""
    client = LLMClient(
        model="claude-sonnet-4-20250514",
        api_key="test",
        provider="anthropic",
        max_budget_usd=0.0,
    )
    client.total_input_tokens = 10_000_000  # absurdly high — but budget guard is off
    # The call will fail because we haven't monkeypatched the HTTP client,
    # but it should NOT fail with "Budget limit"
    with pytest.raises(Exception) as exc_info:
        client.call(
            system="s",
            messages=[{"role": "user", "content": "q"}],
            tools=[{"name": "t", "description": "d", "input_schema": {"type": "object", "properties": {}}}],
        )
    assert "Budget limit" not in str(exc_info.value)


class _DummyHTTPResponse:
    def __init__(self, payload: dict):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_openai_adapter_parses_tool_call(monkeypatch):
    response_payload = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "wiki_answer",
                                "arguments": '{"answer":"ok","citations":[],"confidence":"high"}',
                            }
                        }
                    ]
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    def fake_urlopen(req, timeout=120):
        assert req.full_url.endswith("/chat/completions")
        return _DummyHTTPResponse(response_payload)

    monkeypatch.setattr("wikimind.llm.request.urlopen", fake_urlopen)

    client = LLMClient(model="gpt-4o-mini", api_key="test", provider="openai")
    result = client.call(
        system="s",
        messages=[{"role": "user", "content": "q"}],
        tools=[
            {
                "name": "wiki_answer",
                "description": "answer",
                "input_schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                },
            }
        ],
        tool_choice={"type": "tool", "name": "wiki_answer"},
    )

    assert result["answer"] == "ok"
    summary = client.token_summary()
    assert summary["input_tokens"] == 10
    assert summary["output_tokens"] == 5


def test_ollama_adapter_parses_schema_json(monkeypatch):
    response_payload = {
        "message": {
            "role": "assistant",
            "content": '{"answer":"ok","citations":[],"confidence":"high"}',
        },
        "prompt_eval_count": 20,
        "eval_count": 8,
    }

    def fake_urlopen(req, timeout=120):
        assert req.full_url.endswith("/api/chat")
        return _DummyHTTPResponse(response_payload)

    monkeypatch.setattr("wikimind.llm.request.urlopen", fake_urlopen)

    client = LLMClient(model="llama3.1", api_key="", provider="ollama")
    result = client.call(
        system="s",
        messages=[{"role": "user", "content": "q"}],
        tools=[
            {
                "name": "wiki_answer",
                "description": "answer",
                "input_schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                },
            }
        ],
        tool_choice={"type": "tool", "name": "wiki_answer"},
    )

    assert result["answer"] == "ok"
    summary = client.token_summary()
    assert summary["input_tokens"] == 20
    assert summary["output_tokens"] == 8
