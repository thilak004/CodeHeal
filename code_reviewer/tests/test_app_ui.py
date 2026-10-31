"""Streamlit UI regression tests for the language-preserving proposal flow."""
import sys
from pathlib import Path

import pytest

CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

pytest.importorskip("streamlit")

import agent  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(CODE_DIR / "app.py")

CPP_SOURCE = (
    'class Student {\n'
    "public:\n"
    "    ~Student() {\n"
    '        cout << "Destructor called" << endl;\n'
    "    }\n"
    "}\n"
)
CPP_FIXED = (
    'class Student {\n'
    "public:\n"
    "    ~Student() {\n"
    '        cout << "Destructor called" << endl;\n'
    "    }\n"
    "};\n"
)


class Response:
    def __init__(self, content):
        self.content = content


class FakeModel:
    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, messages):
        return Response(CPP_FIXED)


class FakeYamlModel:
    """Answers a YAML request with YAML, never with another language."""

    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, messages):
        return Response("name: demo\n")


class FakeGoModel:
    """Answers a Go request with Go, never with another language."""

    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, messages):
        return Response('package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("hi")\n}\n')


class FakeForeignModel:
    """Answers every request with Python, whatever language was asked for."""

    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, messages):
        return Response("print('hello')\n")


class FakeRealisticCppModel:
    """Answers a C++ request with ordinary C++ source."""

    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, messages):
        return Response(
            "#include <iostream>\n\n"
            "class Vector {\n"
            "public:\n"
            "    void add(int value)\n"
            "    {\n"
            '        std::cout << value << "\\n";\n'
            "    }\n"
            "};\n"
        )


REALISTIC_CPP_SOURCE = (
    "#include <iostream>\n\n"
    "class Vector {\n"
    "public:\n"
    "    void add(int value)\n"
    "    {\n"
    '        std::cout << value << "\\n"\n'
    "    }\n"
    "};\n"
)


def test_realistic_cpp_upload_produces_a_cpp_proposal(monkeypatch):
    """A C++ upload must not end in "No valid fix was produced"."""
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(agent, "ChatGroq", FakeRealisticCppModel)
    monkeypatch.setattr("multilang.shutil.which", lambda name: None)

    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    app.file_uploader[0].upload(
        "fnoverload.cpp",
        REALISTIC_CPP_SOURCE.encode("utf-8"),
        "text/x-cpp",
    ).run()

    app.form_submit_button[0].click().run()
    assert not app.exception

    metrics = [item.value for item in app.metric]
    assert metrics[0] == "fixed"
    assert metrics[2] == "valid"

    code_languages = [getattr(item.proto, "language", None) for item in app.get("code")]
    assert "cpp" in code_languages
    assert "python" not in code_languages

    errors = [item.value for item in app.error]
    assert not any("No valid fix was produced" in value for value in errors)


def test_cpp_upload_keeps_cpp_language_and_filename(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(agent, "ChatGroq", FakeModel)

    app = AppTest.from_file(APP_PATH, default_timeout=30).run()
    app.file_uploader[0].upload("student.cpp", CPP_SOURCE.encode("utf-8"), "text/x-cpp").run()

    assert app.text_input[0].value == "student.cpp"
    assert "Detected language: C++" in [item.value for item in app.caption]

    app.form_submit_button[0].click().run()
    assert not app.exception

    metrics = [item.value for item in app.metric]
    assert metrics[0] == "fixed"
    assert metrics[2] == "valid"

    code_languages = [getattr(item.proto, "language", None) for item in app.get("code")]
    assert code_languages.count("cpp") >= 2
    assert "python" not in code_languages

    for index, button in enumerate(app.button):
        if "Approve and apply fix" in button.label:
            app.button[index].click().run()
            break
    assert not app.exception

    captions = [item.value for item in app.caption]
    assert any("corrected_student.cpp" in value and "C++" in value for value in captions)
    assert [item.label for item in app.download_button] == ["Download corrected code"]
