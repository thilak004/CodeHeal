"""Streamlit interface for the AI Code Reviewer."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from agent import explain_proposal, fix_code
from assistant import ask_assistant
from detector import detect_ai_code, humanize_code
from github_integration import fetch_pull_request_diff, prepare_local_review
from history import clear_history, delete_review, list_reviews, save_review
from languages import detect_language, language_label, streamlit_language
from project import analyze_project_zip, inspect_project_zip, read_project_context
from review import review_source
from sandbox import run_pytest_sandbox
from test_generation import generate_tests
from tools import run_ruff

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

st.set_page_config(page_title="AI Code Reviewer", layout="wide", page_icon=":material/bug_report:")

MAX_UPLOAD_BYTES = 512 * 1024
HISTORY_PATH = Path(os.getenv("REVIEW_HISTORY_DB", ".review_history.sqlite3"))


def _safe_filename(filename: str) -> str:
    basename = Path(filename or "code.py").name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", basename)
    return safe or "code.py"


def _initialise_state() -> None:
    st.session_state.setdefault(
        "input_code",
        'def greet(name):\n    if name == "World"\n        print("Hello, World!")\n    else:\n        print(f"Hello, {name}")\n',
    )
    st.session_state.setdefault("source_filename", "code.py")
    st.session_state.setdefault("review_result", None)
    st.session_state.setdefault("approved_code", None)
    st.session_state.setdefault("approved_identity", None)
    st.session_state.setdefault("upload_identity", None)
    st.session_state.setdefault("mode_result", None)
    st.session_state.setdefault("test_result", None)
    st.session_state.setdefault("project_result", None)
    st.session_state.setdefault("sandbox_result", None)
    st.session_state.setdefault("explanation_requested", False)
    st.session_state.setdefault("provider_name", os.getenv("LLM_PROVIDER", "groq").lower())
    st.session_state.setdefault("assistant_result", None)
    st.session_state.setdefault("assistant_action", "question")
    st.session_state.setdefault("assistant_request", "")
    st.session_state.setdefault("assistant_context", "")
    st.session_state.setdefault("assistant_project_zip", None)
    st.session_state.setdefault("assistant_project_manifest", None)
    st.session_state.setdefault("assistant_selected_files", [])
    st.session_state.setdefault("assistant_approved_identity", None)
    st.session_state.setdefault("assistant_source_identity", None)
    st.session_state.setdefault("detector_result", None)
    st.session_state.setdefault("humanize_result", None)


def _show_ruff_report(title: str, report: dict | None) -> None:
    st.subheader(title)
    if not isinstance(report, dict):
        report = {}
    status = report.get("status")
    if status == "clean":
        st.success(report.get("message", "No Ruff issues found."), icon=":material/check_circle:")
    elif status in {"unavailable", "error", "not_run"}:
        st.warning(report.get("message", "Ruff analysis was unavailable."), icon=":material/warning:")
    else:
        st.warning(report.get("message", "Ruff found issues."), icon=":material/report:")
        findings = report.get("findings", [])
        if findings:
            st.dataframe(
                [
                    {
                        "code": item.get("code"),
                        "message": item.get("message"),
                        "line": item.get("line"),
                        "column": item.get("column"),
                        "fixable": item.get("fixable"),
                    }
                    for item in findings
                ],
                hide_index=True,
                width="stretch",
            )


def _show_score(score: dict | None) -> None:
    if not isinstance(score, dict):
        score = {}
    value = score.get("score")
    if value is None:
        st.info("Quality score is not available because no scoreable checks completed.")
    else:
        st.metric("Quality score", f"{value}/100", score.get("label", ""))
    components = score.get("components", {})
    if components:
        st.dataframe(
            [{"check": key, "score": value if value is not None else "unknown"} for key, value in components.items()],
            hide_index=True,
            width="stretch",
        )


def _show_findings(findings: list[dict]) -> None:
    if not findings:
        st.success("No deterministic findings were reported.")
        return
    st.dataframe(
        [
            {
                "severity": item.get("severity"),
                "code": item.get("code"),
                "line": item.get("line"),
                "message": item.get("message"),
                "suggestion": item.get("suggestion"),
            }
            for item in findings
        ],
        hide_index=True,
        width="stretch",
    )


def _save_history(filename: str, mode: str, source: str, result: dict) -> None:
    score = result.get("score")
    score_value = score.get("score") if isinstance(score, dict) else None
    try:
        save_review(
            HISTORY_PATH,
            {
                "filename": filename,
                "mode": mode,
                "source": source,
                "proposal_hash": result.get("proposal_id"),
                "status": result.get("state", result.get("status", "unknown")),
                "score": score_value,
                "approved": False,
                "findings": result.get("findings", []),
            },
        )
    except (OSError, TypeError, ValueError) as exc:
        st.warning(f"Review completed, but history could not be saved: {exc}")


def _apply_assistant_proposal(proposal: str, proposal_identity: str) -> None:
    """Update the editor from a button callback before keyed widgets render again."""
    st.session_state["input_code"] = proposal
    st.session_state["assistant_approved_identity"] = proposal_identity
    st.session_state["assistant_source_identity"] = proposal_identity
    st.session_state["assistant_result"] = None


def _health_panel(result: dict) -> None:
    """Show a unified correction/review health panel."""
    st.subheader("Health panel")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Syntax", "OK" if result.get("syntax_ok") else "Needs fix")
    c2.metric("Candidate", "Valid" if result.get("candidate_valid") else "—")
    ruff = result.get("ruff") or {}
    ruff_status = ruff.get("status", "not_run")
    c3.metric("Ruff", ruff_status.capitalize())
    security_count = len(result.get("findings", []) or [])
    c4.metric("Findings", security_count)
    _show_score(result.get("score") or {})


_initialise_state()
st.title("AI Code Reviewer")

with st.sidebar:
    st.header("Settings")
    provider_options = ["groq", "ollama", "claude"]
    current_provider = st.session_state["provider_name"] if st.session_state["provider_name"] in provider_options else "groq"
    provider_name = st.selectbox("AI provider", options=provider_options, index=provider_options.index(current_provider))
    st.session_state["provider_name"] = provider_name

MODE_LABELS = {
    "fix_syntax": "Fix syntax",
    "ai_detector": "AI Code Detector",
    "assistant": "Assistant",
    "review_quality": "Quality review",
    "security": "Security review",
    "refactor": "Refactor",
    "type_hints": "Type hints",
    "tests": "Generate tests",
    "project": "Project ZIP",
    "github_pr": "GitHub PR",
    "history": "History",
}

mode = st.selectbox(
    "Mode",
    options=list(MODE_LABELS),
    format_func=MODE_LABELS.get,
)

if mode == "history":
    st.header("Review history")
    try:
        rows = list_reviews(HISTORY_PATH)
    except OSError as exc:
        st.error(f"History is unavailable: {exc}")
        rows = []
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
        st.download_button(
            "Download history JSON",
            data=json.dumps(rows, indent=2),
            file_name="review-history.json",
            mime="application/json",
            width="stretch",
        )
        delete_id = st.number_input("Review ID to delete", min_value=1, step=1, value=rows[0]["id"])
        if st.button("Delete selected review"):
            delete_review(HISTORY_PATH, int(delete_id))
            st.rerun()
    else:
        st.info("No reviews have been saved yet.")
    if st.button("Clear history"):
        clear_history(HISTORY_PATH)
        st.rerun()
    st.stop()

# Filter extensions to only show requested ones
supported_extensions = [".c", ".cc", ".cpp", ".cxx", ".hpp", ".cs", ".java", ".js", ".jsx", ".py"]
uploaded_file = st.file_uploader(
    "Upload a source file",
    type=[extension.lstrip(".") for extension in supported_extensions],
    help="Supported: C, C++, C#, Java, JavaScript, Python.",
)
if uploaded_file is not None:
    uploaded_bytes = uploaded_file.getvalue()
    upload_id = hashlib.sha256(uploaded_bytes).hexdigest()
    if st.session_state["upload_identity"] != upload_id:
        if uploaded_file.size > MAX_UPLOAD_BYTES:
            st.error("The uploaded file is too large. Please upload a file under 512 KB.")
        else:
            try:
                uploaded_code = uploaded_bytes.decode("utf-8")
            except UnicodeDecodeError:
                st.error("The uploaded file must be UTF-8 encoded.")
            else:
                uploaded_filename = _safe_filename(uploaded_file.name)
                if detect_language(uploaded_filename) is None:
                    st.error("That file type is not supported yet. Upload one of the listed source formats.")
                else:
                    st.session_state.update(
                        input_code=uploaded_code,
                        source_filename=uploaded_filename,
                        review_result=None,
                        approved_code=None,
                        approved_identity=None,
                        upload_identity=upload_id,
                        mode_result=None,
                        test_result=None,
                        sandbox_result=None,
                        detector_result=None,
                        humanize_result=None,
                    )
                    st.rerun()

if mode == "ai_detector":
    st.header("AI Code Detector")
    st.caption("Forensic detection of AI-generated vs human-written code using burstiness, stylometry, and comment redundancy analysis.")
    st.text_input("Filename", key="source_filename")
    detector_language = detect_language(st.session_state["source_filename"])
    st.caption(f"Detected language: {language_label(detector_language)}")
    st.text_area("Source code to analyze", key="input_code", height=320)

    col_btn1, col_btn2 = st.columns([1, 1])
    with col_btn1:
        scan_clicked = st.button("Analyze with AI Detector", type="primary", use_container_width=True)
    with col_btn2:
        humanize_clicked = st.button("Humanize Code (Remove AI Markers)", type="secondary", use_container_width=True)

    if scan_clicked:
        with st.spinner("Analyzing code entropy, burstiness, and stylometric patterns..."):
            st.session_state["detector_result"] = detect_ai_code(
                st.session_state["input_code"],
                filename=_safe_filename(st.session_state["source_filename"]),
            )
            st.session_state["humanize_result"] = None

    if humanize_clicked:
        with st.spinner("Refactoring code to natural, idiomatic human style..."):
            st.session_state["humanize_result"] = humanize_code(
                st.session_state["input_code"],
                filename=_safe_filename(st.session_state["source_filename"]),
                provider_name=provider_name,
            )

    det_result = st.session_state.get("detector_result")
    if det_result:
        if det_result.get("status") == "ready":
            st.divider()
            ai_pct = det_result["ai_probability"]
            human_pct = det_result["human_probability"]
            verdict = det_result["verdict"]

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("AI-Generated Probability", f"{ai_pct}%")
            m2.metric("Human-Written Probability", f"{human_pct}%")
            m3.metric("Verdict", verdict)
            m4.metric("Flagged AI Lines", f"{det_result['flagged_lines_count']} / {det_result['total_lines']}")

            if ai_pct >= 65:
                st.error(f"**Verdict:** {verdict} ({ai_pct}% probability). This code exhibits strong patterns typical of LLM generation (uniform line burstiness, textbook comments, or generic identifier naming).")
            elif ai_pct <= 35:
                st.success(f"**Verdict:** {verdict} ({human_pct}% probability). Code shows natural structural variation, domain-specific naming, and organic formatting.")
            else:
                st.warning(f"**Verdict:** {verdict} ({ai_pct}% AI / {human_pct}% Human). Mix of human-crafted and automated/templated sections.")

            st.subheader("Stylometric & Forensic Signals")
            sig = det_result["signals"]
            s1, s2, s3, s4 = st.columns(4)
            s1.progress(sig["comment_redundancy"] / 100, text=f"Comment Redundancy: {sig['comment_redundancy']}%")
            s2.progress(sig["generic_naming"] / 100, text=f"Generic Identifiers: {sig['generic_naming']}%")
            s3.progress(sig["line_uniformity"] / 100, text=f"Line Uniformity: {sig['line_uniformity']}%")
            s4.progress(sig["structural_consistency"] / 100, text=f"Structural Uniformity: {sig['structural_consistency']}%")

            with st.expander("Detector Forensic Analysis", expanded=True):
                st.markdown(det_result["explanation"])

            st.subheader("Line-by-Line AI Probability Heatmap")
            st.caption("Lines highlighted in red/orange have high AI probability; yellow indicates mixed/uncertain; unhighlighted lines appear human-written.")

            heatmap_html = ['<div style="font-family: monospace; font-size: 13px; line-height: 1.5; border: 1px solid #30363d; border-radius: 6px; padding: 12px; background-color: #0e1117; color: #e6edf3; overflow-x: auto;">']
            for item in det_result["line_analysis"]:
                line_no = item["line_number"]
                code_text = item["code"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(" ", "&nbsp;")
                if not code_text:
                    code_text = "&nbsp;"
                prob = item["ai_probability"]
                cls = item["classification"]
                reasons = " | ".join(item["reasons"]) if item["reasons"] else ""
                title_attr = f'title="Line {line_no} ({prob}% AI) - {reasons}"' if reasons else f'title="Line {line_no} ({prob}% AI)"'

                if cls == "ai":
                    bg = "background-color: rgba(255, 68, 68, 0.28); border-left: 4px solid #ff4444;"
                    badge = f'<span style="color: #ff6b6b; font-size: 11px; margin-left: 12px;">[{prob}% AI: {reasons}]</span>'
                elif cls == "mixed":
                    bg = "background-color: rgba(255, 187, 0, 0.22); border-left: 4px solid #ffbb00;"
                    badge = f'<span style="color: #ffd166; font-size: 11px; margin-left: 12px;">[{prob}% AI]</span>'
                else:
                    bg = "border-left: 4px solid transparent;"
                    badge = ""

                heatmap_html.append(
                    f'<div style="{bg} padding: 1px 8px; margin: 1px 0;" {title_attr}>'
                    f'<span style="color: #8b949e; display: inline-block; width: 36px; text-align: right; margin-right: 12px; user-select: none;">{line_no}</span>'
                    f'<span>{code_text}</span>{badge}'
                    f'</div>'
                )
            heatmap_html.append("</div>")
            st.markdown("".join(heatmap_html), unsafe_allow_html=True)
        else:
            st.error(det_result.get("error", "AI code detection failed."))

    hum_result = st.session_state.get("humanize_result")
    if hum_result:
        st.divider()
        if hum_result.get("status") == "proposal":
            st.success("Humanized code proposal generated! Redundant AI comments stripped and generic tokens naturalized.")
            h_col1, h_col2 = st.columns(2)
            with h_col1:
                st.subheader("Original (AI-style)")
                st.code(hum_result["original_code"], language=streamlit_language(detector_language))
            with h_col2:
                st.subheader("Humanized Code")
                st.code(hum_result["humanized_code"], language=streamlit_language(detector_language))

            if hum_result.get("diff"):
                with st.expander("Review Humanization Diff", expanded=True):
                    st.code(hum_result["diff"], language="diff")

            if st.button("Apply Humanized Code to Editor", type="primary"):
                st.session_state["input_code"] = hum_result["humanized_code"]
                st.session_state["humanize_result"] = None
                st.session_state["detector_result"] = None
                st.rerun()

            st.download_button(
                "Download Humanized Code",
                data=hum_result["humanized_code"],
                file_name=f"humanized_{_safe_filename(st.session_state['source_filename'])}",
                mime="text/plain",
                use_container_width=True,
            )
        else:
            st.error(hum_result.get("error", "Humanization failed."))

    st.stop()

if mode == "assistant":
    st.header("AI coding assistant")
    st.text_input("Filename", key="source_filename")
    assistant_language = detect_language(st.session_state["source_filename"])
    st.caption(f"Detected language: {language_label(assistant_language)}")
    st.text_area("Source code", key="input_code", height=320)
    action_options = ["question", "explain", "fix", "refactor", "type_hints", "tests", "complete"]
    action = st.selectbox(
        "Assistant action",
        options=action_options,
        format_func=lambda value: value.replace("_", " ").capitalize(),
        key="assistant_action",
    )
    request = st.text_area(
        "Request",
        key="assistant_request",
        height=120,
        placeholder="Explain this function, or ask for a smaller safe refactor...",
    )
    context = st.text_area(
        "Optional project context",
        key="assistant_context",
        height=120,
        placeholder="Paste relevant interfaces, file names, or related snippets.",
    )
    assistant_project_zip = st.file_uploader("Optional project ZIP context", type=["zip"], key="assistant_project_zip_upload")
    project_context = context
    if assistant_project_zip is not None:
        project_bytes = assistant_project_zip.getvalue()
        project_manifest = inspect_project_zip(project_bytes)
        st.session_state["assistant_project_manifest"] = project_manifest
        if project_manifest.get("ok"):
            context_names = [item["name"] for item in project_manifest.get("files", []) if detect_language(item.get("name"))]
            selected_files = st.multiselect(
                "Project files to include",
                options=context_names,
                default=[name for name in st.session_state.get("assistant_selected_files", []) if name in context_names],
                key="assistant_selected_files",
            )
            if selected_files:
                project_context_result = read_project_context(project_bytes, selected_files)
                project_context = "\n\n".join(filter(None, [context, project_context_result.get("context", "")]))
                st.caption(f"Selected {len(project_context_result.get('selected', []))} project file(s) as bounded context.")
        else:
            st.error(project_manifest.get("error", "Project archive rejected."))
    current_assistant_source = st.session_state["input_code"]
    current_assistant_identity = hashlib.sha256(current_assistant_source.encode("utf-8")).hexdigest()
    if st.session_state.get("assistant_source_identity") != current_assistant_identity:
        st.session_state["assistant_result"] = None
        st.session_state["assistant_approved_identity"] = None
        st.session_state["assistant_source_identity"] = current_assistant_identity
    def _ask_assistant() -> None:
        st.session_state["assistant_result"] = ask_assistant(
            st.session_state["input_code"],
            st.session_state["assistant_request"],
            filename=_safe_filename(st.session_state["source_filename"]),
            action=st.session_state["assistant_action"],
            context=project_context,
            provider_name=provider_name,
        )
        st.session_state["assistant_approved_identity"] = None
        st.session_state["assistant_source_identity"] = hashlib.sha256(
            st.session_state["input_code"].encode("utf-8")
        ).hexdigest()

    st.button("Ask assistant", type="primary", on_click=_ask_assistant)
    assistant_result = st.session_state.get("assistant_result")
    if assistant_result:
        status = assistant_result.get("status")
        if status == "answer":
            st.success("Assistant response")
            st.markdown(assistant_result.get("answer", ""))
        elif status == "proposal":
            st.success("An AST-validated proposal is ready for review.")
            st.code(assistant_result.get("proposal", ""), language=streamlit_language(assistant_language))
            if assistant_result.get("warnings"):
                st.warning("Validation warnings: " + " ".join(assistant_result["warnings"]))
            proposal = assistant_result.get("proposal", "")
            proposal_identity = hashlib.sha256(proposal.encode("utf-8")).hexdigest()
            if st.session_state.get("assistant_approved_identity") != proposal_identity:
                st.button(
                    "Approve assistant proposal",
                    type="primary",
                    on_click=_apply_assistant_proposal,
                    args=(proposal, proposal_identity),
                )
            else:
                st.success("Proposal approved and placed in the editor. Run a review before downloading it.")
        else:
            st.error(assistant_result.get("error", "The assistant could not complete the request."))
    st.stop()

if mode == "project":
    st.header("Project manifest")
    project_upload = st.file_uploader("Upload a project ZIP", type=["zip"])
    if project_upload is not None:
        result = inspect_project_zip(project_upload.getvalue())
        if result.get("ok"):
            result = analyze_project_zip(project_upload.getvalue())
        st.session_state["project_result"] = result
    result = st.session_state.get("project_result")
    if result:
        if result.get("ok"):
            st.success(f"Safe manifest created for {len(result.get('files', []))} supported files.")
            st.dataframe(result.get("files", []), hide_index=True, width="stretch")
            if result.get("analyses"):
                st.subheader("Python file checks")
                st.dataframe(result["analyses"], hide_index=True, width="stretch")
        else:
            st.error(result.get("error", "Project archive rejected."))
    st.stop()

if mode == "github_pr":
    st.header("GitHub PR import")
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        st.warning("Set GITHUB_TOKEN in your environment to enable this feature.")
    else:
        owner = st.text_input("Repository owner")
        repository = st.text_input("Repository name")
        pr_number = st.number_input("PR number", min_value=1, step=1, value=1)
        if st.button("Fetch PR diff", type="primary", disabled=not (owner and repository)):
            with st.spinner("Fetching PR diff..."):
                diff_result = fetch_pull_request_diff(owner, repository, int(pr_number), github_token)
                st.session_state["github_pr_result"] = diff_result
        pr_result = st.session_state.get("github_pr_result")
        if pr_result:
            if pr_result.get("status") == "ready":
                st.success(f"Fetched PR #{pr_number} from {owner}/{repository}")
                files = pr_result.get("files", [])
                st.caption(f"{len(files)} file(s) changed")
                for file_info in files:
                    with st.expander(f"{file_info['status']} {file_info['filename']} (+{file_info['additions']}/-{file_info['deletions']})"):
                        st.code(file_info.get("patch", ""), language="diff")
                if st.button("Prepare local review", type="secondary"):
                    local_review = prepare_local_review(pr_result)
                    st.session_state["github_pr_result"] = local_review
                    st.rerun()
            elif pr_result.get("status") == "proposal":
                st.download_button(
                    "Export patch as JSON",
                    data=json.dumps(pr_result, indent=2),
                    file_name=f"pr-{pr_result.get('number', 'unknown')}-patch.json",
                    mime="application/json",
                    width="stretch",
                )
            else:
                st.error(pr_result.get("error", "Failed to fetch PR."))
    st.stop()

with st.form("review_form"):
    st.text_input("Filename", key="source_filename")
    source_filename = _safe_filename(st.session_state["source_filename"])
    detected_language = detect_language(source_filename)
    st.caption(f"Detected language: {language_label(detected_language)}")
    original_code = st.text_area("Source code", key="input_code", height=320)
    btn_col1, btn_col2 = st.columns([1, 1])
    with btn_col1:
        review_clicked = st.form_submit_button("Run review", type="primary", use_container_width=True)
    with btn_col2:
        quick_fix_clicked = st.form_submit_button("⚡ Quick Fix & Match Format", type="secondary", use_container_width=True)

if review_clicked or quick_fix_clicked:
    st.session_state.update(
        review_result=None,
        approved_code=None,
        approved_identity=None,
        mode_result=None,
        test_result=None,
        sandbox_result=None,
        explanation_requested=False,
    )
    run_mode = "fix_syntax" if quick_fix_clicked else mode
    with st.spinner("Processing with format synchronization..."):
        if run_mode == "fix_syntax":
            st.session_state["review_result"] = fix_code(
                original_code,
                source_filename,
                provider_name=provider_name,
                include_explanation=False,
            )
        elif run_mode == "tests":
            st.session_state["test_result"] = generate_tests(
                original_code,
                source_filename,
                provider_name=provider_name,
            )
        else:
            st.session_state["mode_result"] = review_source(
                original_code,
                source_filename,
                run_mode,
                provider_name=provider_name,
            )
    active_result = st.session_state.get("review_result") or st.session_state.get("mode_result") or st.session_state.get("test_result")
    if active_result:
        _save_history(source_filename, run_mode, original_code, active_result)

result = st.session_state.get("review_result")
if mode == "fix_syntax" and result is None and st.session_state.get("mode_result") is not None:
    result = st.session_state["mode_result"]
    st.header(f"{result.get('language_label', 'Source')} validation")
    st.write(result.get("message", result.get("syntax_message", "")))
    if result.get("provider_message"):
        st.info(result["provider_message"])
    _show_findings(result.get("findings", []))
    if result.get("status") == "unsupported":
        st.error(result.get("error", "Unsupported source type."))
elif mode == "fix_syntax" and result is not None:
    state = result.get("state", "failed")
    if state == "valid":
        st.success("The source is already syntactically valid.")
    elif state == "fixed":
        st.success("A syntax-valid proposal is ready for review.")
    elif state == "unavailable":
        st.warning(result.get("error", "The selected provider or language validator is unavailable."))
    else:
        st.error(result.get("error", "No valid fix was produced."))

    status_col, attempt_col, candidate_col = st.columns(3)
    status_col.metric("Proposal state", state)
    attempt_col.metric("Fix attempts", result.get("attempt_count", 0))
    candidate_col.metric("Candidate syntax", "valid" if result.get("candidate_valid") else "not valid")
    if result.get("error") and state != "fixed":
        st.caption(result["error"])
    if result.get("semantic_warnings"):
        st.warning("Validation warnings: " + " ".join(result["semantic_warnings"]))

    source_language = streamlit_language(result.get("language") or detected_language)
    from tools import detect_indent

    orig_sample = result.get("original_code", original_code)
    indent_char, indent_size = detect_indent(orig_sample)
    indent_desc = f"{indent_size} spaces" if indent_char == " " else "Tabs"
    line_ending_desc = "CRLF (Windows)" if "\r\n" in orig_sample else "LF (Unix)"
    st.info(f"📐 **Format Synchronized:** Indentation style ({indent_desc}) and line-endings ({line_ending_desc}) strictly matched to uploaded code.", icon=":material/format_align_left:")

    original_col, proposed_col = st.columns(2)
    with original_col:
        st.subheader("Original code")
        st.code(result.get("original_code", original_code), language=source_language, line_numbers=True)
    with proposed_col:
        st.subheader("Proposed code (format-matched)")
        st.code(result.get("fixed_code") or "No valid proposal", language=source_language, line_numbers=True)

    if result.get("language_check"):
        language_check = result["language_check"]
        check_status = language_check.get("status", "unknown")
        if check_status == "findings" and result.get("candidate_valid"):
            check_status = "passed with advisory warnings"
        st.caption(
            f"Proposal validation: {language_check.get('tool', 'built-in')} — "
            f"{check_status}"
        )

    if result.get("diff"):
        with st.expander("Review the diff", expanded=True):
            st.code(result["diff"], language="diff")

    with st.expander("Why this proposal was made", expanded=True):
        explanation = result.get("explanation", {})
        for label, key in (("Summary", "summary"), ("Root cause", "root_cause"), ("Changes", "changes"), ("Remaining concerns", "remaining_concerns")):
            st.markdown(f"**{label}:** {explanation.get(key, 'Not available.')}")
        if state == "fixed" and st.button("Ask for detailed explanation"):
            result["explanation"] = explain_proposal(result, provider_name=provider_name)
            st.session_state["review_result"] = result
            st.rerun()

    report_col, proposal_report_col = st.columns(2)
    with report_col:
        _show_ruff_report("Original Ruff analysis", result.get("original_ruff") or run_ruff(original_code, source_filename))
    with proposal_report_col:
        _show_ruff_report("Proposed Ruff analysis", result.get("proposed_ruff", {}))

    result_filename = result.get("filename") or source_filename
    if state == "valid":
        st.subheader("Correct code")
        st.success("This uploaded code is already syntactically correct.")
        st.caption(f"Output file: correct_{result_filename} ({result.get('language_label', 'Source')})")
        st.code(result["fixed_code"], language=source_language)
        st.download_button(
            "Download correct code",
            data=result["fixed_code"],
            file_name=f"correct_{result_filename}",
            mime="text/plain",
            width="stretch",
        )
    elif state == "fixed":
        proposal_id = result.get("proposal_id")
        if st.session_state.get("approved_identity") != proposal_id:
            st.caption(f"Output file: corrected_{result_filename} ({result.get('language_label', 'Source')})")
            if st.button("Approve and apply fix", type="primary"):
                st.session_state["approved_code"] = result["fixed_code"]
                st.session_state["approved_identity"] = proposal_id
                st.rerun()
        else:
            st.subheader("Corrected code")
            st.success("The fix was approved and applied. Your corrected code is ready to download.")
            st.caption(f"Output file: corrected_{result_filename} ({result.get('language_label', 'Source')})")
            st.code(st.session_state["approved_code"], language=source_language)
            st.download_button(
                "Download corrected code",
                data=st.session_state["approved_code"],
                file_name=f"corrected_{result_filename}",
                mime="text/plain",
                width="stretch",
            )
    if result.get("logs"):
        with st.expander("Analysis log"):
            st.caption("\n".join(result["logs"]))

elif mode == "tests" and st.session_state.get("test_result") is not None:
    result = st.session_state["test_result"]
    if result.get("status") == "proposal":
        st.success("Generated tests are an unapproved proposal; they have not run.", icon=":material/science:")
        st.code(result["tests"], language="python")
        st.download_button(
            "Download proposed tests",
            data=result["tests"],
            file_name=result["filename"],
            mime="text/x-python",
        )

        # Sandbox controls
        st.divider()
        st.subheader("Sandbox execution")
        st.caption("The sandbox runs `python -m pytest -q` in a temporary directory with a timeout and output cap. It is disabled by default on Windows.")
        sandbox_allowed = os.getenv("ENABLE_TEST_RUNNER", "false").lower() == "true"
        isolated_allowed = os.getenv("TEST_RUNNER_ISOLATED", "false").lower() == "true"
        if not sandbox_allowed:
            st.info("Sandbox is disabled. Set `ENABLE_TEST_RUNNER=true` to enable.")
        elif os.name == "nt" and not isolated_allowed:
            st.warning("Windows requires an explicitly configured isolated runner. Set `TEST_RUNNER_ISOLATED=true` in addition to `ENABLE_TEST_RUNNER=true`.")
        else:
            st.success("Sandbox is available.")

        if st.button("Run tests in sandbox", type="primary", disabled=not sandbox_allowed or (os.name == "nt" and not isolated_allowed)):
            with st.spinner("Running pytest in sandbox..."):
                import tempfile
                with tempfile.TemporaryDirectory() as tmp_dir:
                    tmp_path = Path(tmp_dir)
                    (tmp_path / source_filename).write_text(original_code, encoding="utf-8")
                    test_filename = result.get("filename", f"test_{source_filename}")
                    (tmp_path / test_filename).write_text(result.get("tests", ""), encoding="utf-8")
                    st.session_state["sandbox_result"] = run_pytest_sandbox(tmp_path, enabled=True, timeout_seconds=15)

        sandbox_result = st.session_state.get("sandbox_result")
        if sandbox_result:
            status = sandbox_result.get("status")
            if status == "unavailable":
                st.info(sandbox_result.get("message", "Sandbox execution is unavailable."))
            elif status == "passed":
                st.success(sandbox_result.get("message", "Tests passed."))
            elif status == "failed":
                st.error(sandbox_result.get("message", "Tests failed."))
            elif status == "timeout":
                st.warning(sandbox_result.get("message", "Test execution timed out."))
            else:
                st.warning(sandbox_result.get("message", f"Sandbox status: {status}"))
            if sandbox_result.get("stdout"):
                st.code(sandbox_result["stdout"], language="text")
            if sandbox_result.get("stderr"):
                st.code(sandbox_result["stderr"], language="text")
    else:
        st.warning(result.get("error", "Test generation was unavailable."))


elif mode in {"review_quality", "security", "refactor", "type_hints"} and st.session_state.get("mode_result") is not None:
    result = st.session_state["mode_result"]
    st.header(f"{result.get('language_label', 'Source')} {mode.replace('_', ' ')} review")
    _health_panel(result)
    st.divider()
    st.write(result.get("syntax_message", ""))
    if result.get("language_check"):
        check = result["language_check"]
        st.caption(f"Static checker: {check.get('tool', 'built-in')} — {check.get('status', 'unknown')}")
    if result.get("provider_message"):
        st.warning(result["provider_message"])
    _show_ruff_report("Ruff analysis", result.get("ruff", {}))
    _show_findings(result.get("findings", []))

# Provider warning already shown in sidebar
