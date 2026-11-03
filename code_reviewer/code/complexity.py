"""Code complexity analysis and metrics calculation."""
from __future__ import annotations

import ast
import re
from typing import Any


def _count_lines(source: str) -> dict[str, int]:
    """Count lines of code, comments, and blank lines."""
    lines = source.splitlines()
    code_lines = 0
    comment_lines = 0
    blank_lines = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_lines += 1
        elif stripped.startswith("#"):
            comment_lines += 1
        else:
            code_lines += 1

    return {
        "total": len(lines),
        "code": code_lines,
        "comments": comment_lines,
        "blank": blank_lines,
    }


def _calculate_cyclomatic_complexity(source: str) -> int:
    """Calculate cyclomatic complexity for Python code.

    Cyclomatic complexity = number of decision points + 1
    Decision points: if, elif, else, for, while, except, and, or
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return 0

    complexity = 1  # Base complexity
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            # Count 'and' and 'or' operators
            complexity += len(node.values) - 1

    return complexity


def _calculate_max_nesting_depth(source: str) -> int:
    """Calculate maximum nesting depth in code."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return 0

    max_depth = 0

    def calculate_depth(node: ast.AST, depth: int = 0) -> None:
        nonlocal max_depth
        max_depth = max(max_depth, depth)

        for child in ast.iter_child_nodes(node):
            if isinstance(
                child,
                (
                    ast.If,
                    ast.For,
                    ast.While,
                    ast.With,
                    ast.Try,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                    ast.ClassDef,
                ),
            ):
                calculate_depth(child, depth + 1)
            else:
                calculate_depth(child, depth)

    calculate_depth(tree)
    return max_depth


def _calculate_average_function_length(source: str) -> float:
    """Calculate average function/method length in lines."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return 0.0

    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    if not functions:
        return 0.0

    total_lines = sum(node.end_lineno - node.lineno + 1 for node in functions if node.end_lineno)
    return total_lines / len(functions) if functions else 0.0


def _calculate_maintainability_index(
    cyclomatic: int, lines_of_code: int, comment_lines: int
) -> float:
    """Calculate maintainability index (0-100).

    Based on: cyclomatic complexity, lines of code, and comments
    """
    if lines_of_code == 0:
        return 100.0

    # Normalize values
    cc_score = max(0, 100 - (cyclomatic * 10))
    loc_score = max(0, 100 - (lines_of_code / 10))
    comment_ratio = comment_lines / lines_of_code if lines_of_code > 0 else 0
    comment_score = comment_ratio * 100

    # Calculate average
    maintainability = (cc_score + loc_score + comment_score) / 3
    return max(0, min(100, maintainability))


def _count_functions(source: str) -> int:
    """Count number of functions/methods."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return 0

    return len([node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))])


def _count_classes(source: str) -> int:
    """Count number of classes."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return 0

    return len([node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)])


def _get_halstead_metrics(source: str) -> dict[str, Any]:
    """Calculate basic Halstead complexity metrics.

    Returns operators count, operands count, and volume estimate.
    """
    # Simple regex-based approach for token counting
    # In production, use a proper tokenizer
    operators = len(re.findall(r'[\+\-\*\/\%\=\<\>\!&\|]', source))
    operands = len(re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', source))

    if operators == 0 or operands == 0:
        return {"operators": 0, "operands": 0, "volume": 0}

    # Halstead volume = (operators + operands) * log2(operators + operands)
    total_tokens = operators + operands
    try:
        import math

        volume = total_tokens * math.log2(total_tokens)
    except (ValueError, ZeroDivisionError):
        volume = 0

    return {"operators": operators, "operands": operands, "volume": round(volume, 2)}


def calculate_code_metrics(source: str, language: str = "python") -> dict[str, Any]:
    """Calculate comprehensive code metrics.

    Currently supports Python. Other languages return limited metrics.
    """
    if language != "python":
        return {
            "status": "unsupported",
            "message": f"Detailed metrics not available for {language}. Only basic line counts supported.",
            "language": language,
            "lines": _count_lines(source),
        }

    lines = _count_lines(source)
    cyclomatic = _calculate_cyclomatic_complexity(source)
    max_nesting = _calculate_max_nesting_depth(source)
    avg_function_length = _calculate_average_function_length(source)
    function_count = _count_functions(source)
    class_count = _count_classes(source)
    halstead = _get_halstead_metrics(source)

    # Calculate maintainability index
    maintainability = _calculate_maintainability_index(
        cyclomatic, lines["code"], lines["comments"]
    )

    # Determine health status
    if cyclomatic <= 5:
        complexity_status = "low"
    elif cyclomatic <= 10:
        complexity_status = "moderate"
    elif cyclomatic <= 15:
        complexity_status = "high"
    else:
        complexity_status = "very_high"

    if maintainability >= 85:
        maintainability_status = "excellent"
    elif maintainability >= 70:
        maintainability_status = "good"
    elif maintainability >= 50:
        maintainability_status = "moderate"
    else:
        maintainability_status = "poor"

    return {
        "status": "success",
        "language": language,
        "metrics": {
            "lines": lines,
            "cyclomatic_complexity": {
                "value": cyclomatic,
                "status": complexity_status,
                "description": f"Complexity is {complexity_status}. " + (
                    "Consider refactoring if > 10."
                    if cyclomatic > 10
                    else "Good complexity level."
                ),
            },
            "max_nesting_depth": {
                "value": max_nesting,
                "status": "good" if max_nesting <= 4 else "warning" if max_nesting <= 6 else "poor",
                "description": f"Maximum nesting depth is {max_nesting} levels.",
            },
            "average_function_length": {
                "value": round(avg_function_length, 2),
                "status": "good" if avg_function_length <= 50 else "warning" if avg_function_length <= 100 else "poor",
                "description": f"Average function is {round(avg_function_length, 1)} lines.",
            },
            "function_count": function_count,
            "class_count": class_count,
            "comment_ratio": {
                "value": round(
                    (lines["comments"] / lines["code"] * 100) if lines["code"] > 0 else 0, 2
                ),
                "status": "good"
                if (lines["comments"] / lines["code"] * 100 if lines["code"] > 0 else 0) >= 15
                else "warning"
                if (lines["comments"] / lines["code"] * 100 if lines["code"] > 0 else 0) >= 10
                else "poor",
                "description": f"{lines['comments']} comment lines found.",
            },
            "maintainability_index": {
                "value": round(maintainability, 2),
                "status": maintainability_status,
                "description": f"Maintainability index is {round(maintainability, 1)} ({maintainability_status}).",
            },
            "halstead": halstead,
        },
        "summary": {
            "overall_status": maintainability_status,
            "refactoring_needed": complexity_status in {"high", "very_high"} or max_nesting > 6,
            "recommendations": _get_recommendations(
                cyclomatic, max_nesting, avg_function_length, maintainability, lines
            ),
        },
    }


def _get_recommendations(
    cyclomatic: int,
    max_nesting: int,
    avg_function_length: float,
    maintainability: float,
    lines: dict[str, int],
) -> list[str]:
    """Generate recommendations based on metrics."""
    recommendations = []

    if cyclomatic > 10:
        recommendations.append(
            f"Cyclomatic complexity is {cyclomatic}. Consider breaking functions into smaller pieces."
        )

    if max_nesting > 6:
        recommendations.append(
            f"Maximum nesting depth is {max_nesting} levels. Consider extracting nested logic into helper functions."
        )

    if avg_function_length > 100:
        recommendations.append(
            f"Average function length is {avg_function_length:.0f} lines. Aim for smaller functions (< 50 lines)."
        )

    if maintainability < 50:
        recommendations.append("Code maintainability is poor. Prioritize refactoring.")

    if maintainability < 70:
        recommendations.append("Code maintainability is moderate. Consider improvements.")

    if lines["comments"] / lines["code"] < 0.1 if lines["code"] > 0 else False:
        recommendations.append("Comment ratio is low (< 10%). Add more documentation.")

    if not recommendations:
        recommendations.append("Code metrics look good! Keep maintaining high quality.")

    return recommendations
