import io
import stat
import zipfile

from history import clear_history, delete_review, list_reviews, save_review
from project import analyze_project_zip, inspect_project_zip, read_project_context
from quality import calculate_quality_score
from review import _parse_findings
from security import scan_security
from sandbox import run_pytest_sandbox


def test_security_scan_reports_risky_constructs():
    source = "import subprocess\nsubprocess.run('x', shell=True)\neval(user_input)\n"
    findings = scan_security(source)
    codes = {finding["code"] for finding in findings}
    assert {"SEC001", "SEC004"} <= codes


def test_quality_score_keeps_unavailable_checks_unknown():
    result = calculate_quality_score(True, {"status": "unavailable", "findings": []}, None)
    assert result["components"] == {"syntax": 100, "ruff": None, "security": None, "tests": None}
    assert result["score"] == 100


def test_history_can_list_and_delete_records(tmp_path):
    path = tmp_path / "history.sqlite3"
    review_id = save_review(path, {"filename": "x.py", "source": "x = 1", "mode": "security", "status": "valid"})
    assert list_reviews(path)[0]["id"] == review_id
    delete_review(path, review_id)
    assert list_reviews(path) == []
    clear_history(path)


def test_project_rejects_traversal():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escape.py", "print('x')")
    result = inspect_project_zip(stream.getvalue())
    assert result["ok"] is False
    assert "Unsafe archive path" in result["error"]


def test_project_analyzes_python_without_execution(monkeypatch):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("main.py", "if True print('bad')\n")
    monkeypatch.setattr("project.run_ruff", lambda source, filename: {"status": "clean", "findings": []})
    result = analyze_project_zip(stream.getvalue())
    assert result["ok"] is True
    assert result["analyses"][0]["status"] == "needs_fix"


def test_project_context_reads_only_selected_python_files():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("main.py", "def main():\n    return 1\n")
        archive.writestr("other.py", "secret = 2\n")
    result = read_project_context(stream.getvalue(), ["main.py"])
    assert result["ok"] is True
    assert result["selected"] == ["main.py"]
    assert "return 1" in result["context"]
    assert "secret = 2" not in result["context"]


def test_project_rejects_symlink_metadata():
    stream = io.BytesIO()
    info = zipfile.ZipInfo("linked.py")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(info, "target.py")
    result = inspect_project_zip(stream.getvalue())
    assert result["ok"] is False
    assert "Symbolic links" in result["error"]


def test_sandbox_is_unavailable_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("ENABLE_TEST_RUNNER", raising=False)
    result = run_pytest_sandbox(tmp_path, enabled=None)
    assert result["status"] == "unavailable"


def test_findings_parser_handles_non_dict_payload():
    assert _parse_findings('{"findings": ["bad"]}') == []


def test_generate_tests_strips_markdown_fences(monkeypatch):
    from test_generation import generate_tests

    class FakeModel:
        def invoke(self, messages):
            return type("Resp", (), {"content": "```python\ndef test_add():\n    assert 1 + 1 == 2\n```"})()

    monkeypatch.setattr("providers.ChatGroq", lambda *args, **kwargs: FakeModel())
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    result = generate_tests("def add(a, b): return a + b\n", "math.py")
    assert result["status"] == "proposal"
    assert "def test_add():" in result["tests"]
    assert "```" not in result["tests"]
    assert result["filename"] == "test_math.py"


def test_generate_tests_rejects_non_python():
    from test_generation import generate_tests
    result = generate_tests("class Student {}", "student.cpp")
    assert result["status"] == "unsupported"


def test_generate_tests_rejects_syntax_error():
    from test_generation import generate_tests
    result = generate_tests("def broken(\n", "broken.py")
    assert result["status"] == "failed"
    assert "Source must parse" in result["error"]


def test_review_source_tests_mode_delegation(monkeypatch):
    from review import review_source

    class FakeModel:
        def invoke(self, messages):
            return type("Resp", (), {"content": "def test_foo():\n    assert True\n"})()

    monkeypatch.setattr("providers.ChatGroq", lambda *args, **kwargs: FakeModel())
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    result = review_source("x = 1\n", "x.py", mode="tests")
    assert result["status"] == "proposal"
    assert "test_foo" in result["tests"]

