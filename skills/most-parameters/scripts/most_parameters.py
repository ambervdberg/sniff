#!/usr/bin/env python3
"""Rank functions/methods by parameter count (long-parameter-list smell).

A node-metric skill: it leans on the shared node_metric engine to count each
function's formal parameters, then prints a small PARAMS / NAME / LOCATION table.
Functions with many parameters are prime "introduce a parameter object / split
this" refactor targets. The calling agent only ever sees the table, never the AST.

Usage:
    python most_parameters.py [PATH] [--top N] [--lang L ...] [--min N] [--include-tests]

PATH defaults to the current directory. Languages auto-detected unless --lang is
given (repeatable). Only languages the engine has parameter kinds for are scored.
"""

from __future__ import annotations

import argparse
import os
import sys

# Import the shared engines from the sibling _ast-harness directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_ast-harness"))
import harness as h  # pylint: disable=wrong-import-position
import node_metric as nm  # pylint: disable=wrong-import-position


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank functions by parameter count.")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=10, help="how many to show (default: 10)")
    parser.add_argument("--lang", action="append", help="force a language (repeatable); skips auto-detect")
    parser.add_argument("--min", type=int, default=3, dest="minimum",
                        help="only show functions with at least this many params (default: 3, ignores <=2)")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    args = parser.parse_args()

    langs = sorted(set(args.lang)) if args.lang else sorted(h.detect_languages(args.path))
    if not langs:
        sys.exit(f"No supported source files found under {args.path!r}.")

    scored = nm.params(args.path, langs=langs, include_tests=args.include_tests)
    scored = [m for m in scored if m.metrics.get("params", 0) >= args.minimum]

    if not scored:
        scorable = ", ".join(l for l in langs if l in nm.PARAM_LIST_KINDS) or "none"
        print(f"No functions with >= {args.minimum} params (scorable languages: {scorable}).")
        return

    header = (
        f"Most parameters: {min(args.top, len(scored))} of {len(scored)} functions "
        f"({', '.join(langs)}; tests {'included' if args.include_tests else 'excluded'}):"
    )

    h.print_table(
        scored,
        columns=[
            ("PARAMS", lambda m: m.metrics["params"]),
            ("NAME", lambda m: m.name),
            ("LOCATION", lambda m: m.location),
        ],
        sort_key=lambda m: m.metrics["params"],
        top=args.top,
        header=header,
    )


if __name__ == "__main__":
    main()
