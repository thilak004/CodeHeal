# AI Code Reviewer

A safety-first code review and fix-proposal app for Python, JavaScript, Java, C, C++, and C#. Review code in a Streamlit UI or use the optional command-line and API interfaces.

## Features

- Review pasted code, uploaded files, and project ZIP archives.
- Generate syntax-fix proposals and inspect them in a unified diff before approving or downloading.
- Run language-aware static validation, Ruff, quality checks, and defensive security checks without executing submitted code during normal review.
- Choose Groq, Ollama, or Claude for AI-assisted features; static review modes work without an AI provider.
- Store review metadata locally in SQLite. Raw source and credentials are not stored in review history.
- Optionally inspect GitHub pull-request patches in read-only mode.

## Quick start

Requires Python 3.9 or newer.

From the repository root, install the dependencies and create your local environment file:

```powershell
python -m venv code_reviewer\.venv
code_reviewer\.venv\Scripts\python.exe -m pip install -r code_reviewer\requirements.txt
Copy-Item code_reviewer\.env.example code_reviewer\.env
```

Set `LLM_PROVIDER` and the matching provider credentials in `code_reviewer\.env` if you want AI-assisted features. Then start the app:

```powershell
code_reviewer\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL printed by Streamlit. Static review features are available without provider credentials.

## Configuration

Set `LLM_PROVIDER` to `groq`, `ollama`, or `claude` in `code_reviewer/.env`, then configure the matching settings:

- Groq: `GROQ_API_KEY` and optional `GROQ_MODEL`
- Ollama: `OLLAMA_URL` and `OLLAMA_MODEL`
- Claude: `ANTHROPIC_API_KEY` and optional `ANTHROPIC_MODEL` / `ANTHROPIC_MAX_TOKENS`

See [`code_reviewer/.env.example`](code_reviewer/.env.example) for all available options, including upload limits and optional API and test-runner settings. Keep `.env` files and tokens private; they are excluded from Git.

## Safety notes

Normal review does not import or execute submitted code. A generated fix remains a proposal until you review and approve it. Test execution is disabled by default; enabling it requires a separately configured isolation boundary and should not be treated as safe for untrusted code otherwise.

The optional API should be bound to localhost unless you have configured authentication and appropriate network controls. The GitHub integration only reads pull-request patches; it does not post comments or push changes.

## Tests

Run the test suite from the repository root:

```powershell
code_reviewer\.venv\Scripts\python.exe -m pytest -q code_reviewer\tests
```

## Documentation

For detailed architecture, validation behavior, CLI and API usage, and the full project structure, see [`code_reviewer/README.md`](code_reviewer/README.md).
