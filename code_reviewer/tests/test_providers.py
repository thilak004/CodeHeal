import os

import pytest

from providers import ClaudeProvider, create_provider


class FakeMessages:
    def __init__(self):
        self.request = None

    def create(self, **request):
        self.request = request
        return type("Response", (), {"content": [type("Block", (), {"text": "fixed"})()]})()


class FakeClient:
    def __init__(self):
        self.messages = FakeMessages()


def test_create_provider_rejects_missing_claude_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        create_provider("claude")


def test_claude_provider_uses_official_messages_api(monkeypatch):
    client = FakeClient()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    provider = create_provider("claude", claude_factory=lambda: client)
    result = provider.invoke([type("Message", (), {"content": "Explain this"})()])
    assert result.content == "fixed"
    assert client.messages.request["model"] == os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    assert client.messages.request["messages"][0]["role"] == "user"


def test_claude_provider_extracts_string_content():
    client = FakeClient()
    provider = ClaudeProvider(client, "claude-opus-5-5")
    result = provider.invoke("hello")
    assert result.content == "fixed"
