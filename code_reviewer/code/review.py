"""Review-mode orchestration for Python and supported source languages."""
from __future__ import annotations

import json
from typing import Any

from error_detection import detect_common_errors
from languages import detect_language, language_label
from multilang import candidate_is_acceptable, check_source
from prompts import REVIEW_PROMPT
from providers import create_provider
from quality import calculate_quality_score
from security import scan_security
from tools import check_source_size, check_syntax, run_ruff

MODES = ("fix_syntax", "review_quality", "security", "refactor", "type_hints", "tests", "ai_detector")


def _local_findings(source: str, mode: str, language: str | None = "python") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if language == "python" and mode in {"security", "review_quality"}:
        findings.extend(scan_security(source))
    # Add common error detection for all languages and modes
    if language:
        try:
            findings.extend(detect_common_errors(source, language))
        except Exception as exc:
            import sys
            print(f"Error detecting common errors: {exc}", file=sys.stderr)
    return findings


def _parse_findings(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return []
    raw = payload.get("findings") if isinstance(payload, dict) else []
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            line = max(0, int(item.get("line", 0) or 0))
        except (TypeError, ValueError):
            line = 0
        result.append(
            {
                "severity": str(item.get("severity", "info")),
                "code": str(item.get("code", "LLM")),
                "message": str(item.get("message", "Review finding")),
                "line": line,
                "confidence": str(item.get("confidence", "low")),
                "suggestion": str(item.get("suggestion", "Review manually.")),
            }
        )
    return result


def _review_python(source: str, filename: str, mode: str, provider_name: str | None) -> dict[str, Any]:
    syntax_ok, syntax_message = check_syntax(source)
    ruff = run_ruff(source, filename)
    findings = _local_findings(source, mode, "python")
    provider_message = None
    if mode in {"review_quality", "refactor", "type_hints"} and syntax_ok:
        try:
            provider = create_provider(provider_name)
            response = provider.invoke(REVIEW_PROMPT.format_messages(mode=mode, language="Python", code=source))
            findings.extend(_parse_findings(str(response.content)))
        except Exception as exc:
            provider_message = f"AI review unavailable: {exc}"
    score = calculate_quality_score(syntax_ok, ruff, findings, None)
    return {
        "status": "valid" if syntax_ok else "needs_fix",
        "syntax_ok": syntax_ok,
        "syntax_message": syntax_message,
        "ruff": ruff,
        "findings": findings,
        "score": score,
        "provider_message": provider_message,
        "filename": filename,
        "mode": mode,
        "language": "python",
        "language_label": "Python",
    }


def _review_other_language(source: str, filename: str, mode: str, provider_name: str | None) -> dict[str, Any]:
    language_result = check_source(source, filename)
    findings = list(language_result.get("findings", []))
    provider_message = None
    language = language_result.get("language")
    # A heuristic warning does not stop the review, so the source is reviewed
    # whenever no proven error was found.
    source_acceptable = candidate_is_acceptable(language_result)
    if mode in {"review_quality", "refactor", "type_hints"} and source_acceptable:
        try:
            provider = create_provider(provider_name)
            response = provider.invoke(
                REVIEW_PROMPT.format_messages(
                    mode=mode,
                    language=language_label(language),
                    code=source,
                )
            )
            findings.extend(_parse_findings(str(response.content)))
        except Exception as exc:
            provider_message = f"AI review unavailable: {exc}"
    status = "valid" if source_acceptable else language_result.get("status", "error")
    return {
        "status": status,
        "syntax_ok": status == "valid",
        "syntax_message": language_result.get("message", "Language check completed."),
        "ruff": {"status": "not_run", "findings": [], "message": "Ruff applies only to Python sources."},
        "language_check": language_result,
        "findings": findings,
        "score": calculate_quality_score(status == "valid", None, findings, None),
        "provider_message": provider_message,
        "filename": filename,
        "mode": mode,
        "language": language,
        "language_label": language_result.get("language_label", "Unknown"),
    }


def review_source(
    source: str,
    filename: str = "code.py",
    mode: str = "review_quality",
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Run static review without importing, compiling, or executing source."""
    if mode not in MODES:
        return {"status": "failed", "error": f"Unknown review mode: {mode}", "findings": []}
    size_ok, size_message = check_source_size(source)
    if not size_ok:
        return {"status": "failed", "error": size_message, "findings": []}
    language = detect_language(filename)
    if language is None:
        return {"status": "unsupported", "error": f"Unsupported file type: {filename}", "findings": []}
    if mode == "tests":
        if language != "python":
            return {"status": "unsupported", "error": "Test generation is currently available for Python files only.", "findings": [], "language": language}
        from test_generation import generate_tests
        return generate_tests(source, filename, provider_name)
    if mode == "ai_detector":
        from detector import detect_ai_code
        return detect_ai_code(source, filename)
    if language == "python":
        return _review_python(source, filename, mode, provider_name)
    return _review_other_language(source, filename, mode, provider_name)
