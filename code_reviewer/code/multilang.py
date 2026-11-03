"""Safe, static validators for supported non-Python source languages."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

import fingerprints
from languages import detect_language, language_label
from tools import MAX_SOURCE_BYTES, check_source_size, check_syntax

TOOL_TIMEOUT_SECONDS = 10

# A method or function signature, such as a C# or Java method. It is closed by
# a brace, so it never misses a terminator.
_METHOD_SIGNATURE = re.compile(
    r"^(?:(?:public|private|protected|internal|static|final|abstract|virtual|override|sealed|"
    r"partial|async|unsafe|extern|new|readonly|const|volatile|explicit|implicit)\s+)*"
    r"[A-Za-z_][\w:<>, ]*?[*&]?\s+[A-Za-z_]\w*\s*(?:<[^>]*>)?\s*\([^;]*\)\s*"
    r"(?:(?:const|noexcept|override|final|mutable)\s*|throws\s+\w[\w.]*\s*)*$"
)

# A statement that ends with one of these operators continues on the next
# line, so the line itself does not need a terminator.
_CONTINUES_AT_END = re.compile(
    r"(?:&&|\|\||<<=|>>=|<<|>>|==|!=|<=|>=|\+=|-=|\*=|/=|%=|->|\+\+|--|\\"
    r"|[+\-*/%=<>!&|^~?.(,\[{])$"
)

# A statement that starts with one of these tokens continues the line above.
# A closing brace is not one of them: it ends a block, not an expression.
_CONTINUES_BELOW = re.compile(r"^(?:<<|>>|&&|\|\||[)\],.]|->|::|\.\.\.)")

# Keywords that start a declaration rather than a statement. None of them is
# terminated by a semicolon on its own.
_DECLARATION_KEYWORDS = re.compile(
    r"^(?:if|else|for|while|switch|case|default|try|catch|finally|class|struct|"
    r"namespace|package|import|using|typedef|friend|operator|template|typename|enum|"
    r"union|public|private|protected|impl|match|constexpr|consteval|inline|explicit|virtual|"
    r"static_cast|const_cast|dynamic_cast|reinterpret_cast)\b"
)

# A class or struct declaration at the start of a line. A forward declaration
# such as "class Greeter;" ends with a semicolon and declares no body.
_CLASS_DECLARATION = re.compile(
    r"^(?:template\s*<[^>]*>\s*)?(?:class|struct)\s+([A-Za-z_]\w*)"
)

# Comment markers per language. Delimiters inside a comment are text, not
# syntax, so they are blanked before braces are counted.
_BLOCK_COMMENTS: tuple[tuple[str, str], ...] = (("/*", "*/"),)
_LINE_COMMENTS: dict[str, tuple[str, ...]] = {
    "python": ("#",),
    "javascript": ("//",),
    "java": ("//",),
    "c": ("//",),
    "cpp": ("//",),
    "csharp": ("//",),
}


def _result(status: str, message: str, findings: list[dict[str, Any]] | None = None, tool: str = "builtin") -> dict[str, Any]:
    return {"status": status, "message": message, "findings": findings or [], "tool": tool}


def _finding(code: str, message: str, line: int, severity: str = "error", suggestion: str = "Review this line manually.") -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "line": max(0, line),
        "confidence": "high",
        "suggestion": suggestion,
    }


def _run_tool(command: list[str], source: str, tool: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            input=source,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return _result("unavailable", f"{tool} is not installed or not on PATH.", tool=tool)
    except subprocess.TimeoutExpired:
        return _result("error", f"{tool} analysis timed out.", tool=tool)
    except OSError as exc:
        return _result("error", f"{tool} could not start: {exc}", tool=tool)

    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode == 0:
        return _result("clean", f"{tool} reported no errors.", tool=tool)
    return _result(
        "findings",
        f"{tool} reported errors.",
        [_finding(f"{tool.upper()}", output[:2000] or f"{tool} exited with status {completed.returncode}.", 0)],
        tool=tool,
    )


def _blank_literals_and_comments(source: str, language: str) -> str:
    """Replace string literals and comment text with spaces.

    Delimiters inside a string or a comment are text, not syntax, so they must
    not be counted as unbalanced braces or brackets.
    """
    line_markers = _LINE_COMMENTS.get(language, ("//",)) if language else ("//",)
    out: list[str] = []
    in_block = False
    for line in source.splitlines():
        rendered: list[str] = []
        index = 0
        while index < len(line):
            if in_block:
                end = line.find("*/", index)
                if end == -1:
                    rendered.append(" " * (len(line) - index))
                    index = len(line)
                    continue
                rendered.append(" " * (end + 2 - index))
                index = end + 2
                in_block = False
                continue
            if line.startswith("/*", index):
                end = line.find("*/", index + 2)
                if end == -1:
                    rendered.append(" " * (len(line) - index))
                    index = len(line)
                    in_block = True
                    continue
                rendered.append(" " * (end + 2 - index))
                index = end + 2
                continue
            matched = False
            for marker in line_markers:
                if line.startswith(marker, index):
                    rendered.append(" " * (len(line) - index))
                    index = len(line)
                    matched = True
                    break
            if matched:
                break
            character = line[index]
            if character in {'"', "'"}:
                end = index + 1
                while end < len(line):
                    if line[end] == "\\":
                        end += 2
                        continue
                    if line[end] == character:
                        end += 1
                        break
                    end += 1
                rendered.append(" " * (end - index))
                index = end
                continue
            rendered.append(character)
            index += 1
        out.append("".join(rendered))
    return "\n".join(out)


def _bracket_findings(source: str, pairs: tuple[tuple[str, str], ...], code: str, language: str = "") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    stack: list[tuple[str, int]] = []
    opening = {left: right for left, right in pairs}
    closing = {right: left for left, right in pairs}
    for line_number, line in enumerate(_blank_literals_and_comments(source, language).splitlines(), 1):
        for character in line:
            if character in opening:
                stack.append((character, line_number))
            elif character in closing:
                if not stack or stack[-1][0] != closing[character]:
                    findings.append(_finding(code, f"Unexpected closing delimiter {character}.", line_number))
                else:
                    stack.pop()
    findings.extend(
        _finding(code, f"Unclosed delimiter {left}.", line_number)
        for left, line_number in stack
    )
    return findings


def _json_check(source: str) -> dict[str, Any]:
    try:
        json.loads(source)
    except json.JSONDecodeError as exc:
        return _result("findings", f"JSON syntax error at line {exc.lineno}, column {exc.colno}.", [_finding("JSON001", exc.msg, exc.lineno)])
    return _result("clean", "JSON syntax is valid.")


def _yaml_check(source: str) -> dict[str, Any]:
    try:
        import yaml
    except ImportError:
        lines = source.splitlines()
        for number, line in enumerate(lines, 1):
            if line.count(":") > 1 and not line.lstrip().startswith("#"):
                return _result("findings", "Basic YAML structure may be invalid.", [_finding("YAML001", "Review this mapping line; PyYAML is not installed.", number, "warning")])
        return _result("unavailable", "YAML parser is not installed; static fallback checks found no obvious issue.")
    try:
        yaml.safe_load(source)
    except yaml.YAMLError as exc:
        line = getattr(getattr(exc, "problem_mark", None), "line", 0) + 1
        return _result("findings", f"YAML syntax error at line {line}.", [_finding("YAML001", str(exc), line)])
    return _result("clean", "YAML syntax is valid.")


def _html_check(source: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if source.count("<script") != source.count("</script>"):
        findings.append(_finding("HTML001", "Script tags are not balanced.", 1))
    if source.count("<div") != source.count("</div>"):
        findings.append(_finding("HTML002", "Div tags are not balanced.", 1, "warning"))
    return _result("findings" if findings else "clean", "HTML structure needs review." if findings else "Basic HTML structure is balanced.", findings)


def _css_check(source: str) -> dict[str, Any]:
    findings = _bracket_findings(source, (("{", "}"), ("(", ")")), "CSS001", "css")
    return _result("findings" if findings else "clean", "CSS delimiters need review." if findings else "Basic CSS delimiters are balanced.", findings)


def _sql_check(source: str) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(source.splitlines(), 1):
        if not re.search(r"\b(SELECT|UPDATE|DELETE|INSERT)\b", line, re.IGNORECASE):
            continue
        if ";" in line or "(" in line:
            continue
        # A statement may span several lines, so the terminator is looked for
        # in the whole script. A statement that is never terminated is reported
        # at the line that opens it.
        if re.search(r";\s*\Z", source, re.IGNORECASE):
            continue
        findings.append(_finding("SQL001", "SQL statement may be missing a terminator; verify the dialect.", line_number, "warning"))
    return _result("findings" if findings else "clean", "SQL requires review." if findings else "No basic SQL issues detected.", findings)


def _class_termination_findings(source: str, code: str) -> list[dict[str, Any]]:
    """Detect a common C/C++/Java-style missing semicolon after a class body."""
    findings: list[dict[str, Any]] = []
    depth = 0
    pending_class = False
    class_depth: int | None = None
    for line_number, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        # A forward declaration such as "class Greeter;" declares no body, so
        # it can never miss a terminator.
        declaration = _CLASS_DECLARATION.match(stripped)
        if declaration and "{" not in stripped:
            pending_class = False
        elif declaration or re.search(r"\b(?:class|struct)\s+[A-Za-z_]\w*", stripped):
            pending_class = True
        for character_index, character in enumerate(line):
            before = depth
            if character == "{":
                depth += 1
                if pending_class and class_depth is None:
                    class_depth = depth
                    pending_class = False
            elif character == "}":
                if class_depth is not None and before == class_depth:
                    trailing = line[character_index + 1 :].strip()
                    if not trailing.startswith(";"):
                        findings.append(
                            _finding(
                                code,
                                "Class or struct definition may be missing a trailing semicolon.",
                                line_number,
                                "error",
                                "Add ';' after the closing class or struct brace.",
                            )
                        )
                    class_depth = None
                depth = max(0, depth - 1)
        if pending_class and "{" in line:
            pending_class = False
    return findings


def _fallback_external_check(language: str, source: str, tool: str) -> dict[str, Any]:
    """Run built-in checks when a native compiler or formatter is unavailable."""
    pairs = (("{", "}"), ("(", ")"), ("[", "]"))
    findings = _bracket_findings(source, pairs, f"{language.upper()}001", language)
    lines = source.splitlines()

    if language in {"c", "cpp"}:
        findings.extend(_class_termination_findings(source, f"{language.upper()}003"))

    if language in {"javascript", "typescript"}:
        for line_number, line in enumerate(lines, 1):
            stripped = line.strip()
            if re.search(r"(?:const|let|var)\s+\w+\s*=\s*;", stripped):
                findings.append(_finding(f"{language.upper()}002", "Variable declaration is missing a value.", line_number))
            if re.search(r"\b(?:if|while|for)\s*\([^)]*$", stripped):
                findings.append(_finding(f"{language.upper()}003", "Control statement has an unclosed condition.", line_number))

    if language in {"c", "cpp", "java", "csharp"}:
        # A method or function signature is closed by a brace, not by a
        # semicolon, so it never misses a terminator. This only holds for the
        # languages whose bodies are brace-delimited.
        brace_bodied = language in {"c", "cpp", "java", "csharp"}
        # A statement may be split over several lines, so the parenthesis
        # depth is tracked across lines: a line inside an open parameter list
        # continues the line above it. The depth is counted on the source
        # with string literals and comments blanked out, so a parenthesis
        # inside text does not shift it.
        code_lines = _blank_literals_and_comments(source, language).splitlines()
        depth = 0
        for line_number, line in enumerate(lines, 1):
            stripped = line.strip()
            code_line = code_lines[line_number - 1] if line_number <= len(code_lines) else ""
            depth_before = depth
            depth = max(0, depth + code_line.count("(") - code_line.count(")"))
            if not stripped or stripped.startswith(("//", "/*", "*", "#", "<?php", "?>")):
                continue
            if stripped.endswith((";", "{", "}", ":", ",")):
                continue
            # A line inside an open parenthesis continues the statement above,
            # and a line that opens one continues the statement below.
            if depth_before > 0 or depth > 0:
                continue
            # A statement that ends with an operator continues on the next
            # line, so the line itself does not need a terminator.
            if _CONTINUES_AT_END.search(stripped):
                continue
            # A statement that starts with an operator continues the line
            # above it, so it has no terminator of its own either.
            if _CONTINUES_BELOW.match(stripped):
                continue
            if brace_bodied and _METHOD_SIGNATURE.match(stripped):
                continue
            if _DECLARATION_KEYWORDS.match(stripped):
                continue
            looks_like_statement = (
                re.match(r"^(?:return|throw|break|continue|cin|cout|cerr|clog)\b", stripped)
                or re.search(r"(?:=|\b(?:cin|cout|cerr|clog)\s*(?:>>|<<)|\b(?:System\.out|Console\.))", stripped)
                or re.match(r"^(?:const\s+)?(?:std::)?[A-Za-z_]\w*(?:<[^>]+>)?\s+\w+", stripped)
                or re.match(r"^[A-Za-z_]\w*\s*\([^)]*\)$", stripped)
            )
            if looks_like_statement:
                findings.append(
                    _finding(
                        f"{language.upper()}002",
                        "This statement may be missing a semicolon.",
                        line_number,
                        "warning",
                        "Review the statement terminator for this language.",
                    )
                )

    if language == "python":
        return _result("clean", "Built-in Python validation completed.", tool="built-in")
    if findings:
        message = "Built-in fallback validation found possible issue(s)."
    else:
        message = "Built-in fallback validation completed; no obvious syntax issues were detected."
    return _result("findings" if findings else "clean", message, findings, tool="built-in fallback")


def _external_check(language: str, source: str) -> dict[str, Any]:
    commands = {
        "javascript": ("node", ["node", "--check", "-"], "Node.js"),
        "java": ("javac", ["javac", "-Xlint", "-"], "javac"),
        "csharp": ("dotnet", ["dotnet", "format", "--verify-no-changes"], "dotnet"),
        "c": ("clang", ["clang", "-fsyntax-only", "-x", "c", "-"], "Clang"),
        "cpp": ("clang++", ["clang++", "-fsyntax-only", "-x", "c++", "-"], "Clang++"),
    }
    executable, command, tool = commands[language]
    if shutil.which(executable) is None:
        return _fallback_external_check(language, source, tool)
    return _run_tool(command, source, tool)


def _language_mismatch(candidate: str, language: str | None) -> str | None:
    """Reject output written in a different language before static validation.

    The fingerprint check is shared by every supported language, so a proposal
    is rejected whenever the provider answers a request in a clearly foreign
    language, not only when it answers with Python.
    """
    return fingerprints.language_mismatch(candidate, language)


def split_findings(findings: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split findings into blocking errors and advisory warnings.

    A finding that reports an error severity is a proven defect, such as an
    unbalanced delimiter. A finding that reports a warning severity is a
    heuristic, so it is surfaced to the reviewer but it does not block a
    proposal on its own.
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for finding in findings or []:
        if str(finding.get("severity", "error")).strip().lower() == "error":
            errors.append(finding)
        else:
            warnings.append(finding)
    return errors, warnings


def candidate_is_acceptable(result: dict[str, Any]) -> bool:
    """Report whether a validation result may be offered as a proposal."""
    if result.get("status") in {"error", "unsupported"}:
        return False
    errors, _warnings = split_findings(result.get("findings"))
    return not errors


def advisory_messages(result: dict[str, Any]) -> list[str]:
    """Collect the non-blocking findings of a validation result."""
    _errors, warnings = split_findings(result.get("findings"))
    messages = []
    for finding in warnings:
        line = finding.get("line")
        message = str(finding.get("message", "")).strip()
        if not message:
            continue
        messages.append(f"line {line}: {message}" if line else message)
    if result.get("status") == "unavailable":
        messages.append(str(result.get("message", "The language checker is unavailable.")))
    return messages


def validate_candidate_for_language(candidate: str, original: str, filename: str) -> tuple[bool, str, list[str]]:
    """Validate a generated candidate without executing it.

    A missing external checker is reported as a warning rather than being
    presented as proof that the candidate is syntactically correct. A
    heuristic warning does not reject the candidate: only a proven error
    does, so a language whose checker is a heuristic is not blocked by it.
    """
    if not isinstance(candidate, str) or not candidate.strip():
        return False, "The model returned empty output.", []
    stripped = candidate.strip()
    if "```" in stripped or re.search(r"^(Here is|Sure[,!]|I fixed|Explanation:)", stripped, re.IGNORECASE):
        return False, "The model returned prose or markdown instead of source code.", []
    language = detect_language(filename)
    mismatch = _language_mismatch(candidate, language)
    if mismatch:
        return False, mismatch, []
    result = check_source(candidate, filename)
    if result.get("status") == "error":
        return False, str(result.get("message", "The candidate could not be validated.")), []
    errors, _warnings = split_findings(result.get("findings"))
    if errors:
        first = errors[0]
        return False, str(first.get("message", result.get("message", "The candidate failed validation."))), advisory_messages(result)
    warnings = advisory_messages(result)
    return True, "Valid source" if result.get("status") == "clean" else "Source proposal requires manual validation", warnings


def check_source(source: str, filename: str) -> dict[str, Any]:
    """Validate a supported source file without importing or executing it."""
    size_ok, size_message = check_source_size(source, MAX_SOURCE_BYTES)
    if not size_ok:
        return _result("error", size_message)
    language = detect_language(filename)
    if language is None:
        return _result("unsupported", f"Unsupported file type: {filename}")
    if language == "json":
        result = _json_check(source)
    elif language == "yaml":
        result = _yaml_check(source)
    elif language == "html":
        result = _html_check(source)
    elif language == "css":
        result = _css_check(source)
    elif language == "sql":
        result = _sql_check(source)
    elif language == "python":
        # Python has its own AST-based checker, so it is never parsed by the
        # language fallbacks.
        python_valid, python_message = check_syntax(source)
        result = _result("clean" if python_valid else "findings", python_message, None if python_valid else [_finding("PY001", python_message, 0)])
    else:
        result = _external_check(language, source)

    # Add advanced error detection findings
    try:
        from error_detection import detect_common_errors
        additional_findings = detect_common_errors(source, language)
        if additional_findings:
            existing = result.get("findings", []) or []
            result["findings"] = existing + additional_findings
            if result.get("status") == "clean" and additional_findings:
                result["status"] = "findings"
    except Exception:
        pass  # If advanced detection fails, continue with basic checks

    return {
        **result,
        "language": language,
        "language_label": language_label(language),
        "filename": filename,
    }
