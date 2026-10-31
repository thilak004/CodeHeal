"""Deterministic, non-executing analysis tools for the code reviewer."""
from __future__ import annotations

import ast
import difflib
import json
import re
import subprocess
import sys
from typing import Any

import fingerprints

RUFF_TIMEOUT_SECONDS = 10
MAX_SOURCE_BYTES = 512 * 1024


def normalize_source(code_string: str) -> str:
    """Normalize transport-level line endings without changing Python semantics."""
    if not isinstance(code_string, str):
        raise TypeError("Source code must be text.")
    return code_string.replace("\r\n", "\n").replace("\r", "\n")


def detect_indent(code: str) -> tuple[str, int]:
    """Detect whether code uses tabs or spaces, and the base indent unit size."""
    lines = code.splitlines()
    tab_count = 0
    space_indents: list[int] = []
    for line in lines:
        if not line.strip():
            continue
        leading = line[: len(line) - len(line.lstrip())]
        if not leading:
            continue
        if leading.startswith("\t"):
            tab_count += 1
        elif leading.startswith(" "):
            space_indents.append(len(leading))
    if tab_count > len(space_indents):
        return ("\t", 1)
    if not space_indents:
        return (" ", 4)
    if all(s % 2 == 0 for s in space_indents):
        if any(s % 4 != 0 for s in space_indents):
            return (" ", 2)
        return (" ", 4)
    return (" ", 4)


def reindent_code(candidate: str, orig_char: str, orig_size: int, cand_char: str, cand_size: int) -> str:
    """Re-indent candidate code so its indentation matches original code's style."""
    if (orig_char, orig_size) == (cand_char, cand_size):
        return candidate
    res: list[str] = []
    for line in candidate.splitlines():
        if not line.strip():
            res.append("")
            continue
        leading = line[: len(line) - len(line.lstrip())]
        rest = line[len(leading):]
        if cand_char == " ":
            level = len(leading) // max(1, cand_size)
        else:
            level = leading.count("\t")
        new_leading = (orig_char * orig_size) * level
        res.append(new_leading + rest)
    return "\n".join(res)


def match_code_formatting(original: str, candidate: str) -> str:
    """Ensure candidate code matches the exact indentation style and line endings of original."""
    if not original or not candidate:
        return candidate
    orig_char, orig_size = detect_indent(original)
    cand_char, cand_size = detect_indent(candidate)
    formatted = reindent_code(candidate, orig_char, orig_size, cand_char, cand_size)
    is_crlf = "\r\n" in original
    formatted = formatted.replace("\r\n", "\n").replace("\r", "\n")
    if is_crlf:
        formatted = formatted.replace("\n", "\r\n")
    orig_has_trailing = original.endswith(("\r\n", "\n"))
    cand_has_trailing = formatted.endswith(("\r\n", "\n"))
    if orig_has_trailing and not cand_has_trailing:
        formatted += "\r\n" if is_crlf else "\n"
    elif not orig_has_trailing and cand_has_trailing:
        formatted = formatted.rstrip("\r\n")
    return formatted


def check_source_size(code_string: str, max_bytes: int = MAX_SOURCE_BYTES) -> tuple[bool, str]:
    """Reject oversized source before sending it to an external provider."""
    if not isinstance(code_string, str):
        return False, "Source code must be text."
    size = len(code_string.encode("utf-8"))
    if size > max_bytes:
        return False, f"Source is too large ({size} bytes); the limit is {max_bytes} bytes."
    return True, "Source size is within the limit."


def check_syntax(code_string: str) -> tuple[bool, str]:
    """Parse source with ``ast.parse`` and return ``(ok, message)``."""
    try:
        ast.parse(code_string)
    except (SyntaxError, ValueError, TypeError) as exc:
        if isinstance(exc, SyntaxError):
            location = f" at line {exc.lineno}" if exc.lineno else ""
            return False, f"SyntaxError: {exc.msg}{location}"
        return False, f"SyntaxError: {exc}"
    return True, "Valid syntax"


def _normalise_ruff_findings(payload: Any) -> list[dict[str, Any]]:
    """Convert Ruff JSON into a stable result shape."""
    if not isinstance(payload, list):
        return []
    findings: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        location = item.get("location") or {}
        end_location = item.get("end_location") or {}
        findings.append(
            {
                "code": str(item.get("code") or "RUFF"),
                "message": str(item.get("message") or "Ruff reported an issue."),
                "filename": str(item.get("filename") or "code.py"),
                "line": int(location.get("row") or 0),
                "column": int(location.get("column") or 0),
                "end_line": int(end_location.get("row") or 0),
                "end_column": int(end_location.get("column") or 0),
                "fixable": bool(item.get("fix")),
            }
        )
    return findings


def run_ruff(code_string: str, filename: str = "code.py") -> dict[str, Any]:
    """Run Ruff against source text, never the reviewed program."""
    command = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--output-format",
        "json",
        "--stdin-filename",
        filename,
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            input=code_string,
            capture_output=True,
            text=True,
            timeout=RUFF_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return {"status": "unavailable", "findings": [], "message": "Ruff is not installed."}
    except subprocess.TimeoutExpired:
        return {"status": "error", "findings": [], "message": "Ruff analysis timed out."}
    except OSError as exc:
        return {"status": "error", "findings": [], "message": f"Ruff could not start: {exc}"}

    detail = (completed.stderr or completed.stdout).strip()
    if "No module named ruff" in detail:
        return {"status": "unavailable", "findings": [], "message": "Ruff is not installed."}
    if completed.returncode not in (0, 1):
        return {
            "status": "error",
            "findings": [],
            "message": detail or f"Ruff exited with status {completed.returncode}.",
        }
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return {"status": "error", "findings": [], "message": "Ruff returned invalid JSON."}

    findings = _normalise_ruff_findings(payload)
    return {
        "status": "findings" if findings else "clean",
        "findings": findings,
        "message": f"Ruff found {len(findings)} issue(s)." if findings else "No Ruff issues found.",
    }


def _top_level_signature(tree: ast.AST) -> dict[str, set[str]]:
    definitions: set[str] = set()
    imports: set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions.add(node.name)
        elif isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return {"definitions": definitions, "imports": imports}


def semantic_change_warnings(original: str, proposed: str) -> list[str]:
    """Report broad top-level changes; this is a warning, not a correctness proof."""
    try:
        before = _top_level_signature(ast.parse(original))
        after = _top_level_signature(ast.parse(proposed))
    except (SyntaxError, ValueError, TypeError):
        return ["Semantic comparison was unavailable because one version is not valid Python."]

    warnings: list[str] = []
    removed_defs = sorted(before["definitions"] - after["definitions"])
    added_defs = sorted(after["definitions"] - before["definitions"])
    removed_imports = sorted(before["imports"] - after["imports"])
    added_imports = sorted(after["imports"] - before["imports"])
    if removed_defs:
        warnings.append(f"Top-level definitions removed: {', '.join(removed_defs)}.")
    if added_defs:
        warnings.append(f"Top-level definitions added: {', '.join(added_defs)}.")
    if removed_imports:
        warnings.append(f"Imports removed: {', '.join(removed_imports)}.")
    if added_imports:
        warnings.append(f"Imports added: {', '.join(added_imports)}.")
    return warnings


def validate_candidate(
    candidate: str,
    original: str,
    language: str | None = "python",
) -> tuple[bool, str, list[str]]:
    """Validate model output before it can become a proposal.

    When a language is supplied, output written in a clearly different language
    is rejected before the syntax check so a Python upload cannot be answered
    with source from another language.
    """
    if not isinstance(candidate, str) or not candidate.strip():
        return False, "The model returned empty output.", []
    stripped = candidate.strip()
    if "```" in stripped or re.search(r"^```", stripped):
        return False, "The model returned markdown fences instead of raw Python.", []
    if re.search(r"^(Here is|Sure[,!]|I fixed|Explanation:)", stripped, re.IGNORECASE):
        return False, "The model returned prose instead of raw Python.", []
    mismatch = fingerprints.language_mismatch(candidate, language)
    if mismatch:
        return False, mismatch, []
    ok, error = check_syntax(candidate)
    if not ok:
        return False, error, []
    return True, "Valid syntax", semantic_change_warnings(original, candidate)


def build_unified_diff(
    original: str,
    proposed: str,
    original_name: str = "original.py",
    proposed_name: str = "fixed.py",
) -> str:
    """Return a deterministic unified diff between two source strings.

    The final newline is a convention rather than a code change, so it is
    kept out of the diff: otherwise a proposal that differs only by a
    trailing newline reports a spurious change on the last line.
    """
    original_lines = original.splitlines(keepends=True)
    proposed_lines = proposed.splitlines(keepends=True)
    if original_lines and proposed_lines:
        original_last = original_lines[-1]
        proposed_last = proposed_lines[-1]
        if original_last.strip() == proposed_last.strip() and (original_last.endswith("\n") != proposed_last.endswith("\n")):
            original_lines[-1] = original_last.rstrip("\n")
            proposed_lines[-1] = proposed_last.rstrip("\n")
    return "".join(
        difflib.unified_diff(
            original_lines,
            proposed_lines,
            fromfile=original_name,
            tofile=proposed_name,
        )
    )
