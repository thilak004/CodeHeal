import subprocess

from tools import build_unified_diff, check_syntax, detect_indent, match_code_formatting, run_ruff


def test_check_syntax_reports_valid_and_invalid_code():
    assert check_syntax("x = 1")[0] is True
    valid, error = check_syntax("if True print('x')")
    assert valid is False
    assert "SyntaxError" in error


def test_build_unified_diff_contains_file_names_and_change():
    diff = build_unified_diff("x = 1\n", "x = 2\n", "input.py", "fixed_input.py")
    assert "--- input.py" in diff
    assert "+++ fixed_input.py" in diff
    assert "-x = 1" in diff
    assert "+x = 2" in diff


def test_build_unified_diff_ignores_a_trailing_newline_only_change():
    """A trailing newline is a convention, so it is not reported as a change."""
    diff = build_unified_diff("x = 1\n", "x = 1", "input.py", "fixed_input.py")
    assert diff == ""


def test_run_ruff_normalises_findings(monkeypatch):
    class Completed:
        returncode = 1
        stdout = '[{"code":"F401","message":"unused import","filename":"code.py","location":{"row":2,"column":1},"fix":{}}]'
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Completed())
    result = run_ruff("import os\n")
    assert result["status"] == "findings"
    assert result["findings"][0]["code"] == "F401"
    assert result["findings"][0]["line"] == 2


def test_run_ruff_handles_timeout(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ruff", timeout=10)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    result = run_ruff("x = 1\n")
    assert result["status"] == "error"
    assert "timed out" in result["message"]


def test_run_ruff_handles_invalid_json(monkeypatch):
    class Completed:
        returncode = 0
        stdout = "not json"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Completed())
    result = run_ruff("x = 1\n")
    assert result["status"] == "error"
    assert "invalid JSON" in result["message"]


# ── Format-matching tests ─────────────────────────────────────────────────────


def test_detect_indent_spaces_2():
    code = "function f() {\n  let x = 1;\n  return x;\n}"
    char, size = detect_indent(code)
    assert char == " "
    assert size == 2


def test_detect_indent_spaces_4():
    code = "def foo():\n    x = 1\n    return x\n"
    char, size = detect_indent(code)
    assert char == " "
    assert size == 4


def test_detect_indent_tabs():
    code = "function f() {\n\tlet x = 1;\n\treturn x;\n}"
    char, size = detect_indent(code)
    assert char == "\t"
    assert size == 1


def test_detect_indent_empty_or_no_indent():
    """Code with no indented lines defaults to 4-space."""
    char, size = detect_indent("x = 1\ny = 2\n")
    assert char == " "
    assert size == 4


def test_match_code_formatting_reindents_4space_to_2space():
    """LLM returns 4-space indent; original uses 2-space — must be re-indented."""
    orig = "function f() {\n  let x = 1;\n  return x;\n}"
    cand = "function f() {\n    let x = 1;\n    return x;\n}"
    result = match_code_formatting(orig, cand)
    assert "  let x = 1;" in result
    assert "    let x = 1;" not in result


def test_match_code_formatting_reindents_2space_to_4space():
    """Original uses 4-space; LLM returns 2-space — must be expanded."""
    orig = "def foo():\n    x = 1\n    return x\n"
    cand = "def foo():\n  x = 1\n  return x\n"
    result = match_code_formatting(orig, cand)
    lines = result.splitlines()
    # Body lines must be indented with exactly 4 spaces, not 2
    body_lines = [ln for ln in lines if ln.strip().startswith("x") or ln.strip().startswith("return")]
    assert all(ln.startswith("    ") for ln in body_lines), f"Expected 4-space indent: {body_lines}"
    assert not any(ln.startswith("  ") and not ln.startswith("    ") for ln in body_lines)


def test_match_code_formatting_reindents_spaces_to_tabs():
    """Original uses tabs; LLM returns spaces — must convert to tabs."""
    orig = "func main() {\n\tfmt.Println()\n}\n"
    cand = "func main() {\n    fmt.Println()\n}\n"
    result = match_code_formatting(orig, cand)
    assert "\tfmt.Println()" in result
    assert "    fmt.Println()" not in result


def test_match_code_formatting_preserves_crlf():
    """If original uses CRLF, output must also use CRLF."""
    orig = "x = 1\r\ny = 2\r\n"
    cand = "x = 1\ny = 2\n"
    result = match_code_formatting(orig, cand)
    assert "\r\n" in result
    assert result.count("\r\n") == result.count("\n")  # every \n has a \r prefix


def test_match_code_formatting_adds_trailing_newline():
    """If original ends with newline, output must too."""
    orig = "x = 1\n"
    cand = "x = 1"
    result = match_code_formatting(orig, cand)
    assert result.endswith("\n")


def test_match_code_formatting_removes_trailing_newline():
    """If original has no trailing newline, output must not add one."""
    orig = "x = 1"
    cand = "x = 1\n"
    result = match_code_formatting(orig, cand)
    assert not result.endswith("\n")


def test_match_code_formatting_passthrough_on_empty_inputs():
    """Edge-case: empty strings must not raise."""
    assert match_code_formatting("", "x = 1\n") == "x = 1\n"
    assert match_code_formatting("x = 1\n", "") == ""
