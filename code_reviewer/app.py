"""Entry point so the project can be started with: streamlit run app.py"""
import runpy
import sys
from pathlib import Path

_APP_DIR = Path(__file__).resolve().parent / "code"
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

runpy.run_path(str(_APP_DIR / "app.py"), run_name="__main__")
