"""Proposal-oriented conversational coding assistance."""
from __future__ import annotations

import json
from typing import Any

from agent import _strip_markdown
from languages import detect_language, language_label
from multilang import candidate_is_acceptable, check_source, validate_candidate_for_language
from prompts import ASSISTANT_PROMPT
from providers import create_provider
from tools import check_source_size, check_syntax, match_code_formatting, normalize_source, validate_candidate

CODE_ACTIONS = {"fix", "refactor", "type_hints", "tests", "complete"}


def _context_text(context: Any) -> str:
    if not context:
        return "No additional project context was selected."
    if isinstance(context, str):
        return context
    try:
        return json.dumps(context, ensure_ascii=False, indent=2)[:80_000]
    except (TypeError, ValueError):
        return str(context)[:80_000]


def ask_assistant(
    source: str,
    request: str,
    *,
    filename: str = "code.py",
    action: str = "question",
    context: Any = None,
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Ask the selected provider for an answer or an unapproved code proposal."""
    language = detect_language(filename)
    if language is None:
        return {"status": "unsupported", "error": f"Unsupported file type: {filename}", "answer": "", "proposal": None}
    try:
        source = normalize_source(source)
    except TypeError as exc:
        return {"status": "failed", "error": str(exc), "answer": "", "proposal": None}
    size_ok, size_message = check_source_size(source)
    if not size_ok:
        return {"status": "failed", "error": size_message, "answer": "", "proposal": None}
    if not isinstance(request, str) or not request.strip():
        return {"status": "failed", "error": "Enter a request for the assistant.", "answer": "", "proposal": None}
    if action in CODE_ACTIONS:
        if language == "python":
            valid, syntax_message = check_syntax(source)
        else:
            source_result = check_source(source, filename)
            valid = candidate_is_acceptable(source_result)
            syntax_message = str(source_result.get("message", "The source could not be validated."))
        if not valid:
            return {
                "status": "needs_fix",
                "error": f"Source must parse before a code proposal can be generated: {syntax_message}",
                "answer": "",
                "proposal": None,
            }
    try:
        provider = create_provider(provider_name)
        response = provider.invoke(
            ASSISTANT_PROMPT.format_messages(
                action=action,
                language=language_label(language),
                filename=filename,
                request=request.strip(),
                code=source,
                context=_context_text(context),
            )
        )
        content = getattr(response, "content", "")
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc), "answer": "", "proposal": None}

    if not content:
        return {"status": "failed", "error": "The selected provider returned empty output.", "answer": "", "proposal": None}
    if action in CODE_ACTIONS:
        candidate = _strip_markdown(content, language or "python")
        candidate = match_code_formatting(source, candidate)
        if language == "python":
            valid, validation_error, warnings = validate_candidate(candidate, source, language=language)
        else:
            valid, validation_error, warnings = validate_candidate_for_language(candidate, source, filename)
        if not valid:
            return {
                "status": "failed",
                "error": validation_error,
                "answer": "",
                "proposal": None,
                "warnings": warnings,
            }
        return {
            "status": "proposal",
            "error": None,
            "answer": "",
            "proposal": candidate,
            "warnings": warnings,
            "filename": filename,
        }
    return {"status": "answer", "error": None, "answer": content, "proposal": None, "filename": filename}
