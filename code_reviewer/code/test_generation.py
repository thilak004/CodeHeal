"""Test generation mode - extract pytest proposals as unapproved suggestions."""
from __future__ import annotations

from typing import Any

from agent import _strip_markdown
from languages import detect_language
from prompts import TEST_GENERATION_PROMPT
from providers import create_provider
from tools import check_source_size, check_syntax, validate_candidate


def generate_tests(
    source: str,
    filename: str = "code.py",
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Generate AST-validated Python tests as an unapproved proposal."""
    size_ok, size_message = check_source_size(source)
    if not size_ok:
        return {"status": "failed", "error": size_message}
    if detect_language(filename) != "python":
        return {"status": "unsupported", "error": "Generated pytest proposals currently support Python files only."}
    syntax_ok, syntax_message = check_syntax(source)
    if not syntax_ok:
        return {"status": "failed", "error": f"Source must parse before test generation: {syntax_message}"}
    try:
        provider = create_provider(provider_name)
        response = provider.invoke(TEST_GENERATION_PROMPT.format_messages(code=source))
        raw = getattr(response, "content", "")
        candidate = _strip_markdown(raw if isinstance(raw, str) else str(raw), "python")
        valid, error, _ = validate_candidate(candidate, candidate)
        if not valid:
            return {"status": "failed", "error": error, "warnings": []}
        return {"status": "proposal", "tests": candidate, "warnings": [], "filename": f"test_{filename}"}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}
