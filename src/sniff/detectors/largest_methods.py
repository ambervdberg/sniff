#!/usr/bin/env python3
"""Rank the largest methods/functions in a codebase by line count.

A thin skill on top of the harness: it supplies the per-language "what counts
as a method/function" node kinds, then lets the shared engine do the scanning,
nested-closure folding, naming, ranking, and table printing. The calling agent
only ever sees the small table at the end, never the raw AST.

Usage:
    python -m sniff.detectors.largest_methods [PATH] [--top N] [--lang L ...] [--include-tests]

PATH defaults to the current directory. Languages are auto-detected from the
file extensions present unless --lang is given (repeatable).
"""

from __future__ import annotations

import sys

from sniff.detectors import _node_metric_cli as cli

NAME = "largest-methods"
TITLE = "Longest methods"
DEFAULT_ARGS: "list[str]" = []

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

# The languages this detector has node kinds for; every other language is
# reported as out of scope rather than silently scanned and found empty.
LANGUAGES = sorted(LANG_KINDS)


def main(argv: "list[str] | None" = None) -> int:
    parser = cli.new_parser("Rank the largest methods/functions by line count.")
    cli.finish_parser(parser)
    args = parser.parse_args(argv)

    langs = cli.detect_and_gate(args, LANGUAGES)
    if langs is None:
        return 0

    spec = cli.SizeSpec(
        rule=LANG_KINDS,
        header=lambda shown, total, langs_str, tests_str: (
            f"Largest {shown} of {total} methods/functions "
            f"({langs_str}; tests {tests_str}; nested closures folded into their parent):"
        ),
        empty_message="No methods or functions matched.",
    )
    return cli.run_size_main(args, langs, spec)


if __name__ == "__main__":
    sys.exit(main())
