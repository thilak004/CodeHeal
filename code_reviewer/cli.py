"""Entry point for the CLI from code_reviewer directory."""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent / "code"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

if __name__ == "__main__":
    from cli import main

    raise SystemExit(main())

