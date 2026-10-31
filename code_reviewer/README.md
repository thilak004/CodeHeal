# AI Code Reviewer

A safety-first multi-language code reviewer and fixer built with Streamlit, Groq, Ollama, Claude, language-aware static checks, and Python's AST parser.

## Features

- Paste source code or upload a UTF-8 file up to 512 KB.
- Review Python, JavaScript, Java, C, C++, and C#.
- Detect the language from the file extension and run a language-appropriate static checker without importing or executing submitted code.
- Generate bounded, AST-validated syntax-fix proposals with retry feedback.
- Generate syntax-fix proposals for every supported language, not only Python, and keep the corrected file in its original language and extension.
- Reject a proposal written in a different language, for every supported language, so the corrected code always corresponds to the uploaded code.
- Compare original and proposed source with a unified diff.
- Run Ruff against original and proposed source.
- Show deterministic security findings for risky Python patterns.
- Review valid code in quality, security, refactor, and type-hint modes.
- AI Code Detector: Calculate AI vs Human probability with multi-signal stylometry (line burstiness, comment redundancy, generic identifier distribution, structural uniformity).
- Visual Line-by-Line Heatmap: Highlight AI-templated code lines vs natural human lines with forensic explanations.
- One-Click Code Humanizer: Refactor robotic, over-commented AI code into natural, idiomatic human style with live diff review.
- Calculate an explainable quality score without inventing unavailable checks.
- Ask for an optional detailed explanation after a proposal is validated.
- Require explicit approval before a fix becomes applied or downloadable.
- Generate pytest source as an unapproved proposal; generated tests are never run automatically.
- Inspect project ZIP manifests with archive size, file count, path traversal, and symlink protection.
- Store review metadata in local SQLite history with JSON export and delete/clear controls.
- Report sandbox availability explicitly; test execution is disabled by default and is not a security boundary.
- Select Groq, Ollama, or Claude explicitly through `LLM_PROVIDER`.
- Review project ZIP files across supported languages; unsafe paths and symlinks are rejected.
- Ask questions about the current file or request approved-only fix, refactor, type-hint, test, and completion proposals.
- Optionally fetch GitHub pull-request file patches in read-only mode; remote comments and pushes are not implemented.

## Architecture: generate → validate → review → approve

1. **Generate** — deterministic syntax checks run first. Only invalid source is sent to the explicitly selected provider for a bounded fix loop.
2. **Validate** — each provider response is checked for empty output, prose, markdown fences, the requested language, and valid syntax for that language. A proven error (an unbalanced delimiter, for example) rejects the proposal; a heuristic warning is reported to the reviewer but does not block the proposal.
3. **Review** — Ruff, security checks, quality scoring, and optional AI findings run without executing reviewed source.
4. **Approve** — a user reviews the original, proposal, and diff, then explicitly approves before download.

A proposal for one language is rejected when the provider returns another language, so a C++ upload cannot be answered with Python. The corrected file keeps the uploaded name and extension, for example `corrected_student.cpp`.

The language check is a family-aware fingerprint guard in `code/fingerprints.py`. It scores every supported language against the candidate and reports a mismatch only when the foreign language is clearly present and clearly stronger than the requested one, so ordinary source is never rejected by mistake. Close siblings are treated symmetrically: plain C stays valid for a C++ upload and plain JavaScript stays valid for a TypeScript upload, while the reverse direction is rejected.

The guard is applied on every path that can produce source: the syntax-fix loop, the conversational assistant's code proposals, the CLI, and the API. A proposal in the wrong language is rejected before it is shown, so the corrected code always corresponds to the uploaded code, and the corrected file keeps the uploaded name and extension.

A syntax-valid proposal is not proof of behavioral correctness. The app never imports submitted code and never executes generated code as part of normal review.

## Language validation

Each language is checked by its own tool when it is installed: `node`, `tsc`, `javac`, `gofmt`, `rustc`, `php -l`, `dotnet`, `clang`, and `clang++`. When a tool is missing, the built-in fallback runs instead and reports what it can prove. The fallback never executes the submitted source.

The fallback separates two kinds of finding. An **error** is a proven defect, such as an unbalanced delimiter, and it rejects a proposal. A **warning** is a heuristic, such as a possible missing semicolon, and it is shown to the reviewer without blocking the proposal. This distinction matters most for the languages whose only checker is a heuristic: C, C++, Java, C#, Rust, and PHP. Go is exempt from the semicolon heuristic because its statements are terminated by a newline.

The fallback also understands the shapes that ordinary source uses: a parameter list split over several lines, a statement continued on the next line, a forward declaration, and a brace inside a string literal or a comment. None of these is reported as a defect.

## Setup and run

When the `auto code fixer` workspace folder is open in VS Code, its Python
interpreter is set to the project virtual environment. Install dependencies if
needed, then run the app from the workspace root:

```powershell
code_reviewer\.venv\Scripts\python.exe -m pip install -r code_reviewer\requirements.txt
streamlit run app.py
```

The root `app.py` forwards to the application in `code_reviewer` while keeping
that folder as the working directory. This preserves the app's `.env` and
review-history paths.

To run from inside `code_reviewer` instead:

```bash
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
streamlit run app.py
```

Python 3.9+ is supported. On Windows PowerShell, use `./.venv/Scripts/Activate.ps1` if script execution policy permits it, or invoke `.venv/Scripts/python.exe` directly.

## Configuration

Copy `.env.example` to `.env` and set only the provider you intend to use:

- `LLM_PROVIDER=groq`, `LLM_PROVIDER=ollama`, or `LLM_PROVIDER=claude`.
- `GROQ_API_KEY` and optional `GROQ_MODEL` for Groq.
- `OLLAMA_URL` and `OLLAMA_MODEL` for a local Ollama server.
- `ANTHROPIC_API_KEY`, optional `ANTHROPIC_MODEL`, and `ANTHROPIC_MAX_TOKENS` for Claude through the official Anthropic Python SDK.
- `REVIEW_HISTORY_DB` for the SQLite metadata path.
- `ENABLE_TEST_RUNNER=true` only when an external isolation boundary is configured.
- `TEST_RUNNER_ISOLATED=true` is required on Windows before the bounded runner can start.
- `GITHUB_TOKEN` is read only by the optional read-only PR adapter; it is never stored in history.

Credentials are read from environment variables and are not written to review history. Static modes work without an AI key; AI-backed modes report an explicit unavailable state.

## Optional CLI and API

Run the proposal-only CLI from the project root:

```bash
.venv\\Scripts\\python.exe -m cli path\\to\\file.py --mode review_quality
.venv\\Scripts\\python.exe -m cli path\\to\\file.py --mode fix_syntax --output json
```

The CLI prints proposals and review metadata; it never writes back to the input file.

The optional FastAPI adapter is in `code/api.py`. Install the requirements, then start it from the project root:

```bash
.venv\\Scripts\\python.exe -m uvicorn api:app --app-dir code --host 127.0.0.1 --port 8000
```

The API exposes `/health` and proposal-only `POST /review`. It has no remote code-runner or apply endpoint. Add authentication and network controls before exposing it beyond localhost.

The optional `code/github_integration.py` adapter fetches pull-request file patches only. It does not post comments, push commits, or apply remote changes.

## Tests and checks

```bash
.venv\\Scripts\\python.exe -m pytest -q
.venv\\Scripts\\python.exe -m compileall -q code tests
.venv\\Scripts\\python.exe -m ruff check code tests
```

Tests mock provider and subprocess boundaries. They do not use real credentials or network calls.

## Project structure

```text
code_reviewer/
├── code/
│   ├── app.py                # Streamlit UI, modes, upload, approval, history
│   ├── languages.py          # Supported extensions and language detection
│   ├── multilang.py          # Safe language-aware static validation
│   ├── fingerprints.py       # Cross-language proposal guard
│   ├── agent.py              # AST-gated syntax-fix proposal loop
│   ├── providers.py          # Explicit Groq/Ollama/Claude provider boundary
│   ├── assistant.py          # Conversational, proposal-oriented coding assistant
│   ├── review.py             # Quality, security, refactor, type-hint, and test modes
│   ├── security.py           # Static defensive AST findings
│   ├── quality.py            # Explainable score calculation
│   ├── history.py            # Parameterized SQLite metadata store
│   ├── project.py            # Safe ZIP metadata inspection
│   ├── sandbox.py            # Opt-in bounded pytest runner
│   ├── cli.py                # Proposal-only command-line interface
│   ├── api.py                # Optional FastAPI proposal API
│   ├── github_integration.py # Read-only pull-request patch adapter
│   ├── tools.py              # AST, Ruff, validation, and diff helpers
│   └── prompts.py            # Provider prompt templates
├── tests/
├── requirements.txt
├── .env.example
└── README.md
```

No IDE package is bundled into the Streamlit application. An IDE client can call the local proposal API and must apply only user-approved patches.
