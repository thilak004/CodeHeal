"""Safe command-line entry point for proposal-only reviews."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent import fix_code
from languages import detect_language
from review import review_source
from test_generation import generate_tests


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review supported source files without executing them.")
    parser.add_argument("path", type=Path, help="Path to a supported source file")
    parser.add_argument(
        "--mode",
        choices=("fix_syntax", "review_quality", "security", "refactor", "type_hints", "tests", "ai_detector"),
        default="review_quality",
    )
    parser.add_argument("--output", choices=("json", "text"), default="json")
    parser.add_argument("--provider", choices=("groq", "ollama", "claude"), default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source = args.path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"Could not read source file: {exc}", file=sys.stderr)
        return 2

    if detect_language(args.path.name) is None:
        print(f"Unsupported file type: {args.path.name}", file=sys.stderr)
        return 2
    if args.mode == "fix_syntax":
        result = fix_code(
            source,
            args.path.name,
            provider_name=args.provider,
            include_explanation=False,
        )
    elif args.mode == "tests":
        result = generate_tests(source, args.path.name, provider_name=args.provider)
    elif args.mode == "ai_detector":
        from detector import detect_ai_code

        result = detect_ai_code(source, args.path.name)
    else:
        result = review_source(source, args.path.name, args.mode, provider_name=args.provider)

    if args.output == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"status: {result.get('state', result.get('status', 'unknown'))}")
        if result.get("error"):
            print(f"error: {result['error']}")
        if result.get("ai_probability") is not None:
            print(f"verdict: {result.get('verdict')}")
            print(f"ai_probability: {result.get('ai_probability')}%")
            print(f"human_probability: {result.get('human_probability')}%")
            print(f"flagged_lines: {result.get('flagged_lines_count')}/{result.get('total_lines')}")
        if result.get("findings"):
            print(f"findings: {len(result['findings'])}")
        if result.get("fixed_code"):
            print(result["fixed_code"])
        elif result.get("tests"):
            print(result["tests"])
    return 0 if result.get("success", result.get("status") not in {"failed", "unavailable", "unsupported"}) else 1


if __name__ == "__main__":
    raise SystemExit(main())
