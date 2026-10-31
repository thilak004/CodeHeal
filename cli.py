"""Workspace-root entry point for the CLI."""
import sys
from pathlib import Path

_CODE_DIR = Path(__file__).resolve().parent / "code_reviewer" / "code"
if str(_CODE_DIR) not in sys.path:
    sys.path.insert(0, str(_CODE_DIR))

if __name__ == "__main__":
    from cli import main

    raise SystemExit(main())

