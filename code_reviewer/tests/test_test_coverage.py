"""Tests for test coverage and gap analysis module."""
from __future__ import annotations

from test_coverage import analyze_test_coverage, analyze_assertion_quality, generate_test_stubs_for_gaps


def test_analyze_test_coverage_basic():
    source = """
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
"""
    test_source = """
def test_add():
    assert add(1, 2) == 3
"""
    result = analyze_test_coverage(source, "math.py", test_source)
    assert result["status"] == "success"
    summary = result["summary"]
    assert summary["total_functions"] == 2
    assert summary["covered_functions"] == 1
    assert summary["uncovered_functions"] == 1
    assert summary["coverage_percentage"] == 50.0
    assert len(result["covered"]) == 1
    assert len(result["uncovered"]) == 1
    assert result["uncovered"][0]["name"] == "subtract"


def test_analyze_assertion_quality():
    test_source = """
def test_good():
    assert 1 + 1 == 2

def test_shallow():
    print("no assert here")
"""
    res = analyze_assertion_quality(test_source)
    assert res["status"] == "success"
    assert res["assertion_count"] == 1
    assert len(res["shallow_tests"]) == 1
    assert res["shallow_tests"][0]["test_name"] == "def test_shallow()"


def test_generate_test_stubs_for_gaps():
    source = "def compute(x):\n    return x * 2\n"
    gaps = [{"name": "compute", "line": 1, "type": "function"}]
    res = generate_test_stubs_for_gaps(source, gaps)
    assert "test_stubs" in res
    assert "compute" in res["test_stubs"]
