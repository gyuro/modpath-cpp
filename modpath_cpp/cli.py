from __future__ import annotations

import argparse
import json
import sys

from .planner import analyze_compile_commands, format_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="modpath-cpp",
        description=(
            "Analyze compile_commands.json and emit a practical C++20 modules migration plan."
        ),
    )
    parser.add_argument(
        "compile_commands",
        nargs="?",
        default="./compile_commands.json",
        help="Path to compile_commands.json (default: ./compile_commands.json)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output machine-readable JSON for CI",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Maximum number of candidates to report (default: 10)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        report = analyze_compile_commands(args.compile_commands, top=args.top)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
