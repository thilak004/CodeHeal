"""Explainable quality scoring for static review results."""
from __future__ import annotations

from typing import Any


def _issue_count(report: dict[str, Any] | None) -> int | None:
    if not report or report.get("status") in {"unavailable", "error"}:
        return None
    return len(report.get("findings", []))


def calculate_quality_score(
    syntax_ok: bool | None,
    ruff_report: dict[str, Any] | None,
    security_findings: list[dict[str, Any]] | None,
    tests_passed: bool | None = None,
) -> dict[str, Any]:
    """Calculate a reproducible score and expose unknown components explicitly."""
    components: dict[str, Any] = {}
    components["syntax"] = 100 if syntax_ok is True else 0 if syntax_ok is False else None

    ruff_count = _issue_count(ruff_report)
    components["ruff"] = max(0, 100 - min(100, ruff_count * 10)) if ruff_count is not None else None

    if security_findings is None:
        components["security"] = None
    else:
        weighted = sum(20 if item.get("severity") == "high" else 10 for item in security_findings)
        components["security"] = max(0, 100 - min(100, weighted))

    components["tests"] = 100 if tests_passed is True else 0 if tests_passed is False else None
    available = [value for value in components.values() if value is not None]
    return {
        "score": round(sum(available) / len(available)) if available else None,
        "components": components,
        "label": "not available" if not available else "needs attention" if sum(available) / len(available) < 70 else "healthy",
    }
