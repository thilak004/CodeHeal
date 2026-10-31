"""Heuristic and stylometric AI code detection engine.

Analyzes source code across supported languages for telltale markers of AI generation:
- Low burstiness / uniform line and statement entropy
- Overly verbose, redundant comments on self-explanatory logic
- Textbook boilerplate patterns and generic naming distributions
- AI assistant signature artifacts and docstring structures
"""
from __future__ import annotations

import ast
import math
import re
from typing import Any

from languages import detect_language, language_label
from tools import check_source_size, normalize_source


GENERIC_IDENTIFIERS = {
    "data", "temp", "tmp", "val", "value", "res", "result", "item", "items",
    "elem", "element", "obj", "object", "arr", "array", "lst", "output", "input_val",
    "input_data", "output_data", "helper", "process_data", "handle_request", "foo", "bar",
}

AI_COMMENT_PATTERNS = [
    re.compile(r"^\s*#\s*(?:initialize|declare|define|set up|create)\b", re.IGNORECASE),
    re.compile(r"^\s*#\s*(?:loop through|iterate through|for each|traverse)\b", re.IGNORECASE),
    re.compile(r"^\s*#\s*(?:check if|verify that|ensure that|validate)\b", re.IGNORECASE),
    re.compile(r"^\s*#\s*(?:return the|output the|print the|display the)\b", re.IGNORECASE),
    re.compile(r"^\s*#\s*(?:increment|decrement|add 1|subtract 1)\b", re.IGNORECASE),
    re.compile(r"^\s*#\s*(?:step \d+|case \d+|example usage)\b", re.IGNORECASE),
    re.compile(r"^\s*//\s*(?:initialize|declare|loop through|check if|return the)\b", re.IGNORECASE),
]

AI_SIGNATURE_PHRASES = [
    "here is the complete code",
    "here is the updated code",
    "time complexity:",
    "space complexity:",
    "example usage:",
    "sample usage:",
    "todo: replace with",
    "explanation of changes",
    "this function takes",
]


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    frequencies: dict[str, int] = {}
    for char in text:
        frequencies[char] = frequencies.get(char, 0) + 1
    length = len(text)
    return -sum((count / length) * math.log2(count / length) for count in frequencies.values())


def _analyze_burstiness(lines: list[str]) -> float:
    """Calculate variance of line lengths. AI code tends to have uniform, low variance."""
    lengths = [len(line.strip()) for line in lines if line.strip()]
    if len(lengths) < 3:
        return 0.5
    mean = sum(lengths) / len(lengths)
    variance = sum((length_val - mean) ** 2 for length_val in lengths) / len(lengths)
    std_dev = math.sqrt(variance)
    coefficient_of_variation = std_dev / (mean + 1e-5)
    # Low CV (< 0.45) indicates machine-uniform code; high CV indicates human irregular bursts
    return max(0.0, min(1.0, 1.0 - (coefficient_of_variation / 1.1)))


def _analyze_comments(lines: list[str]) -> tuple[float, list[int]]:
    """Detect overly verbose or textbook redundant comments typical of LLMs."""
    code_line_count = 0
    comment_line_count = 0
    flagged_comment_lines: list[int] = []

    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "//", "/*", "*")):
            comment_line_count += 1
            for pat in AI_COMMENT_PATTERNS:
                if pat.search(stripped):
                    flagged_comment_lines.append(idx)
                    break
        else:
            code_line_count += 1

    total = code_line_count + comment_line_count
    if total == 0:
        return 0.0, []

    redundant_ratio = len(flagged_comment_lines) / max(1, comment_line_count)
    density_ratio = comment_line_count / total
    score = (redundant_ratio * 0.7) + (min(1.0, density_ratio * 2.0) * 0.3)
    return min(1.0, score), flagged_comment_lines


def _analyze_identifiers(source: str, language: str) -> tuple[float, list[str]]:
    """Measure proportion of textbook/generic identifiers."""
    found_generic: list[str] = []
    total_identifiers = 0

    if language == "python":
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    total_identifiers += 1
                    if node.id.lower() in GENERIC_IDENTIFIERS:
                        found_generic.append(node.id)
                elif isinstance(node, ast.arg):
                    total_identifiers += 1
                    if node.arg.lower() in GENERIC_IDENTIFIERS:
                        found_generic.append(node.arg)
        except Exception:
            tokens = re.findall(r"\b[A-Za-z_]\w*\b", source)
            total_identifiers = len(tokens)
            found_generic = [t for t in tokens if t.lower() in GENERIC_IDENTIFIERS]
    else:
        tokens = re.findall(r"\b[A-Za-z_]\w*\b", source)
        total_identifiers = len(tokens)
        found_generic = [t for t in tokens if t.lower() in GENERIC_IDENTIFIERS]

    if total_identifiers == 0:
        return 0.0, []
    ratio = len(found_generic) / max(1, total_identifiers)
    # 15%+ generic tokens strongly signals generated textbook code
    score = min(1.0, ratio * 5.0)
    return score, sorted(set(found_generic))


def _analyze_ai_signatures(source: str) -> float:
    """Detect artifacts frequently left by LLM responses."""
    lower_source = source.lower()
    matches = sum(1 for phrase in AI_SIGNATURE_PHRASES if phrase in lower_source)
    return min(1.0, matches * 0.35)


def _analyze_structural_uniformity(source: str, language: str) -> float:
    """Analyze AST or indentation depth uniformity."""
    lines = source.splitlines()
    indents = []
    for line in lines:
        if line.strip():
            indent = len(line) - len(line.lstrip())
            indents.append(indent)
    if len(indents) < 4:
        return 0.5
    indent_steps = [abs(indents[i] - indents[i - 1]) for i in range(1, len(indents))]
    even_steps = sum(1 for step in indent_steps if step in {0, 4, 2})
    return even_steps / len(indent_steps) if indent_steps else 0.5


def detect_ai_code(source: str, filename: str = "code.py") -> dict[str, Any]:
    """Run deterministic multi-signal stylometry and heuristics to estimate AI vs Human probability."""
    size_ok, size_message = check_source_size(source)
    if not size_ok:
        return {"status": "failed", "error": size_message}

    try:
        clean_source = normalize_source(source)
    except TypeError as exc:
        return {"status": "failed", "error": str(exc)}

    language = detect_language(filename) or "python"
    lines = clean_source.splitlines()
    if not any(line.strip() for line in lines):
        return {
            "status": "failed",
            "error": "The submitted code is empty.",
        }

    # Signal 1: Line length uniformity (low burstiness)
    burstiness_score = _analyze_burstiness(lines)

    # Signal 2: Comment redundancy & explanatory density
    comment_score, flagged_comment_lines = _analyze_comments(lines)

    # Signal 3: Generic identifier distribution
    generic_score, found_generic = _analyze_identifiers(clean_source, language)

    # Signal 4: Residual AI artifacts / phrasing
    signature_score = _analyze_ai_signatures(clean_source)

    # Signal 5: Structural & indentation uniformity
    structure_score = _analyze_structural_uniformity(clean_source, language)

    # Weighted combined probability calculation
    weights = [
        (comment_score, 0.28),
        (generic_score, 0.25),
        (burstiness_score, 0.22),
        (structure_score, 0.15),
        (signature_score, 0.10),
    ]
    raw_ai_prob = sum(val * wt for val, wt in weights)
    ai_prob_pct = int(max(5, min(98, round(raw_ai_prob * 100))))
    human_prob_pct = 100 - ai_prob_pct

    if ai_prob_pct >= 65:
        verdict = "Likely AI-Generated"
        verdict_color = "error"
    elif ai_prob_pct <= 35:
        verdict = "Likely Human-Written"
        verdict_color = "success"
    else:
        verdict = "Mixed / AI-Assisted"
        verdict_color = "warning"

    # Line-by-line classification for the visual heatmap
    line_analysis: list[dict[str, Any]] = []
    flagged_set = set(flagged_comment_lines)

    for idx, line in enumerate(lines, 1):
        stripped = line.strip()
        reasons: list[str] = []
        line_prob = ai_prob_pct

        if idx in flagged_set:
            line_prob = min(98, line_prob + 30)
            reasons.append("Redundant / descriptive AI-style comment")

        matched_generic = [g for g in found_generic if re.search(rf"\b{re.escape(g)}\b", stripped)]
        if matched_generic:
            line_prob = min(95, line_prob + 15)
            reasons.append(f"Generic textbook identifier: {', '.join(matched_generic[:3])}")

        for phrase in AI_SIGNATURE_PHRASES:
            if phrase in stripped.lower():
                line_prob = 99
                reasons.append(f"AI response artifact: '{phrase}'")

        if not stripped:
            classification = "neutral"
            line_prob = 0
        elif line_prob >= 65:
            classification = "ai"
        elif line_prob <= 35:
            classification = "human"
        else:
            classification = "mixed"

        line_analysis.append({
            "line_number": idx,
            "code": line,
            "ai_probability": line_prob,
            "classification": classification,
            "reasons": reasons,
        })

    explanation_points = []
    if comment_score > 0.4:
        explanation_points.append(
            f"High comment redundancy ({round(comment_score * 100)}% signal): Comments describe straightforward operations rather than domain intent."
        )
    if generic_score > 0.3:
        explanation_points.append(
            f"Textbook identifier pattern ({round(generic_score * 100)}% signal): Detected repeated generic variable names ({', '.join(found_generic[:4])})."
        )
    if burstiness_score > 0.6:
        explanation_points.append(
            f"Low line burstiness ({round(burstiness_score * 100)}% signal): Code formatting and line lengths are highly uniform and machine-templated."
        )
    if signature_score > 0:
        explanation_points.append("Direct AI chat prompt/completion artifacts were detected in the source.")

    if not explanation_points:
        explanation_points.append(
            "Natural variability detected: Line lengths, domain-specific naming, and organic structural variance align with typical human developer coding patterns."
        )

    return {
        "status": "ready",
        "ai_probability": ai_prob_pct,
        "human_probability": human_prob_pct,
        "verdict": verdict,
        "verdict_color": verdict_color,
        "language": language,
        "language_label": language_label(language),
        "signals": {
            "comment_redundancy": int(comment_score * 100),
            "generic_naming": int(generic_score * 100),
            "line_uniformity": int(burstiness_score * 100),
            "structural_consistency": int(structure_score * 100),
            "ai_signatures": int(signature_score * 100),
        },
        "flagged_lines_count": len([item for item in line_analysis if item["classification"] == "ai"]),
        "total_lines": len(lines),
        "line_analysis": line_analysis,
        "explanation": "\n".join(f"- {point}" for point in explanation_points),
    }


def humanize_code(
    source: str,
    filename: str = "code.py",
    provider_name: str | None = None,
) -> dict[str, Any]:
    """Transform robotic, overly-commented AI code into natural idiomatic human-style code."""
    from agent import _strip_markdown
    from multilang import validate_candidate_for_language
    from prompts import HUMANIZE_CODE_PROMPT
    from providers import create_provider
    from tools import build_unified_diff, check_source_size, match_code_formatting, validate_candidate

    size_ok, size_message = check_source_size(source)
    if not size_ok:
        return {"status": "failed", "error": size_message}

    language = detect_language(filename)
    if language is None:
        return {"status": "unsupported", "error": f"Unsupported file type: {filename}"}

    try:
        provider = create_provider(provider_name)
        response = provider.invoke(
            HUMANIZE_CODE_PROMPT.format_messages(
                language=language_label(language),
                filename=filename,
                code=source,
            )
        )
        raw = getattr(response, "content", "")
        candidate = _strip_markdown(raw if isinstance(raw, str) else str(raw), language)
        candidate = match_code_formatting(source, candidate)
        if language == "python":
            valid, error, warnings = validate_candidate(candidate, source, language=language)
        else:
            valid, error, warnings = validate_candidate_for_language(candidate, source, filename)

        if not valid:
            return {"status": "failed", "error": f"Humanized candidate validation failed: {error}", "warnings": warnings}

        return {
            "status": "proposal",
            "original_code": source,
            "humanized_code": candidate,
            "diff": build_unified_diff(source, candidate, filename, f"humanized_{filename}"),
            "filename": filename,
            "language": language,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}

