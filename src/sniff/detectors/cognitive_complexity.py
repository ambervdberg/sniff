#!/usr/bin/env python3
"""Rank functions/methods by cognitive complexity (how hard they are to read).

A node-metric skill: it leans on the shared node_metric engine to score each
function by cognitive complexity (every control structure
costs more the deeper it sits), then prints a small COGNITIVE / NAME / LOCATION
table. High scores flag the functions that are hardest to follow, the prime
"flatten and extract" refactor targets. The calling agent only ever sees the
table, never the AST.

Usage:
    python -m sniff.detectors.cognitive_complexity [PATH] [--top N] [--lang L ...] [--min N] [--include-tests]

PATH defaults to the current directory. Languages auto-detected unless --lang is
given (repeatable). Only languages the engine has nesting kinds for are scored.
"""

from __future__ import annotations

import sys

from sniff import node_metric as nm
from sniff.detectors import _node_metric_cli as cli

NAME = "cognitive-complexity"
TITLE = "High cognitive complexity methods"
DEFAULT_ARGS: "list[str]" = []

# Scoring needs control-flow node kinds, so the engine's nesting map decides what
# this detector can read. Every other language is reported as out of scope.
LANGUAGES = list(nm.SUPPORTED_LANGS)


def main(argv: "list[str] | None" = None) -> int:
    parser = cli.new_parser("Rank functions by cognitive complexity.")
    parser.add_argument("--min", type=int, default=1, dest="minimum",
                        help="only show functions at least this complex (default: 1)")
    cli.finish_parser(parser)
    args = parser.parse_args(argv)

    langs = cli.detect_and_gate(args, LANGUAGES)
    if langs is None:
        return 0

    spec = cli.MetricSpec(
        scorer=nm.cognitive,
        metric_key="cognitive",
        minimum_attr="minimum",
        column="COGNITIVE",
        header=lambda shown, total, langs_str, tests_str: (
            f"Hardest to read: {shown} of {total} functions with cognitive complexity "
            f">= {args.minimum} ({langs_str}; tests {tests_str}):"
        ),
        empty_message=lambda langs_str: f"No functions at cognitive >= {args.minimum} (scanned: {langs_str}).",
    )
    return cli.run_metric_main(args, langs, spec)


if __name__ == "__main__":
    sys.exit(main())
