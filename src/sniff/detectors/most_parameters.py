#!/usr/bin/env python3
"""Rank functions/methods by parameter count (long-parameter-list smell).

A node-metric skill: it leans on the shared node_metric engine to count each
function's formal parameters, then prints a small PARAMS / NAME / LOCATION table.
Functions with many parameters are prime "introduce a parameter object / split
this" refactor targets. The calling agent only ever sees the table, never the AST.

Usage:
    python -m sniff.detectors.most_parameters [PATH] [--top N] [--lang L ...] [--min N] [--include-tests]

PATH defaults to the current directory. Languages auto-detected unless --lang is
given (repeatable). Only languages the engine has parameter kinds for are scored.
"""

from __future__ import annotations

import sys

from sniff import node_metric as nm
from sniff.detectors import _node_metric_cli as cli

NAME = "most-parameters"
TITLE = "Methods with most parameters"
DEFAULT_ARGS: "list[str]" = []

# Counting parameters needs per-language parameter-list node kinds, so the
# engine's map decides what this detector can read. Every other language is
# reported as out of scope.
LANGUAGES = list(nm.PARAM_LANGS)


def main(argv: "list[str] | None" = None) -> int:
    parser = cli.new_parser("Rank functions by parameter count.")
    parser.add_argument("--min", type=int, default=3, dest="minimum",
                        help="only show functions with at least this many params (default: 3, ignores <=2)")
    cli.finish_parser(parser)
    args = parser.parse_args(argv)

    langs = cli.detect_and_gate(args, LANGUAGES)
    if langs is None:
        return 0

    return cli.run_metric_main(
        args, langs,
        scorer=nm.params,
        metric_key="params",
        minimum=args.minimum,
        column="PARAMS",
        header=lambda shown, total, langs_str, tests_str: (
            f"Most parameters: {shown} of {total} functions "
            f"({langs_str}; tests {tests_str}):"
        ),
        empty_message=lambda langs_str: f"No functions with >= {args.minimum} params (scanned: {langs_str}).",
    )


if __name__ == "__main__":
    sys.exit(main())
