import json

import agent


class Response:
    def __init__(self, content):
        self.content = content


def test_explanation_parser_accepts_expected_json():
    fallback = {"summary": "fallback"}
    payload = {
        "summary": "Fixed",
        "root_cause": "Missing colon",
        "changes": "Added colon",
        "remaining_concerns": "Review behavior",
    }
    result = agent._parse_explanation(json.dumps(payload), fallback)
    assert result == payload


def test_explanation_parser_uses_fallback_for_invalid_json():
    fallback = {"summary": "fallback"}
    assert agent._parse_explanation("not json", fallback) == fallback


def test_fix_code_valid_source_runs_static_analysis(monkeypatch):
    monkeypatch.setattr(agent, "run_ruff", lambda code, filename: {"status": "clean", "findings": [], "message": "clean"})
    result = agent.fix_code("x = 1\n", "example.py")
    assert result["success"] is True
    assert result["original_was_valid"] is True
    assert result["fixed_code"] == "x = 1\n"
    assert result["approved"] is False
    assert result["original_ruff"]["status"] == "clean"


def test_fix_code_requires_key_for_invalid_source(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(agent, "run_ruff", lambda code, filename: {"status": "clean", "findings": [], "message": "clean"})
    result = agent.fix_code("if True print('x')\n")
    assert result["success"] is False
    assert "API key" in result["error"]


def test_fix_code_supports_cpp_proposals(monkeypatch):
    monkeypatch.setattr(agent, "ChatGroq", lambda *args, **kwargs: type("Model", (), {
        "invoke": lambda self, messages: Response("class Student {\npublic:\n    ~Student() {}\n};\n")
    })())
    monkeypatch.setenv("GROQ_API_KEY", "test")
    source = "class Student {\npublic:\n    ~Student() {}\n}\n"
    result = agent.fix_code(source, "student.cpp")
    assert result["success"] is True
    assert result["state"] == "fixed"
    assert result["language"] == "cpp"
    assert result["filename"] == "student.cpp"
    assert result["candidate_valid"] is True
    assert result["fixed_code"].rstrip("\r\n").endswith("};")
    assert result["original_ruff"]["status"] == "not_run"
    assert result["approved"] is False


def test_fix_code_accepts_a_realistic_cpp_proposal(monkeypatch):
    """A C++ upload must produce a C++ proposal, not a rejected candidate."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    monkeypatch.setattr(agent, "ChatGroq", lambda *args, **kwargs: type("Model", (), {
        "invoke": lambda self, messages: Response(
            "#include <iostream>\n\n"
            "class Vector {\n"
            "public:\n"
            "    void add(int value)\n"
            "    {\n"
            '        std::cout << value << "\\n";\n'
            "    }\n"
            "};\n"
        )
    })())
    monkeypatch.setenv("GROQ_API_KEY", "test")
    source = (
        "#include <iostream>\n\n"
        "class Vector {\n"
        "public:\n"
        "    void add(int value)\n"
        "    {\n"
        '        std::cout << value << "\\n"\n'
        "    }\n"
        "};\n"
    )
    result = agent.fix_code(source, "fnoverload.cpp")
    assert result["success"] is True
    assert result["state"] == "fixed"
    assert result["candidate_valid"] is True
    assert result["attempt_count"] == 1
    assert result["language"] == "cpp"
    assert result["fixed_code"].startswith("#include <iostream>")


def test_failed_proposal_does_not_claim_a_valid_proposal(monkeypatch):
    """The explanation must not report a valid proposal when none was made."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    monkeypatch.setattr(agent, "ChatGroq", lambda *args, **kwargs: type("Model", (), {
        "invoke": lambda self, messages: Response("class Student {\n")
    })())
    monkeypatch.setenv("GROQ_API_KEY", "test")
    source = "class Student {\npublic:\n    ~Student() {}\n}\n"
    result = agent.fix_code(source, "student.cpp")
    assert result["state"] == "failed"
    assert result["explanation"]["summary"] != "A syntax-valid C++ fix proposal was generated."
    assert "No C++ fix proposal was produced." == result["explanation"]["summary"]


def test_fix_code_rejects_python_shaped_cpp_output_and_retries(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")

    class Model:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return Response("def greet(name):\n    print(name)\n")
            return Response("class Student {\npublic:\n    ~Student() {}\n};\n")

    monkeypatch.setattr(agent, "ChatGroq", Model)
    source = "class Student {\npublic:\n    ~Student() {}\n}\n"
    result = agent.fix_code(source, "student.cpp")
    assert result["success"] is True
    assert result["filename"] == "student.cpp"
    assert result["attempt_count"] == 2
    assert any("Python-like" in log for log in result["logs"])
    assert result["fixed_code"].startswith("class Student")


def test_fix_code_rejects_invalid_non_python_candidate_and_retries(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")

    class Model:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return Response("class Student {\n")
            return Response("class Student {\npublic:\n    ~Student() {}\n};\n")

    monkeypatch.setattr(agent, "ChatGroq", Model)
    source = "class Student {\npublic:\n    ~Student() {}\n}\n"
    result = agent.fix_code(source, "student.cpp")
    assert result["success"] is True
    assert result["attempt_count"] == 2
    assert any("rejected" in log for log in result["logs"])


def test_fix_code_validates_candidate_and_explains_it(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(agent, "run_ruff", lambda code, filename: {"status": "clean", "findings": [], "message": "clean"})

    class Model:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return Response("if True:\n    print('x')")
            return Response(json.dumps({
                "summary": "Fixed syntax",
                "root_cause": "Missing colon",
                "changes": "Added colon",
                "remaining_concerns": "Review behavior",
            }))

    monkeypatch.setattr(agent, "ChatGroq", Model)
    result = agent.fix_code("if True print('x')\n", include_explanation=True)
    assert result["success"] is True
    assert result["fixed_code"].rstrip("\r\n") == "if True:\n    print('x')"
    assert result["explanation"]["summary"] == "Fixed syntax"
    assert result["approved"] is False


def test_fix_code_rejects_foreign_language_output_for_python_upload(monkeypatch):
    """A Python upload must not be answered with source from another language."""
    monkeypatch.setenv("GROQ_API_KEY", "test")

    class Model:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return Response("class Student {\npublic:\n    ~Student() {}\n};\n")
            return Response("if True:\n    print('x')\n")

    monkeypatch.setattr(agent, "ChatGroq", Model)
    result = agent.fix_code("if True print('x')\n", "code.py")
    assert result["success"] is True
    assert result["attempt_count"] == 2
    assert any("C++-like" in log for log in result["logs"])
    assert result["fixed_code"].rstrip("\r\n") == "if True:\n    print('x')"

