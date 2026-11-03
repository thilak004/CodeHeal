"""Code formatting and style fixes for multiple languages."""
from __future__ import annotations

import re
import subprocess
import sys
from typing import Any


def _format_python_code(source: str) -> dict[str, Any]:
    """Format Python code using Black-style formatting."""
    lines = source.splitlines(keepends=True)
    formatted_lines = []

    for line in lines:
        # Remove trailing whitespace
        line = line.rstrip() + ('\n' if line.endswith('\n') else '')

        # Normalize indentation (convert tabs to 4 spaces)
        if '\t' in line:
            line = line.replace('\t', '    ')

        # Fix spacing around operators (but not in strings)
        if not any(quote in line for quote in ['"""', "'''"]):
            # Add space around =, ==, !=, etc (but not in keyword args)
            line = re.sub(r'(\w)([+\-*/%=!<>])([=]?)(\w)', r'\1 \2\3 \4', line)

        formatted_lines.append(line)

    formatted = ''.join(formatted_lines)

    # Check if code changed
    if formatted == source:
        return {
            "status": "clean",
            "message": "Code is already well-formatted",
            "formatted_code": source,
            "changes": [],
        }

    return {
        "status": "formatted",
        "message": "Code has been formatted",
        "formatted_code": formatted,
        "changes": _compute_changes(source, formatted),
        "style_guide": "PEP 8 (Black-style)",
    }


def _format_javascript_code(source: str) -> dict[str, Any]:
    """Format JavaScript code using Prettier-style formatting."""
    lines = source.splitlines(keepends=True)
    formatted_lines = []
    indent_level = 0
    indent_str = "  "  # 2 spaces for JavaScript

    for line in lines:
        stripped = line.strip()

        if not stripped:
            formatted_lines.append("\n")
            continue

        # Adjust indent level for closing braces
        if stripped.startswith("}") or stripped.startswith("]"):
            indent_level = max(0, indent_level - 1)

        # Apply indentation
        formatted_line = indent_str * indent_level + stripped

        # Add newline
        if not formatted_line.endswith("\n"):
            formatted_line += "\n"

        formatted_lines.append(formatted_line)

        # Adjust indent level for opening braces
        if stripped.endswith("{") or stripped.endswith("["):
            indent_level += 1

    formatted = "".join(formatted_lines)

    if formatted == source:
        return {
            "status": "clean",
            "message": "Code is already well-formatted",
            "formatted_code": source,
            "changes": [],
        }

    return {
        "status": "formatted",
        "message": "Code has been formatted",
        "formatted_code": formatted,
        "changes": _compute_changes(source, formatted),
        "style_guide": "Prettier-style",
    }


def _format_java_code(source: str) -> dict[str, Any]:
    """Format Java code using Google Style Guide."""
    lines = source.splitlines(keepends=True)
    formatted_lines = []
    indent_level = 0
    indent_str = "  "  # 2 spaces for Java (Google style)

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith("//"):
            formatted_lines.append(line if line.endswith("\n") else line + "\n")
            continue

        # Adjust indent for closing braces
        if stripped.startswith("}"):
            indent_level = max(0, indent_level - 1)

        # Apply indentation
        formatted_line = indent_str * indent_level + stripped
        if not formatted_line.endswith("\n"):
            formatted_line += "\n"

        formatted_lines.append(formatted_line)

        # Adjust indent for opening braces
        if stripped.endswith("{"):
            indent_level += 1

    formatted = "".join(formatted_lines)

    if formatted == source:
        return {
            "status": "clean",
            "message": "Code is already well-formatted",
            "formatted_code": source,
            "changes": [],
        }

    return {
        "status": "formatted",
        "message": "Code has been formatted",
        "formatted_code": formatted,
        "changes": _compute_changes(source, formatted),
        "style_guide": "Google Java Style",
    }


def _format_csharp_code(source: str) -> dict[str, Any]:
    """Format C# code."""
    lines = source.splitlines(keepends=True)
    formatted_lines = []
    indent_level = 0
    indent_str = "    "  # 4 spaces for C#

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith("//"):
            formatted_lines.append(line if line.endswith("\n") else line + "\n")
            continue

        # Adjust indent for closing braces
        if stripped.startswith("}"):
            indent_level = max(0, indent_level - 1)

        # Apply indentation
        formatted_line = indent_str * indent_level + stripped
        if not formatted_line.endswith("\n"):
            formatted_line += "\n"

        formatted_lines.append(formatted_line)

        # Adjust indent for opening braces
        if stripped.endswith("{"):
            indent_level += 1

    formatted = "".join(formatted_lines)

    if formatted == source:
        return {
            "status": "clean",
            "message": "Code is already well-formatted",
            "formatted_code": source,
            "changes": [],
        }

    return {
        "status": "formatted",
        "message": "Code has been formatted",
        "formatted_code": formatted,
        "changes": _compute_changes(source, formatted),
        "style_guide": "C# Coding Conventions",
    }


def _format_cpp_code(source: str) -> dict[str, Any]:
    """Format C++ code using LLVM Style Guide."""
    lines = source.splitlines(keepends=True)
    formatted_lines = []
    indent_level = 0
    indent_str = "  "  # 2 spaces for C++ (LLVM style)

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith("//"):
            formatted_lines.append(line if line.endswith("\n") else line + "\n")
            continue

        # Adjust indent for closing braces
        if stripped.startswith("}"):
            indent_level = max(0, indent_level - 1)

        # Apply indentation
        formatted_line = indent_str * indent_level + stripped
        if not formatted_line.endswith("\n"):
            formatted_line += "\n"

        formatted_lines.append(formatted_line)

        # Adjust indent for opening braces
        if stripped.endswith("{"):
            indent_level += 1

    formatted = "".join(formatted_lines)

    if formatted == source:
        return {
            "status": "clean",
            "message": "Code is already well-formatted",
            "formatted_code": source,
            "changes": [],
        }

    return {
        "status": "formatted",
        "message": "Code has been formatted",
        "formatted_code": formatted,
        "changes": _compute_changes(source, formatted),
        "style_guide": "LLVM Style Guide",
    }


def _compute_changes(original: str, formatted: str) -> list[dict[str, Any]]:
    """Compute diff between original and formatted code."""
    changes = []
    orig_lines = original.splitlines()
    fmt_lines = formatted.splitlines()

    for i, (orig, fmt) in enumerate(zip(orig_lines, fmt_lines), 1):
        if orig != fmt:
            changes.append({
                "line": i,
                "original": orig,
                "formatted": fmt,
            })

    return changes


def format_code(source: str, language: str = "python") -> dict[str, Any]:
    """Format code according to language style guides.

    Supported languages and style guides:
    - Python: PEP 8 (Black-style)
    - JavaScript: Prettier-style
    - Java: Google Java Style Guide
    - C#: C# Coding Conventions
    - C++: LLVM Style Guide
    """

    if language == "python":
        return _format_python_code(source)
    elif language == "javascript":
        return _format_javascript_code(source)
    elif language == "java":
        return _format_java_code(source)
    elif language == "csharp":
        return _format_csharp_code(source)
    elif language in ["cpp", "c++"]:
        return _format_cpp_code(source)
    elif language == "c":
        return _format_cpp_code(source)  # Use same style as C++
    else:
        return {
            "status": "unsupported",
            "message": f"Code formatting not supported for {language}",
            "language": language,
        }


def get_formatting_stats(original: str, formatted: str) -> dict[str, Any]:
    """Get statistics about formatting changes."""
    orig_lines = original.splitlines()
    fmt_lines = formatted.splitlines()

    changes = 0
    for orig, fmt in zip(orig_lines, fmt_lines):
        if orig != fmt:
            changes += 1

    return {
        "total_lines": len(fmt_lines),
        "lines_changed": changes,
        "percentage_changed": round((changes / len(fmt_lines) * 100) if fmt_lines else 0, 1),
        "formatting_score": round((1 - changes / len(fmt_lines)) * 100 if fmt_lines else 100, 1),
    }
