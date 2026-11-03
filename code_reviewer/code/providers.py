"""Explicit provider boundary for LLM calls."""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Protocol

from langchain_groq import ChatGroq

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised when the optional dependency is absent.
    anthropic = None


class LLMProvider(Protocol):
    def invoke(self, messages: Any) -> Any:
        ...


def _message_text(messages: Any) -> str:
    """Convert LangChain-style prompt messages into one user prompt."""
    if hasattr(messages, "to_messages"):
        messages = messages.to_messages()
    if isinstance(messages, list):
        parts: list[str] = []
        for message in messages:
            content = getattr(message, "content", message)
            if isinstance(content, list):
                content = "\n".join(
                    str(block.get("text", "")) if isinstance(block, dict) else str(getattr(block, "text", block))
                    for block in content
                )
            parts.append(str(content))
        return "\n\n".join(parts)
    return str(messages)


def _response_text(response: Any) -> str:
    """Extract text from either an SDK response or a small test double."""
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
            else:
                text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        return "\n".join(parts).strip()
    return str(content).strip()


class OllamaProvider:
    """Small stdlib-only Ollama adapter; it never silently replaces another provider."""

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def invoke(self, messages: Any) -> Any:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": _message_text(messages)}],
                "stream": False,
                "options": {"temperature": 0},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = ((payload.get("message") or {}).get("content") or "").strip()
        return type("ProviderResponse", (), {"content": content})()


class ClaudeProvider:
    """Official Anthropic Python SDK adapter with a bounded, non-tool request."""

    def __init__(self, client: Any, model: str, max_tokens: int = 8192) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def invoke(self, messages: Any) -> Any:
        request = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": _message_text(messages)}],
        }
        messages_api = self.client.messages
        if hasattr(messages_api, "stream"):
            with messages_api.stream(**request) as stream:
                response = stream.get_final_message()
        else:  # A small compatibility path for test doubles and older SDK wrappers.
            response = messages_api.create(**request)
        return type("ProviderResponse", (), {"content": _response_text(response)})()


def _claude_client(factory: Any | None = None) -> Any:
    if factory is not None:
        return factory()
    if anthropic is None:
        raise RuntimeError("Claude support requires the 'anthropic' package.")
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _max_tokens() -> int:
    try:
        value = int(os.getenv("ANTHROPIC_MAX_TOKENS", "8192"))
    except ValueError:
        value = 8192
    return max(256, min(value, 64000))


def create_provider(
    provider_name: str | None = None,
    groq_factory: Any | None = None,
    claude_factory: Any | None = None,
) -> LLMProvider:
    """Create only the explicitly selected provider; never silently fall back."""
    active_groq_factory = groq_factory or ChatGroq
    name = (provider_name or os.getenv("LLM_PROVIDER", "groq")).strip().lower()
    if name == "groq":
        if not os.getenv("GROQ_API_KEY"):
            raise RuntimeError("Groq API key is not set (GROQ_API_KEY).")
        return active_groq_factory(
            model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
            temperature=0,
        )
    if name == "ollama":
        return OllamaProvider(
            os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
            os.getenv("OLLAMA_MODEL", "llama3.2"),
        )
    if name == "claude":
        if not os.getenv("ANTHROPIC_API_KEY") and claude_factory is None:
            raise RuntimeError("Claude API key is not set (ANTHROPIC_API_KEY).")
        return ClaudeProvider(
            _claude_client(claude_factory),
            os.getenv("ANTHROPIC_MODEL", "claude-opus-4-1"),
            _max_tokens(),
        )
    raise ValueError("Unsupported provider. Choose 'groq', 'ollama', or 'claude'.")
