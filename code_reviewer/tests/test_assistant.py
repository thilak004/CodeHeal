from assistant import ask_assistant


class Response:
    def __init__(self, content):
        self.content = content


class Provider:
    def __init__(self, content):
        self.content = content
        self.messages = []

    def invoke(self, messages):
        self.messages.append(messages)
        return Response(self.content)


def test_assistant_returns_text_answer(monkeypatch):
    provider = Provider("The function returns the greeting.")
    monkeypatch.setattr("assistant.create_provider", lambda name: provider)
    result = ask_assistant("def greet():\n    return 'hi'\n", "What does this do?", action="question")
    assert result["status"] == "answer"
    assert result["answer"].startswith("The function")


def test_assistant_requires_approval_for_validated_proposal(monkeypatch):
    provider = Provider("x = 2\n")
    monkeypatch.setattr("assistant.create_provider", lambda name: provider)
    result = ask_assistant("x = 1\n", "Change the value", action="refactor")
    assert result["status"] == "proposal"
    assert result["proposal"].rstrip("\r\n") == "x = 2"


def test_assistant_rejects_invalid_proposal(monkeypatch):
    provider = Provider("Here is the answer: not code")
    monkeypatch.setattr("assistant.create_provider", lambda name: provider)
    result = ask_assistant("x = 1\n", "Refactor it", action="refactor")
    assert result["status"] == "failed"
    assert "prose" in result["error"]


def test_assistant_proposes_code_for_a_non_python_upload(monkeypatch):
    """The assistant must speak the uploaded language, not only Python."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    provider = Provider("int main() {\n    return 0;\n}\n")
    monkeypatch.setattr("assistant.create_provider", lambda name: provider)
    result = ask_assistant(
        "int main() {\n    return 0;\n}\n",
        "Rename the function",
        filename="demo.cpp",
        action="refactor",
    )
    assert result["status"] == "proposal"
    assert result["proposal"].rstrip("\r\n") == "int main() {\n    return 0;\n}"


def test_assistant_rejects_a_foreign_language_proposal(monkeypatch):
    """A proposal in another language must be rejected for every language."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    provider = Provider("def greet(name):\n    print(name)\n")
    monkeypatch.setattr("assistant.create_provider", lambda name: provider)
    result = ask_assistant(
        "int main() {\n    return 0;\n}\n",
        "Refactor it",
        filename="demo.cpp",
        action="refactor",
    )
    assert result["status"] == "failed"
    assert "Python-like" in result["error"]
