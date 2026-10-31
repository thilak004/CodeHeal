"""Workspace-root entry point for the AI Code Reviewer."""
import os
import runpy
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parent / "code_reviewer"
os.chdir(_PROJECT_DIR)

runpy.run_path(str(_PROJECT_DIR / "app.py"), run_name="__main__")
