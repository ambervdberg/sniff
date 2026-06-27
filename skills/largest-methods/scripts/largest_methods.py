#!/usr/bin/env python3
"""Rank the largest methods/functions in a codebase by line count.

A thin skill on top of _ast-harness: it supplies the per-language "what counts
as a method/function" node kinds, then lets the shared engine do the scanning,
nested-closure folding, naming, ranking, and table printing. The calling agent
only ever sees the small table at the end, never the raw AST.

Usage:
    python largest_methods.py [PATH] [--top N] [--lang L ...] [--include-tests]

PATH defaults to the current directory. Languages are auto-detected from the
file extensions present unless --lang is given (repeatable).
"""

from __future__ import annotations

import argparse
import os
import sys

# Import the shared engine from the sibling _ast-harness directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_ast-harness"))
import harness as h  # noqa: E402

# The tree-sitter node kinds that represent "a method or function" per language.
# Function expressions / arrows are included so class-field callables and
# top-level const handlers are counted too; nested ones are folded away by the
# harness. This map is the only thing this skill knows that the engine doesn't.
LANG_KINDS = {
    "typescript": ["method_definition", "function_declaration", "arrow_function", "function_expression"],
    "tsx": ["method_definition", "function_declaration", "arrow_function", "function_expression"],
    "javascript": ["method_definition", "function_declaration", "arrow_function", "function_expression"],
    "python": ["function_definition"],
    "rust": ["function_item"],
    "go": ["function_declaration", "method_declaration", "func_literal"],
    "java": ["method_declaration", "constructor_declaration"],
    "ruby": ["method", "singleton_method"],
    "csharp": ["method_declaration", "constructor_declaration", "local_function_statement"],
    "php": ["method_declaration", "function_definition"],
    "kotlin": ["function_declaration"],
    "swift": ["function_declaration"],
    "scala": ["function_definition"],
    "c": ["function_definition"],
    "cpp": ["function_definition"],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank the largest methods/functions by line count.")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=20, help="how many to show (default: 20)")
    parser.add_argument("--lang", action="append", help="force a language (repeatable); skips auto-detect")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    args = parser.parse_args()

    langs = sorted(set(args.lang)) if args.lang else sorted(h.detect_languages(args.path))
    if not langs:
        sys.exit(f"No supported source files found under {args.path!r}.")

    matches = h.run(LANG_KINDS, args.path, lang=langs, include_tests=args.include_tests)
    matches = h.fold_nested(matches)

    if not matches:
        print("No methods or functions matched.")
        return

    header = (
        f"Largest {min(args.top, len(matches))} of {len(matches)} methods/functions "
        f"({', '.join(langs)}; tests {'included' if args.include_tests else 'excluded'}; "
        f"nested closures folded into their parent):"
    )

    h.print_table(
        matches,
        columns=[
            ("LINES", lambda m: m.lines),
            ("NAME", lambda m: m.name),
            ("LOCATION", lambda m: m.location),
        ],
        sort_key=lambda m: m.lines,
        top=args.top,
        header=header,
    )


if __name__ == "__main__":
    main()
