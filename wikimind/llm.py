"""LLM client with provider adapters and structured tool output."""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
from json import JSONDecodeError
from typing import Any
from urllib import error, request

import anthropic


class LLMError(Exception):
    pass


class ProviderAdapter(ABC):
    """Provider-specific adapter interface for tool-call style interactions."""

    @abstractmethod
    def call_tool(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict,
    ) -> tuple[dict, int, int]:
        """Return (tool_input_json, input_tokens, output_tokens)."""


class AnthropicAdapter(ProviderAdapter):
    """Anthropic provider adapter."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def call_tool(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict,
    ) -> tuple[dict, int, int]:
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )

        for block in response.content:
            if block.type == "tool_use":
                payload = block.input
                if not isinstance(payload, dict):
                    raise LLMError("Provider returned non-object tool payload.")
                return (
                    payload,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )

        raise LLMError("LLM did not return structured output via tool_use.")


class OpenAIAdapter(ProviderAdapter):
    """OpenAI Chat Completions adapter using function/tool calling."""

    def __init__(self, api_key: str, base_url: str = ""):
        if not api_key:
            raise LLMError(
                "OpenAI provider requires an API key. Set OPENAI_API_KEY and configure api_key_env."
            )
        self.api_key = api_key
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")

    def call_tool(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict,
    ) -> tuple[dict, int, int]:
        endpoint = f"{self.base_url}/chat/completions"

        openai_tools = [_to_openai_tool(t) for t in tools]
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}]
            + _normalize_messages(messages),
            "tools": openai_tools,
            "tool_choice": _to_openai_tool_choice(tool_choice),
            "max_tokens": max_tokens,
        }

        data = _http_post_json(
            endpoint,
            payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)

        payload_obj = _extract_openai_payload(data)
        return payload_obj, input_tokens, output_tokens


class OllamaAdapter(ProviderAdapter):
    """Ollama adapter using /api/chat with schema-constrained JSON output."""

    def __init__(self, base_url: str = ""):
        self.base_url = (base_url or "http://localhost:11434").rstrip("/")

    def call_tool(
        self,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict,
    ) -> tuple[dict, int, int]:
        endpoint = f"{self.base_url}/api/chat"
        selected_tool = _select_tool(tools, tool_choice)
        schema = selected_tool.get("input_schema")
        if not isinstance(schema, dict):
            raise LLMError("Selected tool is missing a valid input_schema.")

        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}]
            + _normalize_messages(messages),
            "stream": False,
            "format": schema,
            "options": {"num_predict": max_tokens},
        }

        data = _http_post_json(
            endpoint,
            payload,
            headers={"Content-Type": "application/json"},
        )

        if not isinstance(data, dict):
            raise LLMError("Ollama returned an invalid response payload.")

        message = data.get("message", {})
        if not isinstance(message, dict):
            raise LLMError("Ollama response missing 'message' object.")

        content = message.get("content", "")
        content_text = _coerce_content_to_text(content)
        payload_obj = _parse_json_object(content_text)

        input_tokens = int(data.get("prompt_eval_count", 0) or 0)
        output_tokens = int(data.get("eval_count", 0) or 0)
        return payload_obj, input_tokens, output_tokens


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_sec: int = 120,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = ""
        raise LLMError(
            f"Provider HTTP error {exc.code} calling {url}: {detail or exc.reason}"
        ) from exc
    except error.URLError as exc:
        raise LLMError(
            f"Provider connection error calling {url}: {exc.reason}"
        ) from exc

    try:
        data = json.loads(raw)
    except JSONDecodeError as exc:
        raise LLMError(
            f"Provider returned invalid JSON from {url}: {raw[:200]}"
        ) from exc

    if not isinstance(data, dict):
        raise LLMError("Provider returned a non-object JSON payload.")
    return data


def _normalize_messages(messages: list[dict]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise LLMError(f"messages[{i}] must be an object.")

        role_raw = msg.get("role", "user")
        role = str(role_raw).strip() or "user"
        content = _coerce_content_to_text(msg.get("content", ""))
        normalized.append({"role": role, "content": content})
    return normalized


def _coerce_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return str(content)


def _to_openai_tool(tool: dict) -> dict[str, Any]:
    schema = tool.get("input_schema")
    if not isinstance(schema, dict):
        raise LLMError("Tool is missing input_schema object for OpenAI provider.")

    name = tool.get("name")
    if not isinstance(name, str) or not name.strip():
        raise LLMError("Tool is missing a valid name for OpenAI provider.")

    description = tool.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


def _to_openai_tool_choice(tool_choice: dict) -> Any:
    choice_type = str(tool_choice.get("type", "any")).strip().lower()

    if choice_type == "tool":
        name = tool_choice.get("name")
        if not isinstance(name, str) or not name.strip():
            raise LLMError("OpenAI tool choice of type 'tool' requires a tool name.")
        return {
            "type": "function",
            "function": {
                "name": name,
            },
        }

    if choice_type == "auto":
        return "auto"

    # Anthropic 'any' maps to OpenAI 'required'.
    return "required"


def _extract_openai_payload(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("OpenAI response missing choices.")

    first = choices[0]
    if not isinstance(first, dict):
        raise LLMError("OpenAI response choice payload is invalid.")

    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMError("OpenAI response missing message object.")

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        call0 = tool_calls[0]
        if not isinstance(call0, dict):
            raise LLMError("OpenAI tool call payload is invalid.")
        function = call0.get("function")
        if not isinstance(function, dict):
            raise LLMError("OpenAI tool call missing function payload.")
        args = function.get("arguments", "")
        args_text = _coerce_content_to_text(args).strip()
        if not args_text:
            raise LLMError("OpenAI tool call returned empty arguments.")
        return _parse_json_object(args_text)

    content = _coerce_content_to_text(message.get("content", "")).strip()
    if content:
        return _parse_json_object(content)

    raise LLMError("OpenAI did not return tool_calls or parseable JSON content.")


def _select_tool(tools: list[dict], tool_choice: dict) -> dict:
    if not tools:
        raise LLMError("No tools provided.")

    choice_type = str(tool_choice.get("type", "any")).strip().lower()
    if choice_type == "tool":
        name = tool_choice.get("name")
        if not isinstance(name, str) or not name.strip():
            raise LLMError("Tool choice of type 'tool' requires a tool name.")
        for tool in tools:
            if tool.get("name") == name:
                return tool
        raise LLMError(f"Requested tool not found: {name}")

    return tools[0]


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        parsed = json.loads(cleaned)
    except JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
            except JSONDecodeError as exc:
                raise LLMError(
                    f"Provider returned non-JSON tool payload: {cleaned[:200]}"
                ) from exc
        else:
            raise LLMError(f"Provider returned non-JSON tool payload: {cleaned[:200]}")

    if not isinstance(parsed, dict):
        raise LLMError("Provider tool payload must be a JSON object.")
    return parsed


def _make_adapter(provider: str, api_key: str, base_url: str = "") -> ProviderAdapter:
    normalized = provider.strip().lower()
    if normalized == "anthropic":
        if not api_key:
            raise LLMError(
                "Anthropic provider requires an API key. Set ANTHROPIC_API_KEY and configure api_key_env."
            )
        return AnthropicAdapter(api_key=api_key)
    if normalized == "openai":
        return OpenAIAdapter(api_key=api_key, base_url=base_url)
    if normalized == "ollama":
        return OllamaAdapter(base_url=base_url)

    raise LLMError(
        f"Unsupported provider: {provider!r}. Currently supported: anthropic, openai, ollama"
    )


class LLMClient:
    """Thin wrapper around provider adapters.

    Every call uses tool_use to get structured JSON output — more reliable
    than asking the LLM to output raw JSON in its response text.
    """

    def __init__(
        self,
        model: str,
        api_key: str = "",
        max_tokens: int = 8192,
        provider: str = "anthropic",
        base_url: str = "",
        max_budget_usd: float = 0.0,
    ):
        self.provider = provider
        self.adapter = _make_adapter(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
        )
        self.model = model
        self.max_tokens = max_tokens
        self.max_budget_usd = max_budget_usd
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def call(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict | None = None,
    ) -> dict:
        """Single LLM call. Returns the tool_use input (parsed JSON)."""
        if self.max_budget_usd > 0:
            spent = self.cost_usd()
            if spent >= self.max_budget_usd:
                raise LLMError(
                    f"Budget limit of ${self.max_budget_usd:.4f} reached "
                    f"(spent ${spent:.4f} this session). "
                    f"Run 'wikimind cost' to review usage, or raise max_budget_usd in wikimind.toml."
                )

        payload, input_tokens, output_tokens = self.adapter.call_tool(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice or {"type": "any"},
        )
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        return payload

    def cost_usd(self) -> float:
        """Approximate cost (currently only modeled for Anthropic pricing)."""
        if self.provider.strip().lower() == "anthropic":
            return (
                self.total_input_tokens * 3.0 + self.total_output_tokens * 15.0
            ) / 1_000_000
        return 0.0

    def token_summary(self) -> dict:
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "cost_usd": round(self.cost_usd(), 6),
        }
