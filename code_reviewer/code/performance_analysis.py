"""Performance analysis for detecting bottlenecks and optimization opportunities."""
from __future__ import annotations

import ast
import re
from typing import Any


def _detect_time_complexity(source: str) -> list[dict[str, Any]]:
    """Detect potential time complexity issues in code."""
    issues = []
    lines = source.splitlines()

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect nested loops (O(n²) or worse)
        loop_count = stripped.count("for ") + stripped.count("while ")
        if loop_count >= 2:
            issues.append({
                "line": line_num,
                "type": "nested_loop",
                "complexity": f"O(n^{loop_count})",
                "severity": "high" if loop_count > 2 else "medium",
                "message": f"Nested loops detected (O(n^{loop_count})). Consider optimization.",
                "suggestion": "Use data structures like sets/dicts for O(1) lookups instead of nested loops",
            })

        # Detect list comprehensions with nested loops (also O(n²))
        if "[" in line and "for " in line and line.count("for ") > 1:
            issues.append({
                "line": line_num,
                "type": "nested_comprehension",
                "complexity": "O(n²)",
                "severity": "medium",
                "message": "Nested list comprehension detected (O(n²))",
                "suggestion": "Consider using generators or breaking into multiple steps",
            })

        # Detect string concatenation in loops (O(n²) in some languages)
        if ("+" in line or "+=" in line) and ("for " in lines[max(0, line_num-5):line_num] or "while " in lines[max(0, line_num-5):line_num]):
            if any(quote in line for quote in ["'", '"']):
                issues.append({
                    "line": line_num,
                    "type": "string_concat_in_loop",
                    "complexity": "O(n²)",
                    "severity": "medium",
                    "message": "String concatenation in loop (inefficient)",
                    "suggestion": "Use list + join() or StringBuilder for better performance",
                })

    return issues


def _detect_memory_issues(source: str) -> list[dict[str, Any]]:
    """Detect potential memory leak patterns and inefficiencies."""
    issues = []
    lines = source.splitlines()

    # Try to parse as Python AST for more accurate analysis
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        tree = None

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect global variables (potential memory bloat)
        if re.match(r"^global\s+\w+", stripped):
            var_name = re.match(r"^global\s+(\w+)", stripped).group(1)
            issues.append({
                "line": line_num,
                "type": "global_variable",
                "severity": "low",
                "message": f"Global variable '{var_name}' detected",
                "suggestion": "Pass as parameters instead to reduce memory footprint",
            })

        # Detect large data structures being copied
        if any(keyword in line for keyword in ["= list(", "= dict(", "= set(", "copy()"]):
            issues.append({
                "line": line_num,
                "type": "data_copy",
                "severity": "medium",
                "message": "Data structure being copied (potentially expensive)",
                "suggestion": "Consider using references or generators to avoid copies",
            })

        # Detect list/dict in loop (potential memory bloat)
        if any(keyword in line for keyword in ["[]", "{}", "list()", "dict()"]):
            if "for " in "".join(lines[max(0, line_num-3):line_num]):
                issues.append({
                    "line": line_num,
                    "type": "allocation_in_loop",
                    "severity": "medium",
                    "message": "Memory allocation in loop",
                    "suggestion": "Allocate outside loop if possible",
                })

    return issues


def _detect_inefficient_algorithms(source: str) -> list[dict[str, Any]]:
    """Detect inefficient algorithm patterns."""
    issues = []
    lines = source.splitlines()

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect linear search in list/array
        if any(method in line for method in [".index(", "in ", "count("]):
            if any(keyword in line for keyword in ["for ", "while "]):
                issues.append({
                    "line": line_num,
                    "type": "linear_search",
                    "complexity": "O(n)",
                    "severity": "medium",
                    "message": "Linear search detected",
                    "suggestion": "Use sets for O(1) lookups or use built-in sorted() + binary search",
                })

        # Detect sorting in loop
        if any(sort_method in line for sort_method in ["sort()", "sorted("]):
            if "for " in "".join(lines[max(0, line_num-3):line_num]) or "while " in "".join(lines[max(0, line_num-3):line_num]):
                issues.append({
                    "line": line_num,
                    "type": "sort_in_loop",
                    "complexity": "O(n² log n)",
                    "severity": "high",
                    "message": "Sorting inside loop (very inefficient)",
                    "suggestion": "Sort once before loop: O(n log n) instead of O(n² log n)",
                })

        # Detect regex in loop (can be slow)
        if "re." in line and any(keyword in "".join(lines[max(0, line_num-5):line_num]) for keyword in ["for ", "while "]):
            issues.append({
                "line": line_num,
                "type": "regex_in_loop",
                "severity": "medium",
                "message": "Regex compilation/matching in loop",
                "suggestion": "Compile regex once before loop: pattern = re.compile(...)",
            })

    return issues


def _detect_database_patterns(source: str) -> list[dict[str, Any]]:
    """Detect inefficient database access patterns."""
    issues = []
    lines = source.splitlines()

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Detect N+1 query pattern
        if any(db_method in line for db_method in [".query(", ".execute(", ".find(", ".get("]):
            if any(keyword in "".join(lines[max(0, line_num-5):line_num]) for keyword in ["for ", "while "]):
                issues.append({
                    "line": line_num,
                    "type": "n_plus_one_query",
                    "severity": "high",
                    "message": "Database query in loop (N+1 problem)",
                    "suggestion": "Use batch queries or JOINs: fetch all data once instead of in loop",
                })

        # Detect missing indexes (patterns)
        if "WHERE" in line.upper() and any(col in line for col in ["id", "user_id", "product_id"]):
            issues.append({
                "line": line_num,
                "type": "potential_missing_index",
                "severity": "medium",
                "message": "Query on column without obvious index",
                "suggestion": "Consider adding index: CREATE INDEX idx_column ON table(column)",
            })

    return issues


def _detect_caching_opportunities(source: str) -> list[dict[str, Any]]:
    """Detect where caching could help."""
    issues = []
    lines = source.splitlines()

    # Look for repeated calculations or lookups
    function_calls = re.findall(r"\b([a-zA-Z_]\w*)\s*\(", source)
    call_counts = {}
    for call in function_calls:
        call_counts[call] = call_counts.get(call, 0) + 1

    for func, count in call_counts.items():
        if count > 3 and func not in ["print", "len", "str", "int", "list", "dict", "range"]:
            issues.append({
                "type": "repeated_function",
                "severity": "low",
                "message": f"Function '{func}' called {count} times (consider caching results)",
                "suggestion": "Use @functools.lru_cache or memoization for expensive calculations",
            })

    return issues


def analyze_performance(source: str, language: str = "python") -> dict[str, Any]:
    """Analyze code for performance bottlenecks and optimization opportunities.

    Detects:
    - Time complexity issues (nested loops, sorting in loops)
    - Memory inefficiencies (unnecessary copies, large allocations)
    - Inefficient algorithms (linear search, regex in loops)
    - Database N+1 queries
    - Caching opportunities
    """

    if language not in ["python", "javascript", "java", "csharp"]:
        return {
            "status": "unsupported",
            "message": f"Performance analysis not supported for {language}",
            "language": language,
        }

    # Collect all issues
    time_complexity_issues = _detect_time_complexity(source)
    memory_issues = _detect_memory_issues(source)
    algorithm_issues = _detect_inefficient_algorithms(source)
    database_issues = _detect_database_patterns(source)
    caching_opportunities = _detect_caching_opportunities(source)

    all_issues = time_complexity_issues + memory_issues + algorithm_issues + database_issues

    # Categorize by severity
    critical = [i for i in all_issues if i.get("severity") == "high"]
    warnings = [i for i in all_issues if i.get("severity") == "medium"]
    info = [i for i in all_issues if i.get("severity") == "low"]

    # Determine status
    if critical:
        status = "critical"
    elif warnings:
        status = "warning"
    elif info or caching_opportunities:
        status = "info"
    else:
        status = "clean"

    return {
        "status": status,
        "language": language,
        "summary": {
            "total_issues": len(all_issues),
            "critical": len(critical),
            "warnings": len(warnings),
            "info": len(info),
            "optimization_opportunities": len(caching_opportunities),
        },
        "issues": {
            "critical": critical,
            "warnings": warnings,
            "info": info,
        },
        "time_complexity_issues": time_complexity_issues,
        "memory_issues": memory_issues,
        "algorithm_issues": algorithm_issues,
        "database_issues": database_issues,
        "caching_opportunities": caching_opportunities,
        "recommendations": _get_performance_recommendations(
            critical, warnings, caching_opportunities, database_issues
        ),
    }


def _get_performance_recommendations(critical: list, warnings: list, caching: list, db_issues: list) -> list[str]:
    """Generate performance optimization recommendations."""
    recommendations = []

    if critical:
        recommendations.append(f"🚨 {len(critical)} critical performance issues found. These need immediate attention.")

    if db_issues:
        n_plus_one = len([i for i in db_issues if i.get("type") == "n_plus_one_query"])
        if n_plus_one:
            recommendations.append(f"🔴 {n_plus_one} N+1 query pattern(s) detected. Use batch queries or JOINs.")

    if warnings:
        recommendations.append(f"⚠️ {len(warnings)} performance warnings. Review nested loops and algorithm choices.")

    if caching:
        recommendations.append(f"💡 {len(caching)} caching opportunities identified. Use memoization for repeated calculations.")

    if not recommendations:
        recommendations.append("✓ Code performance looks good!")

    return recommendations
