"""Language detection and source-file metadata for multi-language review."""
from __future__ import annotations

from pathlib import Path

LANGUAGE_SPECS = {
    "python": {"label": "Python", "extensions": (".py",), "streamlit": "python"},
    "javascript": {"label": "JavaScript", "extensions": (".js", ".jsx"), "streamlit": "javascript"},
    "java": {"label": "Java", "extensions": (".java",), "streamlit": "java"},
    "c": {"label": "C", "extensions": (".c", ".h"), "streamlit": "c"},
    "cpp": {"label": "C++", "extensions": (".cc", ".cpp", ".cxx", ".hpp"), "streamlit": "cpp"},
    "csharp": {"label": "C#", "extensions": (".cs",), "streamlit": "csharp"},
}

_EXTENSION_TO_LANGUAGE = {
    extension: language
    for language, spec in LANGUAGE_SPECS.items()
    for extension in spec["extensions"]
}
SUPPORTED_EXTENSIONS = tuple(sorted(_EXTENSION_TO_LANGUAGE))


def detect_language(filename: str | None) -> str | None:
    """Return the registered language for a filename, or ``None`` if unsupported."""
    suffix = Path(filename or "").suffix.lower()
    return _EXTENSION_TO_LANGUAGE.get(suffix)


def language_label(language: str | None) -> str:
    if language in LANGUAGE_SPECS:
        return str(LANGUAGE_SPECS[language]["label"])
    return "Unknown"


def streamlit_language(language: str | None) -> str:
    if language in LANGUAGE_SPECS:
        return str(LANGUAGE_SPECS[language]["streamlit"])
    return "text"


def supported_source_names() -> list[str]:
    return [str(spec["label"]) for spec in LANGUAGE_SPECS.values()]


def source_extensions(language: str | None = None) -> tuple[str, ...]:
    if language in LANGUAGE_SPECS:
        return tuple(str(extension) for extension in LANGUAGE_SPECS[language]["extensions"])
    return SUPPORTED_EXTENSIONS
