"""Test coverage and gap analysis module."""
from __future__ import annotations

import ast
import re
from typing import Any


def analyze_test_coverage(source: str, filename: str = "code.py", test_source: str | None = None) -> dict[str, Any]:
    """Analyze test coverage and identify testing gaps in source code."""
    functions = []
    classes = []
    test_functions = []

    # 1. Extract functions and classes from source code
    if filename.endswith(".py") or "def " in source:
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not node.name.startswith("_") or node.name.startswith("__init__"):
                        functions.append({
                            "name": node.name,
                            "line": node.lineno,
                            "type": "async function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                        })
                elif isinstance(node, ast.ClassDef):
                    classes.append({
                        "name": node.name,
                        "line": node.lineno,
                        "type": "class",
                    })
        except SyntaxError:
            pass

    # Fallback / multi-language regex extraction if AST fails or non-Python
    if not functions:
        func_patterns = [
            r"def\s+([a-zA-Z_]\w*)",  # Python
            r"function\s+([a-zA-Z_]\w*)",  # JS
            r"(?:public|private|protected)?\s*(?:static)?\s*\w+\s+([a-zA-Z_]\w*)\s*\([^)]*\)",  # Java/C#/C++
        ]
        for pattern in func_patterns:
            for match in re.finditer(pattern, source):
                fname = match.group(1)
                if fname not in [f["name"] for f in functions]:
                    functions.append({
                        "name": fname,
                        "line": source[:match.start()].count("\n") + 1,
                        "type": "function",
                    })

    # 2. Extract or check for test functions
    combined_code = source + (("\n" + test_source) if test_source else "")
    test_pattern = r"(?:def|function)\s+(?:test_([a-zA-Z_]\w*)|([a-zA-Z_]\w*_test)|([a-zA-Z_]\w*Test))"
    for match in re.finditer(test_pattern, combined_code):
        tname = match.group(1) or match.group(2) or match.group(3)
        if tname:
            test_functions.append(tname.lower())

    # Also check for explicit test names
    for line in combined_code.splitlines():
        if "test" in line.lower():
            words = re.findall(r"\btest_[a-zA-Z_]\w*\b|[a-zA-Z_]\w*_test\b", line, re.IGNORECASE)
            for w in words:
                clean_w = w.lower().replace("test_", "").replace("_test", "")
                if clean_w and clean_w not in test_functions:
                    test_functions.append(clean_w)

    # 3. Match source functions to tests
    covered_functions = []
    uncovered_functions = []

    for func in functions:
        fname = func["name"].lower()
        is_covered = any(fname in t or t in fname for t in test_functions) or (
            len(test_functions) > 0 and any(
                f"test_{fname}" in combined_code.lower() or f"{fname}_test" in combined_code.lower() for f in [fname]
            )
        )

        if is_covered:
            covered_functions.append(func)
        else:
            uncovered_functions.append(func)

    total_funcs = len(functions)
    covered_count = len(covered_functions)
    coverage_percentage = round((covered_count / total_funcs * 100) if total_funcs > 0 else 100.0, 1)

    # 4. Generate recommendations & test stubs
    recommendations = []
    if uncovered_functions:
        recommendations.append(f"⚠️ {len(uncovered_functions)} function(s) lack detected unit tests.")
        for unf in uncovered_functions:
            recommendations.append(f"   - Add unit test for `{unf['name']}` (line {unf['line']}).")
    else:
        recommendations.append("✓ All detected functions have corresponding test coverage!")

    if coverage_percentage < 80:
        recommendations.append("💡 Aim for at least 80% test coverage across critical business logic.")
    else:
        recommendations.append("🌟 Excellent test coverage ratio!")

    return {
        "status": "success",
        "summary": {
            "total_functions": total_funcs,
            "covered_functions": covered_count,
            "uncovered_functions": len(uncovered_functions),
            "coverage_percentage": coverage_percentage,
        },
        "functions": functions,
        "covered": covered_functions,
        "uncovered": uncovered_functions,
        "test_functions_found": test_functions,
        "recommendations": recommendations,
    }


def analyze_assertion_quality(test_source: str) -> dict[str, Any]:
    """Inspect test source code for assertion quality and shallow tests (Mutation/Assertion check)."""
    if not test_source or not test_source.strip():
        return {
            "status": "no_tests",
            "message": "No test suite provided for assertion quality analysis.",
            "assertion_count": 0,
            "shallow_tests": [],
            "assertion_quality_score": 0.0,
        }

    # Blank out string literals and comments to avoid false positive assertion counts
    cleaned_test_source = test_source
    try:
        from multilang import _blank_literals_and_comments
        cleaned_test_source = _blank_literals_and_comments(test_source, "python")
    except Exception:
        pass

    lines = cleaned_test_source.splitlines()
    test_blocks = []
    current_test = None
    current_lines = []
    assertion_count = 0
    shallow_tests = []

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("def test_") or stripped.startswith("function test_"):
            if current_test:
                test_blocks.append((current_test, current_lines))
            current_test = stripped.rstrip(":")
            current_lines = [(line_num, line)]
        elif current_test:
            current_lines.append((line_num, line))

    if current_test:
        test_blocks.append((current_test, current_lines))

    if not test_blocks and ("def " in test_source or "function " in test_source):
        test_blocks = [("custom_test_suite", [(i + 1, l) for i, l in enumerate(lines)])]

    for tname, tlines in test_blocks:
        t_text = "\n".join(l[1] for l in tlines)
        asserts = len(re.findall(r"\bassert\b|\bself\.assert|expect\(|should", t_text))
        assertion_count += asserts
        if asserts == 0:
            shallow_tests.append({
                "test_name": tname,
                "line": tlines[0][0] if tlines else 1,
                "issue": "Shallow test: contains no assertions or expectations.",
            })

    quality_score = 100.0
    if test_blocks:
        quality_score = round(max(0.0, (len(test_blocks) - len(shallow_tests)) / len(test_blocks) * 100.0), 1)

    return {
        "status": "success",
        "total_test_functions": len(test_blocks),
        "assertion_count": assertion_count,
        "shallow_tests": shallow_tests,
        "assertion_quality_score": quality_score,
        "recommendations": [
            f"✓ Found {assertion_count} assertions across {len(test_blocks)} test functions.",
            *( [f"⚠️ Test `{st['test_name']}` (line {st['line']}) lacks assertions." for st in shallow_tests] if shallow_tests else ["🌟 All test functions include robust assertions."] )
        ],
    }


def generate_test_stubs_for_gaps(source: str, uncovered_funcs: list[dict], provider_name: str | None = None) -> dict[str, Any]:
    """Generate AI test stubs for uncovered functions."""
    try:
        from agent import _strip_markdown
        from prompts import TEST_GENERATION_PROMPT
        from providers import create_provider
        from tools import check_source_size

        size_ok, size_message = check_source_size(source)
        if not size_ok:
            return {"status": "failed", "error": size_message}

        target_names = [f["name"] for f in uncovered_funcs]
        prompt_text = f"Generate robust pytest unit tests specifically covering these uncovered functions: {', '.join(target_names)}.\n\nSource code:\n{source}"

        provider = create_provider(provider_name)
        response = provider.invoke(TEST_GENERATION_PROMPT.format_messages(code=prompt_text))
        raw = getattr(response, "content", "")
        candidate = _strip_markdown(raw if isinstance(raw, str) else str(raw), "python")

        return {
            "status": "success",
            "test_stubs": candidate,
            "target_functions": target_names,
        }
    except Exception as exc:
        fallback_stubs = "\n\n".join(f"def test_{f['name']}():\n    # TODO: implement test for {f['name']}\n    assert True\n" for f in uncovered_funcs)
        return {
            "status": "unavailable",
            "error": str(exc),
            "test_stubs": f"# Automated test stubs fallback due to error: {exc}\n\n{fallback_stubs}",
            "target_functions": [f["name"] for f in uncovered_funcs],
        }
