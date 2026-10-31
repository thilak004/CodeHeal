"""Reliable, language-aware code-fix proposals."""
from __future__ import annotations

import ast
import hashlib
import json
import re
from typing import Any

from prompts import EXPLAIN_FIX_PROMPT, FIX_CODE_PROMPT

# Kept as a compatibility seam for existing integrations/tests that patch ChatGroq.
from langchain_groq import ChatGroq
from languages import detect_language, language_label
from multilang import candidate_is_acceptable, check_source, validate_candidate_for_language
from providers import create_provider
from tools import (
    MAX_SOURCE_BYTES,
    build_unified_diff,
    check_source_size,
    check_syntax,
    match_code_formatting,
    normalize_source,
    run_ruff,
    validate_candidate,
)


def _strip_markdown(text: str, language: str = "python") -> str:
    """Accept only a complete markdown fence; leave prose for validation to reject."""
    if not isinstance(text, str):
        return ""
    stripped = text.strip()
    language_names = {
        "python": "(?:python|py)",
        "javascript": "(?:javascript|js|jsx)",
        "typescript": "(?:typescript|ts|tsx)",
        "java": "(?:java)",
        "csharp": "(?:csharp|cs|c#)",
        "c": "(?:c|h)",
        "cpp": "(?:cpp|c\\+\\+|cxx|hpp|cc)",
        "go": "(?:go|golang)",
        "rust": "(?:rust|rs)",
        "php": "(?:php)",
        "sql": "(?:sql)",
        "html": "(?:html|htm)",
        "css": "(?:css)",
        "json": "(?:json)",
        "yaml": "(?:yaml|yml)",
    }
    fence_spec = language_names.get(language)
    if fence_spec:
        tag_pattern = rf"(?:{fence_spec}(?![A-Za-z0-9_+#.-])|(?=\s*\n)|$)"
    else:
        tag_pattern = r"[A-Za-z0-9_+#.-]*"
    # The trailing guard stops a short tag from matching a longer one, so a
    # ```cpp fence is never read as a ```c fence.
    match = re.fullmatch(
        rf"```{tag_pattern}\s*(.*?)```",
        stripped,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else stripped


def _local_explanation(original_code: str, proposed_code: str, error: str, language: str = "python") -> dict[str, str]:
    language_name = language_label(language)
    if not proposed_code:
        return {
            "summary": f"No {language_name} fix proposal was produced.",
            "root_cause": error or f"The {language_name} source did not pass validation.",
            "changes": "No proposal was generated, so no source was changed.",
            "remaining_concerns": "Correct the reported syntax error in the source and try again.",
        }
    if original_code == proposed_code:
        return {
            "summary": "The code is syntactically valid.",
            "root_cause": f"The {language_name} static validator found no syntax error.",
            "changes": "No changes were proposed.",
            "remaining_concerns": "Review the static-analysis findings for quality or security issues.",
        }
    return {
        "summary": f"A syntax-valid {language_name} fix proposal was generated.",
        "root_cause": error,
        "changes": "The proposal makes a targeted edit intended to address the reported syntax error.",
        "remaining_concerns": "Syntax validation does not prove behavioral correctness; inspect the diff before approval.",
    }


def _semantic_change_warnings(original_code: str, proposed_code: str) -> list[str]:
    """Compare top-level AST definitions and imports to flag semantic drift."""
    warnings: list[str] = []
    if not original_code or not proposed_code:
        return warnings
    try:
        orig_tree = ast.parse(original_code)
        prop_tree = ast.parse(proposed_code)
    except (SyntaxError, ValueError, TypeError):
        return warnings
    orig_imports = {ast.unparse(node) for node in ast.walk(orig_tree) if isinstance(node, (ast.Import, ast.ImportFrom))}
    prop_imports = {ast.unparse(node) for node in ast.walk(prop_tree) if isinstance(node, (ast.Import, ast.ImportFrom))}
    added_imports = prop_imports - orig_imports
    removed_imports = orig_imports - prop_imports
    if added_imports:
        warnings.append("New imports added: " + ", ".join(sorted(added_imports)))
    if removed_imports:
        warnings.append("Imports removed: " + ", ".join(sorted(removed_imports)))
    orig_defs = {ast.unparse(node) for node in ast.walk(orig_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    prop_defs = {ast.unparse(node) for node in ast.walk(prop_tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    added_defs = prop_defs - orig_defs
    removed_defs = orig_defs - prop_defs
    if added_defs:
        warnings.append("New top-level definitions: " + ", ".join(sorted(added_defs)))
    if removed_defs:
        warnings.append("Removed top-level definitions: " + ", ".join(sorted(removed_defs)))
    return warnings


def _parse_explanation(text: str, fallback: dict[str, str]) -> dict[str, str]:
    try:
        payload: Any = json.loads(_strip_markdown(text))
    except (json.JSONDecodeError, TypeError):
        return fallback
    fields = ("summary", "root_cause", "changes", "remaining_concerns")
    if not isinstance(payload, dict) or not all(isinstance(payload.get(field), str) for field in fields):
        return fallback
    return {field: payload[field].strip() for field in fields}


def _proposal_id(original: str, proposed: str, filename: str) -> str:
    value = f"{filename}\0{original}\0{proposed}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:16]


def _result(
    original_code: str,
    proposed_code: str,
    filename: str,
    logs: list[str],
    *,
    state: str,
    original_was_valid: bool,
    language: str | None = None,
    error: str | None = None,
    semantic_warnings: list[str] | None = None,
    explanation: dict[str, str] | None = None,
    attempt_count: int = 0,
) -> dict[str, Any]:
    proposed_code = proposed_code if isinstance(proposed_code, str) else ""
    language = language or detect_language(filename)
    is_python = language == "python"
    original_ruff = run_ruff(original_code, filename) if is_python else {
        "status": "not_run",
        "findings": [],
        "message": "Ruff applies only to Python sources.",
    }
    proposed_ruff = run_ruff(proposed_code, filename) if proposed_code and is_python else {
        "status": "not_run",
        "findings": [],
        "message": "Ruff applies only to Python sources." if not is_python else "No valid proposal to analyze.",
    }
    if proposed_code:
        if is_python:
            candidate_valid = check_syntax(proposed_code)[0]
        else:
            candidate_valid = candidate_is_acceptable(check_source(proposed_code, filename))
    else:
        candidate_valid = False
    return {
        "success": state in {"valid", "fixed"},
        "state": state,
        "original_was_valid": original_was_valid,
        "candidate_valid": candidate_valid,
        "original_code": original_code,
        "fixed_code": proposed_code,
        "filename": filename,
        "language": language,
        "language_label": language_label(language),
        "logs": logs,
        "error": error,
        "explanation": explanation or _local_explanation(original_code, proposed_code, error or "", language or "python"),
        "original_ruff": original_ruff,
        "proposed_ruff": proposed_ruff,
        "language_check": check_source(proposed_code, filename) if proposed_code and not is_python else None,
        "diff": build_unified_diff(original_code, proposed_code, filename, f"fixed_{filename}") if proposed_code else "",
        "semantic_warnings": semantic_warnings or [],
        "attempt_count": attempt_count,
        "proposal_id": _proposal_id(original_code, proposed_code, filename) if proposed_code else None,
        "approved": False,
        "approved_code": None,
    }


def fix_code(
    original_code: str,
    filename: str = "code.py",
    provider_name: str | None = None,
    max_attempts: int = 2,
    include_explanation: bool = False,
) -> dict[str, Any]:
    """Create a validated proposal for every supported source language."""
    language = detect_language(filename)
    if language is None:
        return _result("", "", filename, [f"Unsupported file type: {filename}"], state="unsupported", original_was_valid=False, error=f"Unsupported file type: {filename}")
    try:
        source = normalize_source(original_code)
    except TypeError as exc:
        return _result("", "", filename, [str(exc)], state="failed", original_was_valid=False, language=language, error=str(exc))

    size_ok, size_message = check_source_size(source, MAX_SOURCE_BYTES)
    if not size_ok:
        return _result(source, "", filename, [size_message], state="failed", original_was_valid=False, language=language, error=size_message)

    if language == "python":
        valid, syntax_error = check_syntax(source)
    else:
        source_result = check_source(source, filename)
        if source_result.get("status") == "unavailable":
            return _result(
                source,
                "",
                filename,
                [source_result.get("message", "The language validator is unavailable.")],
                state="unavailable",
                original_was_valid=False,
                language=language,
                error=source_result.get("message", "The language validator is unavailable."),
            )
        valid = source_result.get("status") == "clean"
        syntax_error = source_result.get("message", "Static validation reported syntax findings.")
    if valid:
        return _result(
            source,
            source,
            filename,
            [f"{language_label(language)} source is already syntactically valid."],
            state="valid",
            original_was_valid=True,
            language=language,
        )

    logs = [f"Detected {syntax_error}"]
    try:
        provider = create_provider(provider_name, groq_factory=ChatGroq)
    except Exception as exc:
        message = str(exc)
        logs.append(message)
        return _result(source, "", filename, logs, state="unavailable", original_was_valid=False, language=language, error=message)

    current_error = syntax_error
    feedback = "No previous attempt."
    for attempt in range(1, max(1, min(max_attempts, 3)) + 1):
        try:
            response = provider.invoke(
                FIX_CODE_PROMPT.format_messages(
                    language=language_label(language),
                    filename=filename,
                    code=source,
                    error=current_error,
                    feedback=feedback,
                )
            )
            raw = getattr(response, "content", "")
            candidate = _strip_markdown(raw if isinstance(raw, str) else str(raw), language)
            candidate = match_code_formatting(source, candidate)
        except Exception as exc:
            logs.append(f"Fix attempt {attempt} failed: {exc}")
            return _result(source, "", filename, logs, state="failed", original_was_valid=False, language=language, error="The model request failed.", attempt_count=attempt)

        if language == "python":
            candidate_ok, candidate_error, warnings = validate_candidate(candidate, source, language=language)
            semantic_warnings = _semantic_change_warnings(source, candidate) if candidate_ok else []
        else:
            candidate_ok, candidate_error, warnings = validate_candidate_for_language(candidate, source, filename)
            semantic_warnings = []
        if candidate_ok:
            logs.append(f"Fix attempt {attempt} produced valid {language_label(language)} source.")
            explanation = _local_explanation(source, candidate, syntax_error, language)
            if include_explanation:
                explanation = explain_proposal(
                    {
                        "state": "fixed",
                        "original_code": source,
                        "fixed_code": candidate,
                        "error": syntax_error,
                        "explanation": explanation,
                        "language": language,
                        "language_label": language_label(language),
                    },
                    provider_name=provider_name,
                    provider=provider,
                )
            return _result(
                source,
                candidate,
                filename,
                logs,
                state="fixed",
                original_was_valid=False,
                language=language,
                semantic_warnings=warnings + semantic_warnings,
                explanation=explanation,
                attempt_count=attempt,
            )
        logs.append(f"Fix attempt {attempt} rejected: {candidate_error}")
        current_error = candidate_error
        feedback = f"Previous candidate rejected: {candidate_error}. Return only corrected raw {language_label(language)} source."

    return _result(
        source,
        "",
        filename,
        logs,
        state="failed",
        original_was_valid=False,
        language=language,
        error=f"No valid fix was produced after {max_attempts} attempts.",
        attempt_count=max_attempts,
    )


def explain_proposal(
    result: dict[str, Any],
    provider_name: str | None = None,
    provider: Any | None = None,
) -> dict[str, str]:
    """Optionally request a detailed explanation after code has been validated."""
    fallback = result.get("explanation") or _local_explanation(
        result.get("original_code", ""), result.get("fixed_code", ""), result.get("error", "") or "", result.get("language", "python")
    )
    if result.get("state") != "fixed":
        return fallback
    try:
        provider = provider or create_provider(provider_name, groq_factory=ChatGroq)
        language_tag = result.get("language_label") or language_label(result.get("language")) or "Source"
        response = provider.invoke(
            EXPLAIN_FIX_PROMPT.format_messages(
                language=language_tag,
                original_code=result.get("original_code", ""),
                proposed_code=result.get("fixed_code", ""),
                error=result.get("error", "") or "Syntax error",
            )
        )
        return _parse_explanation(str(getattr(response, "content", "")), fallback)
    except Exception:
        return fallback
