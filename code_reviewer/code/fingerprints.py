"""Language fingerprints used to reject proposals written in another language.

Every check in this module is a text heuristic. Nothing here imports, compiles,
or executes the inspected source. The goal is narrow: notice when a provider
answers a request for one language with source that plainly belongs to a
different language, so the proposal can be rejected before it reaches the user.

The fingerprints are deliberately conservative. A candidate is only reported as
a foreign language when the evidence is strong *and* clearly stronger than the
evidence for the language that was actually requested, so ordinary source is
never rejected by mistake.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from typing import Any

from languages import language_label

# A language needs at least this much evidence before it can be reported as
# the language of a candidate.
MIN_DETECTION_SCORE = 3
# The evidence for a foreign language must also beat the expected language by
# this margin, so ambiguous text is never reported as a mismatch.
MIN_MARGIN = 2
# The score carried by a language whose definitive marker is present. It
# outranks every other marker, so a file that carries one always wins.
DEFINITIVE_SCORE = 100

# Languages for which quoted text must be kept, rather than blanked.
_STRING_SENSITIVE = {"python"}

# Detection order. Ties are resolved in favour of the language listed first.
LANGUAGE_ORDER = (
    "python",
    "javascript",
    "java",
    "csharp",
    "c",
    "cpp",
)

# Languages that share a syntax family. A candidate written for one member is
# normally accepted for another member, because the two are interchangeable in
# practice. A family member is only rejected when the candidate carries
# evidence that belongs to the sibling language alone.
LANGUAGE_FAMILY = {
    "python": "python",
    "javascript": "script",
    "java": "java",
    "csharp": "csharp",
    "c": "c",
    "cpp": "c",
}

# Markers that cannot appear in any other supported language. They outrank
# every other marker, so a file that carries one is never attributed to a
# different language. They are matched against the code-only text, so a marker
# inside a string literal does not count.
_DEFINITIVE_MARKERS: dict[str, tuple[tuple[str, int], ...]] = {
    "csharp": ((r"(?m)^\s*using\s+System[\w.]*\s*;", 10),),
    "java": ((r"(?m)^\s*import\s+java\.[\w.]*\s*;", 10),),
}

# Markers shared by every member of a family.
_SHARED_MARKERS: dict[str, tuple[tuple[str, int], ...]] = {
    "script": (
        (r"(?m)^\s*(?:const|let|var)\s+\w+", 3),
        # An arrow function is also C#, Rust, and PHP syntax, so it is only a
        # weak hint here.
        (r"=>", 2),
        (r"console\.(?:log|error|warn)\s*\(", 3),
        (r"\brequire\s*\(", 3),
        (r"module\.exports", 3),
        (r"(?m)^\s*export\s+(?:default|const|let|function|class|\{)", 3),
        (r"document\.\w+\s*\(", 3),
        (r"(?m)^\s*function\s+\w*\s*\(", 2),
    ),
    "c": (
        (r"(?m)^\s*#include\s*[<\"]", 3),
        (r"(?m)^\s*int\s+main\s*\(", 3),
        (r"\bprintf\s*\(", 3),
        (r"\bmalloc\s*\(", 2),
        (r"(?m)^\s*typedef\s+struct\b", 3),
    ),
}

# Markers that belong to one language. A weight of 3 marks evidence that is
# essentially exclusive to that language; lower weights are shared hints.
_EXCLUSIVE_MARKERS: dict[str, tuple[tuple[str, int], ...]] = {
    "python": (
        (r"(?m)^\s*def\s+\w+\s*\(", 3),
        (r"(?m)^\s*(?:from\s+[\w.]+\s+import\b|import\s+[\w.]+)", 3),
        (r"(?m)^\s*print\s*\(", 2),
        (r"(?m)^\s*class\s+\w+\s*:", 2),
        (r"(?m)^\s*(?:elif\b|except\b|lambda\b|None\b|True\b|False\b)", 2),
        (r"(?<![.\w])self\.", 2),
    ),
    "javascript": (
        (r"(?m)^\s*type\s+\w+\s*=", 3),
        (r"(?m)^\s*import\s+type\s+", 3),
        (r":\s*(?:string|number|boolean|void|any|unknown|never)\b", 2),
    ),
    "java": (
        (r"(?m)^\s*package\s+[\w.]+\s*;", 3),
        (r"System\.out\.print", 3),
        (r"public\s+static\s+void\s+main\s*\(", 3),
        (r"@Override", 3),
        (r"(?m)^\s*public\s+(?:final\s+|abstract\s+)?(?:class|interface|enum)\s+\w+", 3),
    ),
    "csharp": (
        (r"Console\.\w+\s*\(", 3),
        (r"(?m)^\s*namespace\s+[\w.]+", 3),
        (r"public\s+static\s+void\s+Main\s*\(", 3),
        (r"(?m)^\s*public\s+(?:sealed\s+|static\s+|abstract\s+)?(?:class|interface|record)\s+\w+", 3),
    ),
    # C is a subset of C++, so plain C source stays valid C++ source.
    "c": (),
    "cpp": (
        (r"\bstd::", 3),
        (r"\bcout\s*<<", 3),
        (r"(?m)^\s*template\s*<", 3),
        (r"\bnullptr\b", 3),
        (r"(?m)^\s*class\s+\w+\s*(?::|\{)", 2),
        (r"(?m)^\s*(?:public|private|protected)\s*:", 3),
    ),
}

_QUOTED_TEXT = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`", re.DOTALL)


def _parses_as_python(candidate: str) -> bool:
    """Return True when the text parses as a Python module."""
    try:
        ast.parse(candidate)
    except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
        return False
    return True


def _python_module_like(candidate: str) -> bool:
    """Return True when the text is a Python module rather than a bare literal."""
    try:
        tree = ast.parse(candidate)
    except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
        return False
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(
            node.value, (ast.Dict, ast.List, ast.Set, ast.Tuple, ast.Constant)
        ):
            continue
        return True
    return False


def _structural_score(language: str, candidate: str, dominant: set[str]) -> int:
    """Return structural evidence that the whole candidate is written in a language.

    Structural evidence is only counted when no other language carries strong
    exclusive markers, so a file that merely resembles a data format cannot
    outrank a language the candidate is demonstrably written in.
    """
    if dominant and language not in dominant:
        return 0
    if language == "python":
        return 3 if _python_module_like(candidate) else 0
    return 0


def _satisfies_language(language: str, candidate: str) -> bool:
    """Return True when the candidate is structurally valid for the language.

    A candidate that already satisfies the requested language is never
    reported as a mismatch, even when it carries markers of another language.
    """
    if language == "python":
        return _python_module_like(candidate)
    return False


def _blank_quoted_text(text: str) -> str:
    """Replace quoted spans with spaces so their content is not read as code."""
    def replace(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return _QUOTED_TEXT.sub(replace, text)


def _blank_python_strings(candidate: str) -> str:
    """Blank Python string literals using the tokenizer, keeping line structure."""
    try:
        readline = io.BytesIO(candidate.encode("utf-8")).readline
        tokens = list(tokenize.tokenize(readline))
    except (SyntaxError, IndentationError, tokenize.TokenError, ValueError, UnicodeError):
        return _blank_quoted_text(candidate)
    lines = candidate.splitlines(keepends=True)
    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        start_row, start_col = token.start
        end_row, end_col = token.end
        if start_row - 1 >= len(lines) or end_row - 1 >= len(lines):
            continue
        if start_row == end_row:
            line = lines[start_row - 1]
            lines[start_row - 1] = line[:start_col] + " " * (end_col - start_col) + line[end_col:]
        else:
            lines[start_row - 1] = lines[start_row - 1][:start_col]
            for row in range(start_row, end_row - 1):
                lines[row] = ""
            last = lines[end_row - 1]
            lines[end_row - 1] = " " * end_col + last[end_col:]
    return "".join(lines)


def _scannable_text(language: str, candidate: str) -> str:
    """Return the candidate with string content removed where that is safe."""
    if language in _STRING_SENSITIVE:
        return candidate
    if language == "python" and _parses_as_python(candidate):
        return _blank_python_strings(candidate)
    return _blank_quoted_text(candidate)


def _exclusive_score(language: str, text: str) -> int:
    """Score only the markers that belong to one language."""
    score = 0
    for pattern, weight in _EXCLUSIVE_MARKERS.get(language, ()):
        if re.search(pattern, text):
            score += weight
    return score


def _definitive_languages(texts: dict[str, str]) -> set[str]:
    """Return the languages whose definitive markers are present.

    A definitive marker cannot appear in another supported language, so a
    candidate that carries one belongs to that language no matter what the
    weaker markers say.
    """
    definitive: set[str] = set()
    for language in LANGUAGE_ORDER:
        text = texts[language]
        for pattern, _weight in _DEFINITIVE_MARKERS.get(language, ()):
            if re.search(pattern, text):
                definitive.add(language)
                break
    return definitive


def _marker_score(language: str, text: str) -> int:
    """Score the shared family markers plus the language-specific markers."""
    score = _exclusive_score(language, text)
    for pattern, weight in _SHARED_MARKERS.get(LANGUAGE_FAMILY.get(language, ""), ()):
        if re.search(pattern, text):
            score += weight
    return score


def _scannable_texts(candidate: str) -> dict[str, str]:
    """Return the scannable text of the candidate for every language."""
    return {language: _scannable_text(language, candidate) for language in LANGUAGE_ORDER}


def _dominant_languages(texts: dict[str, str]) -> set[str]:
    """Return the languages whose exclusive markers are unmistakable."""
    dominant: set[str] = set()
    for language in LANGUAGE_ORDER:
        if _exclusive_score(language, texts[language]) >= MIN_DETECTION_SCORE:
            dominant.add(language)
    return dominant


def _score_parts(candidate: str) -> dict[str, tuple[int, int]]:
    """Return ``(marker_score, structural_score)`` for every supported language."""
    texts = _scannable_texts(candidate)
    definitive = _definitive_languages(texts)
    dominant = _dominant_languages(texts)
    parts: dict[str, tuple[int, int]] = {}
    for language in LANGUAGE_ORDER:
        marker = _marker_score(language, texts[language])
        if language in definitive:
            marker = max(marker, DEFINITIVE_SCORE)
        parts[language] = (
            marker,
            _structural_score(language, candidate, dominant),
        )
    return parts


def score_languages(candidate: str) -> dict[str, int]:
    """Score how strongly the candidate looks like each supported language."""
    if not isinstance(candidate, str) or not candidate.strip():
        return {}
    return {
        language: marker + structural
        for language, (marker, structural) in _score_parts(candidate).items()
    }


def _best_language(scores: dict[str, int]) -> str | None:
    best: str | None = None
    best_score = 0
    for language in LANGUAGE_ORDER:
        score = scores.get(language, 0)
        if score > best_score:
            best = language
            best_score = score
    return best


def _family_score(scores: dict[str, int], family: str) -> int:
    return max(
        (scores.get(language, 0) for language in LANGUAGE_ORDER if LANGUAGE_FAMILY[language] == family),
        default=0,
    )


def detect_language_of_candidate(candidate: str) -> str | None:
    """Return the language the candidate most resembles, or ``None`` when unclear."""
    scores = score_languages(candidate)
    if not scores:
        return None
    best = _best_language(scores)
    if best is None or scores[best] < MIN_DETECTION_SCORE:
        return None
    return best


def language_mismatch(candidate: str, expected: str | None) -> str | None:
    """Return a rejection message when the candidate is clearly another language.

    The check only reports a mismatch when the foreign language is both clearly
    present and clearly stronger than the expected language, so ordinary source
    is never rejected by mistake.
    """
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    if not expected or expected not in LANGUAGE_FAMILY:
        return None

    if _satisfies_language(expected, candidate):
        # The candidate already is valid source for the requested language.
        return None

    texts = _scannable_texts(candidate)
    definitive = _definitive_languages(texts)
    if expected in definitive:
        # The candidate carries a marker that only the requested language has.
        return None

    parts = _score_parts(candidate)
    scores = {language: marker + structural for language, (marker, structural) in parts.items()}
    best = _best_language(scores)
    if best is None or best == expected:
        return None
    best_score = scores[best]
    if best_score < MIN_DETECTION_SCORE:
        return None
    expected_family = LANGUAGE_FAMILY[expected]
    if LANGUAGE_FAMILY[best] == expected_family:
        # Same family. The two languages are interchangeable in practice, so a
        # mismatch is only reported when the candidate carries evidence that
        # belongs to the sibling language alone.
        if best in definitive:
            # The candidate carries a marker that only the sibling language
            # has, so it belongs to that language and not to the request.
            return (
                f"The model returned {language_label(best)}-like code "
                f"instead of {language_label(expected)} source."
            )
        text = texts[expected]
        sibling_score = _exclusive_score(best, text)
        if sibling_score <= _exclusive_score(expected, text):
            return None
        if sibling_score < MIN_DETECTION_SCORE:
            return None
    else:
        expected_score = _family_score(scores, expected_family)
        if best_score < expected_score + MIN_MARGIN:
            return None
    return f"The model returned {language_label(best)}-like code instead of {language_label(expected)} source."


def fingerprint_report(candidate: str) -> dict[str, Any]:
    """Return the per-language scores for diagnostics and tests."""
    parts = _score_parts(candidate)
    scores = {language: marker + structural for language, (marker, structural) in parts.items()}
    return {
        "scores": scores,
        "detected": detect_language_of_candidate(candidate),
    }
