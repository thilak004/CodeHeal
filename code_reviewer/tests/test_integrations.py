import json

import github_integration


def test_cli_review_mode_is_proposal_only(tmp_path, monkeypatch, capsys):
    source = tmp_path / "sample.py"
    source.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    from cli import main

    assert main([str(source), "--mode", "review_quality"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "valid"


def test_cli_accepts_explicit_provider(tmp_path, monkeypatch, capsys):
    source = tmp_path / "sample.py"
    source.write_text("x = 1\n", encoding="utf-8")
    from cli import main

    assert main([str(source), "--mode", "review_quality", "--provider", "ollama"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "valid"


def test_github_adapter_requires_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = github_integration.fetch_pull_request_diff("owner", "repo", 1)
    assert result["status"] == "unavailable"
    assert result["files"] == []


def test_github_adapter_has_no_write_action():
    result = github_integration.prepare_local_review({"status": "ready", "files": []})
    assert result["status"] == "proposal"
    assert result["approval_required"] is True
    assert result["write_actions"] == "disabled"


def test_cli_tests_mode_text_output(tmp_path, monkeypatch, capsys):
    source = tmp_path / "sample.py"
    source.write_text("def hello(): return 'world'\n", encoding="utf-8")

    class FakeModel:
        def invoke(self, messages):
            return type("Resp", (), {"content": "def test_hello(): assert True\n"})()

    monkeypatch.setattr("providers.ChatGroq", lambda *args, **kwargs: FakeModel())
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    from cli import main

    assert main([str(source), "--mode", "tests", "--output", "text"]) == 0
    out = capsys.readouterr().out
    assert "status: proposal" in out
    assert "def test_hello():" in out

