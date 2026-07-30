#!/usr/bin/env python3
"""Rank functions/methods by cognitive complexity (how hard they are to read).

A node-metric skill: it leans on the shared node_metric engine to score each
function by SonarSource-style cognitive complexity (every control structure
costs more the deeper it sits), then prints a small COGNITIVE / NAME / LOCATION
table. High scores flag the functions that are hardest to follow, the prime
"flatten and extract" refactor targets. The calling agent only ever sees the
table, never the AST.

Usage:
    python cognitive_complexity.py [PATH] [--top N] [--lang L ...] [--min N] [--include-tests]

PATH defaults to the current directory. Languages auto-detected unless --lang is
given (repeatable). Only languages the engine has nesting kinds for are scored.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
from sniff import harness as h  # pylint: disable=wrong-import-position
from sniff import node_metric as nm  # pylint: disable=wrong-import-position


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank functions by cognitive complexity.")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=10, help="how many to show (default: 10)")
    parser.add_argument("--lang", action="append", help="force a language (repeatable); skips auto-detect")
    parser.add_argument("--min", type=int, default=1, dest="minimum",
                        help="only show functions at least this complex (default: 1)")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    args = parser.parse_args()

    langs = sorted(set(args.lang)) if args.lang else sorted(h.detect_languages(args.path))
    if not langs:
        sys.exit(f"No supported source files found under {args.path!r}.")

    scored = nm.cognitive(args.path, langs=langs, include_tests=args.include_tests)
    scored = [m for m in scored if m.metrics.get("cognitive", 0) >= args.minimum]

    if not scored:
        scorable = ", ".join(l for l in langs if l in nm.NESTING_KINDS) or "none"
        print(f"No functions at cognitive >= {args.minimum} (scorable languages: {scorable}).")
        return

    header = (
        f"Hardest to read: {min(args.top, len(scored))} of {len(scored)} functions by cognitive complexity "
        f"({', '.join(langs)}; tests {'included' if args.include_tests else 'excluded'}):"
    )

    h.print_table(
        scored,
        columns=[
            ("COGNITIVE", lambda m: m.metrics["cognitive"]),
            ("NAME", lambda m: m.name),
            ("LOCATION", lambda m: m.location),
        ],
        sort_key=lambda m: m.metrics["cognitive"],
        top=args.top,
        header=header,
    )


if __name__ == "__main__":
    main()
