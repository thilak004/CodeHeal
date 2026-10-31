import io
import zipfile

from languages import detect_language, source_extensions
from multilang import check_source, validate_candidate_for_language
from project import analyze_project_zip


def test_language_detection_supports_recommended_extensions():
    assert detect_language("component.tsx") is None
    assert detect_language("main.go") is None
    assert detect_language("query.sql") is None
    assert ".cpp" in source_extensions("cpp")


def test_js_fallback_reports_possible_missing_semicolon(monkeypatch):
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    result = check_source("let value = 1;\nconsole.log(value)", "main.js")
    assert result["status"] == "clean"


def test_cpp_fallback_reports_possible_missing_semicolon(monkeypatch):
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    result = check_source("#include <iostream>\nint main() {\n    int value = 1\n    return 0;\n}\n", "main.cpp")
    assert result["status"] == "findings"
    assert result["tool"] == "built-in fallback"
    assert any(item["code"] == "CPP002" for item in result["findings"])


def test_cpp_fallback_reports_missing_class_semicolon(monkeypatch):
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    source = "class Student {\npublic:\n    ~Student() {\n    }\n}\n"
    result = check_source(source, "student.cpp")
    assert any(item["code"] == "CPP003" for item in result["findings"])


def test_cpp_fallback_accepts_a_multiline_parameter_list(monkeypatch):
    """A parameter list split over lines has no terminator of its own."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    source = "int add(\n    int a,\n    int b\n) {\n    return a + b;\n}\n"
    result = check_source(source, "math.cpp")
    assert result["status"] == "clean"


def test_cpp_fallback_accepts_a_continued_expression(monkeypatch):
    """A statement continued on the next line has one terminator, not two."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    source = "int total = 1 +\n    2;\n"
    result = check_source(source, "sum.cpp")
    assert result["status"] == "clean"


def test_cpp_fallback_accepts_a_forward_declaration(monkeypatch):
    """A forward declaration declares no body, so it never misses a semicolon."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    source = "class Greeter;\n\nint main() {\n    return 0;\n}\n"
    result = check_source(source, "greeter.cpp")
    assert result["status"] == "clean"
    assert not any(item["code"] == "CPP003" for item in result["findings"])


def test_cpp_fallback_ignores_a_brace_inside_a_string(monkeypatch):
    """A brace inside a string literal is text, not an unbalanced delimiter."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    source = 'int main() {\n    std::cout << "{" << std::endl;\n    return 0;\n}\n'
    result = check_source(source, "braces.cpp")
    assert result["status"] == "clean"


def test_cpp_fallback_ignores_a_brace_inside_a_comment(monkeypatch):
    """A brace inside a comment is text, not an unbalanced delimiter."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    source = "// opens a brace { in prose\nint main() {\n    return 0;\n}\n"
    result = check_source(source, "comment.cpp")
    assert result["status"] == "clean"


def test_cpp_candidate_with_a_warning_is_still_offered(monkeypatch):
    """A heuristic warning must not block a proposal for the same language."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    candidate = "#include <iostream>\nint main() {\n    int value = 1\n    return 0;\n}\n"
    valid, message, warnings = validate_candidate_for_language(candidate, candidate, "main.cpp")
    assert valid is True
    assert message != "Valid source"
    assert any("semicolon" in warning for warning in warnings)


def test_cpp_candidate_with_a_broken_delimiter_is_rejected(monkeypatch):
    """A proven error still blocks the proposal, so the loop retries."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    valid, message, _warnings = validate_candidate_for_language("class Student {\n", "class Student {}\n", "student.cpp")
    assert valid is False
    assert "Unclosed delimiter" in message


def test_java_fallback_does_not_require_cpp_class_semicolon(monkeypatch):
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    source = "public class Student {\n    void greet() {}\n}\n"
    result = check_source(source, "Student.java")
    assert not any(item["code"] == "JAVA003" for item in result["findings"])


def test_csharp_fallback_does_not_flag_a_method_signature(monkeypatch):
    """A method signature is closed by a brace, so it never misses a semicolon."""
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    source = (
        "class Program\n"
        "{\n"
        "    static void Main(string[] args)\n"
        "    {\n"
        '        Console.WriteLine("hi");\n'
        "    }\n"
        "}\n"
    )
    result = check_source(source, "Program.cs")
    assert result["status"] == "clean"


def test_project_analysis_includes_non_python_files(monkeypatch):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("app.js", "const value = 1;\n")
        archive.writestr("data.js", "{invalid js source;\n")
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)
    result = analyze_project_zip(stream.getvalue())
    assert result["ok"] is True
    assert {item["name"] for item in result["analyses"]} == {"app.js", "data.js"}
