#!/usr/bin/env python3
"""Rank functions/methods by their maximum control-flow nesting depth.

A node-metric skill: it leans on the shared node_metric engine to score each
function by how deeply its loops/branches/try blocks stack, then prints the
small DEPTH / NAME / LOCATION table. Deeply nested functions are the prime
"extract a method / invert this guard" refactor targets. The calling agent only
ever sees the table, never the AST.

Usage:
    python -m sniff.detectors.deepest_nesting [PATH] [--top N] [--lang L ...] [--min-depth N] [--include-tests]

PATH defaults to the current directory. Languages are auto-detected unless
--lang is given (repeatable). Only languages the engine has nesting kinds for
are scored.
"""

from __future__ import annotations

import sys

from sniff import node_metric as nm
from sniff.detectors import _node_metric_cli as cli

NAME = "deepest-nesting"
TITLE = "Deepest nested blocks"
DEFAULT_ARGS: "list[str]" = []

# Depth needs control-flow node kinds, so the engine's nesting map decides what
# this detector can read. Every other language is reported as out of scope.
LANGUAGES = list(nm.SUPPORTED_LANGS)


def main(argv: "list[str] | None" = None) -> int:
    parser = cli.new_parser("Rank functions by control-flow nesting depth.")
    parser.add_argument("--min-depth", type=int, default=1,
                        help="only show functions at least this deep (default: 1, hide flat ones)")
    cli.finish_parser(parser)
    args = parser.parse_args(argv)

    langs = cli.detect_and_gate(args, LANGUAGES)
    if langs is None:
        return 0

    spec = cli.MetricSpec(
        scorer=nm.nesting_depth,
        metric_key="depth",
        minimum_attr="min_depth",
        column="DEPTH",
        header=lambda shown, total, langs_str, tests_str: (
            f"Deepest {shown} of {total} functions with nesting depth "
            f">= {args.min_depth} ({langs_str}; tests {tests_str}):"
        ),
        empty_message=lambda langs_str: f"No functions at nesting depth >= {args.min_depth} (scanned: {langs_str}).",
    )
    return cli.run_metric_main(args, langs, spec)


if __name__ == "__main__":
    sys.exit(main())
