"""End-to-end tests for the language-preserving fix flow, for every language.

Each uploadable language is exercised twice: once with a model answer in the
same language, which must become a proposal, and once with an answer in another
language, which must be rejected.
"""
import pytest

import agent

# language -> (filename, broken source, same-language answer)
SAME_LANGUAGE_CASES = {
    "python": (
        "demo.py",
        "def greet(name)\n    print(name)\n",
        "def greet(name):\n    print(name)\n",
    ),
    "javascript": (
        "demo.js",
        "function greet(name) {\n  console.log(name)\n",
        "function greet(name) {\n  console.log(name);\n}\n",
    ),
    "java": (
        "Demo.java",
        "public class Greeter {\n  public static void main(String[] args) {\n    System.out.println(\"hi\");\n  }\n",
        "public class Greeter {\n  public static void main(String[] args) {\n    System.out.println(\"hi\");\n  }\n}\n",
    ),
    "csharp": (
        "Demo.cs",
        "class Program\n{\n    static void Main()\n    {\n        Console.WriteLine(\"hi\");\n    }\n",
        "class Program\n{\n    static void Main()\n    {\n        Console.WriteLine(\"hi\");\n    }\n}\n",
    ),
    "c": (
        "demo.c",
        "#include <stdio.h>\n\nint main(void) {\n    printf(\"hi\\n\");\n    return 0;\n",
        "#include <stdio.h>\n\nint main(void) {\n    printf(\"hi\\n\");\n    return 0;\n}\n",
    ),
    "cpp": (
        "demo.cpp",
        "#include <iostream>\n\nint main() {\n    std::cout << \"hi\" << std::endl;\n    return 0;\n",
        "#include <iostream>\n\nint main() {\n    std::cout << \"hi\" << std::endl;\n    return 0;\n}\n",
    ),
}

# The answer the model gives when it ignores the requested language.
FOREIGN_ANSWERS = {
    "python": 'int main() {\n    std::cout << "hello" << std::endl;\n    return 0;\n}\n',
}
DEFAULT_FOREIGN_ANSWER = "print('hello')\n"


def _foreign_answer(language: str) -> str:
    return FOREIGN_ANSWERS.get(language, DEFAULT_FOREIGN_ANSWER)

ALL_LANGUAGES = ["python", "javascript", "java", "csharp", "c", "cpp"]


class Response:
    def __init__(self, content):
        self.content = content


def _fake_provider(answer):
    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages):
            return Response(answer)

    return FakeModel


@pytest.fixture(autouse=True)
def _no_native_toolchain(monkeypatch):
    """Use the built-in fallback validators, so the result does not depend on
    whichever compilers happen to be installed on the machine."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    monkeypatch.setenv("GROQ_API_KEY", "test")


def test_every_uploadable_language_has_a_case():
    assert set(SAME_LANGUAGE_CASES) == set(["python", "javascript", "java", "csharp", "c", "cpp"])


@pytest.mark.parametrize("language", ["python", "javascript", "java", "csharp", "c", "cpp"])
def test_same_language_answer_becomes_a_proposal(monkeypatch, language):
    filename, broken, answer = SAME_LANGUAGE_CASES[language]
    monkeypatch.setattr(agent, "ChatGroq", _fake_provider(answer))

    result = agent.fix_code(broken, filename, provider_name="groq", max_attempts=2)

    assert result["state"] == "fixed", result.get("logs")
    assert result["language"] == language
    assert result["fixed_code"].strip()


@pytest.mark.parametrize("language", ["python", "javascript", "java", "csharp", "c", "cpp"])
def test_foreign_language_answer_is_rejected(monkeypatch, language):
    """A proposal in another language must never be offered to the user."""
    filename, broken, _answer = SAME_LANGUAGE_CASES[language]
    monkeypatch.setattr(agent, "ChatGroq", _fake_provider(_foreign_answer(language)))

    result = agent.fix_code(broken, filename, provider_name="groq", max_attempts=2)

    assert result["state"] != "fixed", result.get("logs")
    assert not (result.get("fixed_code") or "").strip()
    logs = " | ".join(result.get("logs") or [])
    assert "Fix attempt" in logs, logs
