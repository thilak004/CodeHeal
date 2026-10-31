"""Unit tests for the AI Code Detector and Humanizer."""
from __future__ import annotations

import json
from detector import detect_ai_code, humanize_code


AI_SAMPLE = """# Initialize the result variable
result = []
# Loop through the items in the input list
for item in data:
    # Check if the item is valid
    if item > 0:
        # Append the item to the result
        result.append(item)
# Return the final result
return result
"""

HUMAN_SAMPLE = """def parse_config(cfg_path):
    with open(cfg_path, "r", encoding="utf-8") as raw:
        return {k.strip(): v.strip() for k, v in (l.split("=", 1) for l in raw if "=" in l)}
"""


def test_ai_detector_identifies_heavy_ai_patterns():
    res = detect_ai_code(AI_SAMPLE, "process.py")
    assert res["status"] == "ready"
    assert res["ai_probability"] >= 60
    assert res["verdict"] == "Likely AI-Generated"
    assert res["flagged_lines_count"] > 0
    assert "comment_redundancy" in res["signals"]
    assert len(res["line_analysis"]) == len(AI_SAMPLE.splitlines())


def test_ai_detector_rates_clean_human_code():
    res = detect_ai_code(HUMAN_SAMPLE, "parser.py")
    assert res["status"] == "ready"
    assert res["ai_probability"] < 50
    assert res["verdict"] in {"Likely Human-Written", "Mixed / AI-Assisted"}


def test_ai_detector_handles_empty_source():
    res = detect_ai_code("", "empty.py")
    assert res["status"] == "failed"
    assert "empty" in res["error"].lower()


def test_humanize_code_creates_proposal(monkeypatch):
    class FakeModel:
        def invoke(self, messages):
            return type("Resp", (), {"content": "def filter_positive(vals):\n    return [x for x in vals if x > 0]\n"})()

    monkeypatch.setattr("providers.ChatGroq", lambda *args, **kwargs: FakeModel())
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    res = humanize_code(AI_SAMPLE, "clean.py")
    assert res["status"] == "proposal"
    assert "def filter_positive" in res["humanized_code"]
    assert "--- clean.py" in res["diff"]


def test_cli_ai_detector_mode(tmp_path, capsys):
    from cli import main

    file_path = tmp_path / "sample.py"
    file_path.write_text(AI_SAMPLE, encoding="utf-8")

    assert main([str(file_path), "--mode", "ai_detector", "--output", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "ready"
    assert "ai_probability" in out

