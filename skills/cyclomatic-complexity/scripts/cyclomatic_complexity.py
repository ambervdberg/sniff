#!/usr/bin/env python3
"""Rank functions/methods by cyclomatic complexity (SonarSource S1541).

A node-metric skill: it leans on the shared node_metric engine to score each
function by its number of independent paths (1 + decision points), then prints a
small COMPLEXITY / NAME / LOCATION table. High-complexity functions are the prime
"too many branches, split or simplify" refactor targets. The calling agent only
ever sees the table, never the AST.

Usage:
    python cyclomatic_complexity.py [PATH] [--top N] [--lang L ...] [--min N] [--include-tests]

PATH defaults to the current directory. Languages auto-detected unless --lang is
given (repeatable). Only languages the engine has decision kinds for are scored.
"""

from __future__ import annotations

import argparse
import os
import sys

# Import the shared engines from the sibling _ast-harness directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_ast-harness"))
import harness as h
import node_metric as nm


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank functions by cyclomatic complexity (S1541).")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=10, help="how many to show (default: 10)")
    parser.add_argument("--lang", action="append", help="force a language (repeatable); skips auto-detect")
    parser.add_argument("--min", type=int, default=1, dest="minimum",
                        help="only show functions at least this complex (default: 1, show all)")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    args = parser.parse_args()

    langs = sorted(set(args.lang)) if args.lang else sorted(h.detect_languages(args.path))
    if not langs:
        sys.exit(f"No supported source files found under {args.path!r}.")

    scored = nm.cyclomatic(args.path, langs=langs, include_tests=args.include_tests)
    scored = [m for m in scored if m.metrics.get("cyclomatic", 0) >= args.minimum]

    if not scored:
        scorable = ", ".join(l for l in langs if l in nm.DECISION_KINDS) or "none"
        print(f"No functions at cyclomatic >= {args.minimum} (scorable languages: {scorable}).")
        return

    header = (
        f"Most complex {min(args.top, len(scored))} of {len(scored)} functions by cyclomatic complexity "
        f"({', '.join(langs)}; tests {'included' if args.include_tests else 'excluded'}):"
    )

    h.print_table(
        scored,
        columns=[
            ("COMPLEXITY", lambda m: m.metrics["cyclomatic"]),
            ("NAME", lambda m: m.name),
            ("LOCATION", lambda m: m.location),
        ],
        sort_key=lambda m: m.metrics["cyclomatic"],
        top=args.top,
        header=header,
    )


if __name__ == "__main__":
    main()
