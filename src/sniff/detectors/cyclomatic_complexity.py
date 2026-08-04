#!/usr/bin/env python3
"""Rank functions/methods by cyclomatic complexity.

A node-metric skill: it leans on the shared node_metric engine to score each
function by its number of independent paths (1 + decision points), then prints a
small COMPLEXITY / NAME / LOCATION table. High-complexity functions are the prime
"too many branches, split or simplify" refactor targets. The calling agent only
ever sees the table, never the AST.

Usage:
    python -m sniff.detectors.cyclomatic_complexity [PATH] [--top N] [--lang L ...] [--min N] [--include-tests]

PATH defaults to the current directory. Languages auto-detected unless --lang is
given (repeatable). Only languages the engine has decision kinds for are scored.
"""

from __future__ import annotations

import sys

from sniff import node_metric as nm
from sniff.detectors import _node_metric_cli as cli

NAME = "cyclomatic-complexity"
TITLE = "High cyclomatic complexity methods"
DEFAULT_ARGS: "list[str]" = []

# Counting decision points needs per-language node kinds, so the engine's
# decision map decides what this detector can read. Every other language is
# reported as out of scope.
LANGUAGES = list(nm.CYCLOMATIC_LANGS)


def main(argv: "list[str] | None" = None) -> int:
    parser = cli.new_parser("Rank functions by cyclomatic complexity.")
    parser.add_argument("--min", type=int, default=1, dest="minimum",
                        help="only show functions at least this complex (default: 1, show all)")
    cli.finish_parser(parser)
    args = parser.parse_args(argv)

    langs = cli.detect_and_gate(args, LANGUAGES)
    if langs is None:
        return 0

    spec = cli.MetricSpec(
        scorer=nm.cyclomatic,
        metric_key="cyclomatic",
        minimum_attr="minimum",
        column="COMPLEXITY",
        header=lambda shown, total, langs_str, tests_str: (
            f"Most complex {shown} of {total} functions by cyclomatic complexity "
            f"({langs_str}; tests {tests_str}):"
        ),
        empty_message=lambda langs_str: f"No functions at cyclomatic >= {args.minimum} (scanned: {langs_str}).",
    )
    return cli.run_metric_main(args, langs, spec)


if __name__ == "__main__":
    sys.exit(main())
