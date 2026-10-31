"""Safe inspection of uploaded multi-language project archives."""
from __future__ import annotations

import io
import posixpath
import stat
import zipfile
from typing import Any

from languages import detect_language
from multilang import candidate_is_acceptable, check_source
from tools import check_syntax, run_ruff

MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_FILES = 200
MAX_TOTAL_UNCOMPRESSED = 20 * 1024 * 1024
ALLOWED_SUFFIXES = {
    ".py", ".js", ".jsx", ".java", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".cs",
    ".toml", ".ini", ".cfg", ".txt", ".md",
}


def _safe_member(name: str) -> bool:
    normalized = posixpath.normpath(name.replace("\\", "/"))
    return normalized not in {".", ""} and not normalized.startswith("../") and "/../" not in f"/{normalized}/" and not normalized.startswith("/")


def inspect_project_zip(data: bytes) -> dict[str, Any]:
    """Validate archive metadata and return a text manifest without extraction."""
    if len(data) > MAX_ARCHIVE_BYTES:
        return {"ok": False, "error": "Archive exceeds the 10 MB upload limit.", "files": []}
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "The uploaded file is not a valid ZIP archive.", "files": []}

    members = archive.infolist()
    if len(members) > MAX_FILES:
        return {"ok": False, "error": f"Archive contains more than {MAX_FILES} files.", "files": []}
    total = sum(member.file_size for member in members)
    if total > MAX_TOTAL_UNCOMPRESSED:
        return {"ok": False, "error": "Archive expands beyond the 20 MB limit.", "files": []}

    selected: list[dict[str, Any]] = []
    for member in members:
        if member.is_dir():
            continue
        if stat.S_ISLNK(member.external_attr >> 16):
            return {"ok": False, "error": f"Symbolic links are not allowed: {member.filename}", "files": []}
        if not _safe_member(member.filename):
            return {"ok": False, "error": f"Unsafe archive path: {member.filename}", "files": []}
        suffix = "." + member.filename.rsplit(".", 1)[-1].lower() if "." in member.filename else ""
        if suffix in ALLOWED_SUFFIXES:
            selected.append({"name": member.filename, "size": member.file_size, "suffix": suffix})
    return {"ok": True, "error": None, "files": selected, "total_bytes": total}


def analyze_project_zip(data: bytes) -> dict[str, Any]:
    """Inspect supported Python files in memory without importing or executing them."""
    manifest = inspect_project_zip(data)
    if not manifest.get("ok"):
        return manifest
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "The uploaded file is not a valid ZIP archive.", "files": []}

    analyses: list[dict[str, Any]] = []
    for item in manifest["files"]:
        try:
            source = archive.read(item["name"]).decode("utf-8")
        except (UnicodeDecodeError, KeyError, OSError) as exc:
            analyses.append({"name": item["name"], "status": "error", "error": f"Could not read UTF-8 source: {exc}"})
            continue
        language = detect_language(item["name"])
        if language == "python":
            syntax_ok, syntax_message = check_syntax(source)
            result = {
                "name": item["name"],
                "language": "Python",
                "status": "valid" if syntax_ok else "needs_fix",
                "syntax": syntax_message,
                "checker": "ruff",
                "ruff": run_ruff(source, item["name"]),
            }
        else:
            checked = check_source(source, item["name"])
            acceptable = candidate_is_acceptable(checked)
            result = {
                "name": item["name"],
                "language": checked.get("language_label", language),
                "status": "valid" if acceptable else checked.get("status", "error"),
                "syntax": checked.get("message", "Language check completed."),
                "checker": checked.get("tool", "built-in"),
                "findings": checked.get("findings", []),
            }
        analyses.append(result)
    return {**manifest, "analyses": analyses}


def read_project_context(
    data: bytes,
    selected_names: list[str] | None = None,
    max_bytes: int = 120 * 1024,
) -> dict[str, Any]:
    """Read explicitly selected supported source files into bounded context."""
    manifest = inspect_project_zip(data)
    if not manifest.get("ok"):
        return {**manifest, "context": "", "selected": []}
    allowed = {item["name"] for item in manifest.get("files", []) if detect_language(item.get("name"))}
    selected = [name for name in (selected_names or []) if name in allowed]
    if not selected:
        return {
            **manifest,
            "context": "No Python project files were selected.",
            "selected": [],
        }
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "The uploaded file is not a valid ZIP archive.", "context": "", "selected": []}

    sections: list[str] = []
    total_bytes = 0
    included: list[str] = []
    for name in selected:
        try:
            source = archive.read(name).decode("utf-8")
        except (UnicodeDecodeError, KeyError, OSError) as exc:
            sections.append(f"FILE_START {name}\n[Could not decode UTF-8 source: {exc}]\nFILE_END")
            continue
        section = f"FILE_START {name}\n{source}\nFILE_END"
        section_bytes = len(section.encode("utf-8"))
        if total_bytes + section_bytes > max_bytes:
            remaining = max_bytes - total_bytes
            if remaining > 0:
                sections.append(section.encode("utf-8")[:remaining].decode("utf-8", errors="ignore"))
            sections.append("[Project context truncated at the configured limit.]")
            break
        sections.append(section)
        included.append(name)
        total_bytes += section_bytes
    return {
        **manifest,
        "context": "\n\n".join(sections),
        "selected": included,
    }
