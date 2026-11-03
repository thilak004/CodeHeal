"""Advanced error detection for multiple languages and error types."""
from __future__ import annotations

import re
from typing import Any


def _finding(code: str, message: str, line: int, severity: str = "error", suggestion: str = "Review this line manually.") -> dict[str, Any]:
    """Create a standardized finding."""
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "line": max(0, line),
        "confidence": "high",
        "suggestion": suggestion,
    }


def detect_common_errors(source: str, language: str) -> list[dict[str, Any]]:
    """Detect common errors across all supported languages."""
    findings: list[dict[str, Any]] = []
    lines = source.splitlines()

    # Common indentation errors
    findings.extend(_detect_indentation_errors(lines, language))

    # Common naming convention errors
    findings.extend(_detect_naming_errors(lines, language))

    # Common operator errors
    findings.extend(_detect_operator_errors(lines, language))

    # Common type-related errors
    findings.extend(_detect_type_errors(lines, language))

    # Common whitespace errors
    findings.extend(_detect_whitespace_errors(lines, language))

    # Language-specific errors
    if language == "python":
        findings.extend(_detect_python_errors(source, lines))
    elif language in {"c", "cpp"}:
        findings.extend(_detect_c_cpp_errors(source, lines))
    elif language == "java":
        findings.extend(_detect_java_errors(source, lines))
    elif language == "javascript":
        findings.extend(_detect_javascript_errors(source, lines))
    elif language == "csharp":
        findings.extend(_detect_csharp_errors(source, lines))

    return findings


def _detect_indentation_errors(lines: list[str], language: str) -> list[dict[str, Any]]:
    """Detect indentation inconsistencies and issues."""
    findings: list[dict[str, Any]] = []
    indent_stack: list[tuple[int, int]] = []
    prev_indent = 0

    for line_number, line in enumerate(lines, 1):
        if not line.strip() or line.strip().startswith(("#", "//", "/*", "*")):
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        # Check for mixed tabs and spaces
        if "\t" in line[:indent] and " " in line[:indent]:
            findings.append(
                _finding(
                    f"{language.upper()}IND001",
                    "Mixed tabs and spaces in indentation.",
                    line_number,
                    "error",
                    "Use consistent indentation (either tabs or spaces, not both).",
                )
            )

        # Detect suspicious indentation jumps in Python
        if language == "python":
            if indent > prev_indent + 8 and stripped and not stripped.startswith("def "):
                findings.append(
                    _finding(
                        "PYIND002",
                        f"Excessive indentation increase ({indent - prev_indent} spaces).",
                        line_number,
                        "warning",
                        "Check if this line is indented correctly.",
                    )
                )

        prev_indent = indent

    return findings


def _detect_naming_errors(lines: list[str], language: str) -> list[dict[str, Any]]:
    """Detect naming convention violations."""
    findings: list[dict[str, Any]] = []

    if language == "python":
        # Check for CamelCase functions (should be snake_case)
        for line_number, line in enumerate(lines, 1):
            match = re.search(r"def\s+([a-z]+[A-Z]\w*)\s*\(", line)
            if match:
                func_name = match.group(1)
                findings.append(
                    _finding(
                        "PYNAM001",
                        f"Function '{func_name}' uses CamelCase; Python prefers snake_case.",
                        line_number,
                        "warning",
                        "Rename to snake_case (e.g., my_function).",
                    )
                )

    elif language in {"java", "csharp"}:
        # Check for snake_case class names (should be CamelCase)
        for line_number, line in enumerate(lines, 1):
            if re.search(r"class\s+([a-z_]+[a-z0-9]*)\b", line):
                match = re.search(r"class\s+([a-z_]+[a-z0-9]*)\b", line)
                if match:
                    class_name = match.group(1)
                    if "_" in class_name:
                        findings.append(
                            _finding(
                                f"{language.upper()}NAM001",
                                f"Class '{class_name}' uses snake_case; {language.capitalize()} prefers PascalCase.",
                                line_number,
                                "warning",
                                "Rename to PascalCase (e.g., MyClass).",
                            )
                        )

    return findings


def _detect_operator_errors(lines: list[str], language: str) -> list[dict[str, Any]]:
    """Detect operator usage errors."""
    findings: list[dict[str, Any]] = []

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith(("#", "//", "/*", "*")):
            continue

        # Detect assignment in conditional (C/C++/Java/C#)
        if language in {"c", "cpp", "java", "csharp"}:
            if re.search(r"if\s*\([^)]*=(?!=)[^)]*\)", stripped) and "==" not in stripped:
                findings.append(
                    _finding(
                        f"{language.upper()}OPR001",
                        "Assignment in conditional; did you mean '==' for comparison?",
                        line_number,
                        "error",
                        "Change '=' to '==' for comparison, or use assignment outside the conditional.",
                    )
                )

        # Detect == instead of = in assignment (all languages)
        if re.search(r"^\s*\w+\s*==", stripped) and "if" not in stripped and "while" not in stripped:
            findings.append(
                _finding(
                    f"{language.upper()}OPR002",
                    "Used comparison '==' instead of assignment '='.",
                    line_number,
                    "warning",
                    "Check if this should be an assignment instead.",
                )
            )

        # Detect double operators
        if re.search(r"[+\-*/%!&|^]=={2,}", stripped):
            findings.append(
                _finding(
                    f"{language.upper()}OPR003",
                    "Suspicious double operator detected.",
                    line_number,
                    "warning",
                    "Review operator usage.",
                )
            )

    return findings


def _detect_type_errors(lines: list[str], language: str) -> list[dict[str, Any]]:
    """Detect type-related errors."""
    findings: list[dict[str, Any]] = []

    if language in {"c", "cpp", "java", "csharp"}:
        for line_number, line in enumerate(lines, 1):
            stripped = line.strip()

            # Detect missing type declarations
            if re.search(r"^\w+\s+\w+\s*=", stripped) and not any(kw in stripped for kw in ["var", "const", "let", "public", "private", "protected", "static"]):
                # Check if it looks like a variable assignment without type
                if re.match(r"^[a-zA-Z_]\w*\s+[a-zA-Z_]\w*\s*=", stripped):
                    pass  # This is likely OK (type declaration)
                else:
                    pass

            # Detect null pointer dereference patterns
            if re.search(r"\w+\s*\?\s*\.\w+|->", stripped) and language in {"c", "cpp"}:
                if "->" in stripped and "nullptr" not in stripped and "null" not in stripped:
                    findings.append(
                        _finding(
                            f"{language.upper()}TYP001",
                            "Potential null pointer dereference; consider null checks.",
                            line_number,
                            "warning",
                            "Add null pointer checks before dereferencing.",
                        )
                    )

    return findings


def _detect_whitespace_errors(lines: list[str], language: str) -> list[dict[str, Any]]:
    """Detect whitespace and formatting issues."""
    findings: list[dict[str, Any]] = []

    for line_number, line in enumerate(lines, 1):
        # Detect trailing whitespace
        if line and line != line.rstrip():
            findings.append(
                _finding(
                    f"{language.upper()}WS001",
                    "Line has trailing whitespace.",
                    line_number,
                    "warning",
                    "Remove trailing whitespace.",
                )
            )

        # Detect multiple spaces around operators (stylistic)
        if re.search(r"\w\s{2,}[+\-*/%=]|[+\-*/%=]\s{2,}\w", line):
            findings.append(
                _finding(
                    f"{language.upper()}WS002",
                    "Multiple spaces around operator; inconsistent formatting.",
                    line_number,
                    "warning",
                    "Use consistent spacing around operators.",
                )
            )

    return findings


def _detect_python_errors(source: str, lines: list[str]) -> list[dict[str, Any]]:
    """Detect Python-specific errors."""
    findings: list[dict[str, Any]] = []

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect missing colons after control structures
        if re.match(r"^(if|elif|else|for|while|def|class|try|except|finally|with)\b", stripped):
            if not stripped.endswith(":") and not stripped.endswith("\\"):
                if "(" in stripped and ")" not in stripped:
                    continue  # Multi-line statement
                findings.append(
                    _finding(
                        "PYSYN001",
                        "Missing colon after control structure.",
                        line_number,
                        "error",
                        "Add ':' at the end of the line.",
                    )
                )

        # Detect incorrect string quotes
        if '"""' in stripped and "'''" in stripped:
            findings.append(
                _finding(
                    "PYSTR001",
                    "Mixed triple-quote styles; use one consistently.",
                    line_number,
                    "warning",
                    "Use either triple double-quotes or triple single-quotes.",
                )
            )

        # Detect lambda without parentheses in complex expressions
        if re.search(r"lambda\s+\w+\s*:\s*\w+\s*[+\-*/]", stripped):
            findings.append(
                _finding(
                    "PYEXP001",
                    "Lambda in complex expression; consider parentheses for clarity.",
                    line_number,
                    "warning",
                    "Add parentheses around the lambda expression.",
                )
            )

    return findings


def _detect_c_cpp_errors(source: str, lines: list[str]) -> list[dict[str, Any]]:
    """Detect C/C++-specific errors."""
    findings: list[dict[str, Any]] = []

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect #include errors
        if stripped.startswith("#include"):
            if not any(bracket in stripped for bracket in ["<", '"']):
                findings.append(
                    _finding(
                        "CINC001",
                        "Invalid #include syntax; missing brackets or quotes.",
                        line_number,
                        "error",
                        "Use #include <filename> or #include \"filename\".",
                    )
                )

        # Detect missing semicolon at end of statement (conservative)
        if (
            re.match(r"^[a-zA-Z_*&]\w*.*[^\s{};\\,:]$", stripped)
            and not stripped.startswith(("#", "//"))
            and stripped not in {"}", ")"}
            and ("(" not in stripped or ")" in stripped)
        ):
            if any(kw in stripped for kw in ["return", "break", "continue", "throw", "delete"]):
                if not stripped.endswith(";"):
                    findings.append(
                        _finding(
                            "CSYN001",
                            "Statement may be missing a semicolon.",
                            line_number,
                            "warning",
                            "Add semicolon at the end of the statement.",
                        )
                    )

        # Detect raw pointers without comments (style)
        if re.search(r"new\s+\w+\s*\(", stripped) and "std::make" not in stripped:
            findings.append(
                _finding(
                    "CMEM001",
                    "Using raw 'new'; consider std::make_unique or std::make_shared.",
                    line_number,
                    "warning",
                    "Use smart pointers for better memory management.",
                )
            )

    return findings


def _detect_java_errors(source: str, lines: list[str]) -> list[dict[str, Any]]:
    """Detect Java-specific errors."""
    findings: list[dict[str, Any]] = []

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect missing imports for common classes
        if any(cls in stripped for cls in ["ArrayList", "HashMap", "HashSet"]):
            if "import" not in source or f"import java.util.{stripped.split()[0]}" not in source:
                findings.append(
                    _finding(
                        "JIMP001",
                        f"Usage of {stripped.split()[0]} without corresponding import statement.",
                        line_number,
                        "warning",
                        f"Add import for java.util.{stripped.split()[0]}.",
                    )
                )

        # Detect incorrect method signatures
        if re.search(r"public\s+void\s+\w+\([^)]*\)\s*$", stripped):
            if "{" not in stripped:
                findings.append(
                    _finding(
                        "JSYN001",
                        "Method signature without body; missing opening brace.",
                        line_number,
                        "warning",
                        "Add '{' to start the method body.",
                    )
                )

    return findings


def _detect_javascript_errors(source: str, lines: list[str]) -> list[dict[str, Any]]:
    """Detect JavaScript-specific errors."""
    findings: list[dict[str, Any]] = []

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect console.log without proper termination
        if "console.log" in stripped and not stripped.endswith(";") and not stripped.endswith(","):
            findings.append(
                _finding(
                    "JSLOG001",
                    "console.log statement may be missing a semicolon.",
                    line_number,
                    "warning",
                    "Add semicolon at the end of the statement.",
                )
            )

        # Detect async without await
        if "async" in stripped and "await" not in source.split(stripped)[0]:
            findings.append(
                _finding(
                    "JSASYNC001",
                    "Async function declared but no await found; may not need async.",
                    line_number,
                    "warning",
                    "Either add await usage or remove async.",
                )
            )

        # Detect == instead of ===
        if "==" in stripped and "===" not in stripped and "!=" not in stripped:
            findings.append(
                _finding(
                    "JSCMP001",
                    "Using loose equality (==); prefer strict equality (===).",
                    line_number,
                    "warning",
                    "Use === for strict comparison.",
                )
            )

    return findings


def _detect_csharp_errors(source: str, lines: list[str]) -> list[dict[str, Any]]:
    """Detect C#-specific errors."""
    findings: list[dict[str, Any]] = []

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect missing using statements
        if any(cls in stripped for cls in ["List<", "Dictionary<", "HashSet<"]):
            if "using System.Collections" not in source:
                findings.append(
                    _finding(
                        "CSIMP001",
                        "Collection type used without using System.Collections directive.",
                        line_number,
                        "warning",
                        "Add 'using System.Collections.Generic;' at the top.",
                    )
                )

        # Detect property without getter/setter
        if re.search(r"public\s+\w+\s+\w+\s*{", stripped):
            if "get" not in stripped and "set" not in stripped:
                findings.append(
                    _finding(
                        "CSPROP001",
                        "Property block without get/set accessor; incomplete.",
                        line_number,
                        "warning",
                        "Add get and/or set accessors.",
                    )
                )

    return findings
