"""Opt-in, bounded subprocess runner for generated tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_OUTPUT_BYTES = 64 * 1024


def run_pytest_sandbox(
    project_dir: str | Path,
    timeout_seconds: int = 10,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Run an allowlisted pytest command only when explicitly enabled.

    This is a bounded subprocess, not a full security sandbox. On Windows,
    callers should keep it disabled unless an external container is configured.
    """
    allowed = enabled if enabled is not None else os.getenv("ENABLE_TEST_RUNNER", "false").lower() == "true"
    if not allowed:
        return {"status": "unavailable", "message": "Test execution is disabled by default.", "stdout": "", "stderr": ""}
    if os.name == "nt" and os.getenv("TEST_RUNNER_ISOLATED", "false").lower() != "true":
        return {"status": "unavailable", "message": "Windows test execution requires an explicitly configured isolated runner.", "stdout": "", "stderr": ""}

    runner_env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": ""}
    if os.name == "nt":
        for var in ("SystemRoot", "SYSTEMROOT", "SystemDrive", "TEMP", "TMP"):
            if var in os.environ:
                runner_env[var] = os.environ[var]

    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(Path(project_dir).resolve()),
            capture_output=True,
            text=True,
            timeout=max(1, min(int(timeout_seconds), 60)),
            shell=False,
            check=False,
            env=runner_env,
        )
    except subprocess.TimeoutExpired as exc:
        return {"status": "timeout", "message": "Test execution timed out.", "stdout": str(exc.stdout or "")[:MAX_OUTPUT_BYTES], "stderr": str(exc.stderr or "")[:MAX_OUTPUT_BYTES]}
    except OSError as exc:
        return {"status": "error", "message": f"Test runner could not start: {exc}", "stdout": "", "stderr": ""}

    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "message": "Tests passed." if completed.returncode == 0 else "Tests failed.",
        "stdout": (completed.stdout or "")[:MAX_OUTPUT_BYTES],
        "stderr": (completed.stderr or "")[:MAX_OUTPUT_BYTES],
    }
