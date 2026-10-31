"""Defensive, deterministic security checks that never execute reviewed code."""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from typing import Any

SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|private[_-]?key)\s*=[\s\"']+[^\s\"']{8,}"
)


def _finding(code: str, message: str, node: ast.AST, severity: str = "medium") -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "line": int(getattr(node, "lineno", 0) or 0),
        "confidence": "medium",
        "suggestion": "Review this pattern and replace it with a safer, least-privilege alternative.",
    }


def _bandit_finding(issue: dict[str, Any]) -> dict[str, Any]:
    """Convert a Bandit issue to the normalized finding schema."""
    severity_map = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    confidence_map = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    return {
        "severity": severity_map.get(str(issue.get("severity", "")).upper(), "medium"),
        "code": f"BANDIT-{issue.get('test_id', 'UNKNOWN')}",
        "message": str(issue.get("issue_text", "Bandit finding")),
        "line": int(issue.get("line_number", 0) or 0),
        "confidence": confidence_map.get(str(issue.get("confidence", "")).upper(), "low"),
        "suggestion": str(issue.get("more_info", "Review this pattern and replace it with a safer, least-privilege alternative.")),
    }


def _run_bandit(source: str) -> list[dict[str, Any]]:
    """Run Bandit on the source and return normalized findings."""
    if shutil.which("bandit") is None:
        return []
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "bandit", "-f", "json", "-"],
            input=source,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode == 0:
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    results = payload.get("results", [])
    if not isinstance(results, list):
        return []
    return [_bandit_finding(issue) for issue in results if isinstance(issue, dict)]


def scan_security(source: str) -> list[dict[str, Any]]:
    """Return conservative findings for common risky Python constructs."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError):
        return []

    findings: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "eval":
                findings.append(_finding("SEC001", "Dynamic eval() can execute attacker-controlled code.", node, "high"))
            elif node.func.id == "exec":
                findings.append(_finding("SEC002", "Dynamic exec() can execute attacker-controlled code.", node, "high"))
            elif node.func.id in {"pickle", "loads"}:
                findings.append(_finding("SEC003", "Deserialization may be unsafe for untrusted input.", node))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "subprocess":
                for keyword in node.keywords:
                    if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                        findings.append(_finding("SEC004", "shell=True increases command-injection risk.", node, "high"))
            if node.func.attr in {"md5", "sha1"}:
                findings.append(_finding("SEC005", f"Weak hash {node.func.attr} is not suitable for security decisions.", node))
        if isinstance(node, ast.Assign):
            text = ast.get_source_segment(source, node) or ""
            if SECRET_PATTERN.search(text):
                findings.append(_finding("SEC006", "Possible hardcoded secret detected.", node, "high"))

    findings.extend(_run_bandit(source))
    return findings
