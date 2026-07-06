#!/usr/bin/env python3
"""Rank Angular components by inline-template size (extract-to-file smell).

A node-metric skill: it leans on the shared node_metric engine to count the
lines of each @Component's inline `template`, then prints a small LINES /
SELECTOR / LOCATION table. Big inline templates belong in their own `.html`
file; this finds the worst offenders. The calling agent only ever sees the
table, never the AST.

Usage:
    python large_inline_templates.py [PATH] [--top N] [--min N] [--include-tests]

PATH defaults to the current directory. Only TypeScript/TSX is scanned (where
Angular components live). Components using templateUrl are ignored.
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
    parser = argparse.ArgumentParser(description="Rank Angular components by inline-template line count.")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=10, help="how many to show (default: 10)")
    parser.add_argument("--min", type=int, default=1, dest="minimum",
                        help="only show templates at least this many lines (default: 1)")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    args = parser.parse_args()

    scored = nm.inline_template_lines(args.path, include_tests=args.include_tests)
    scored = [m for m in scored if m.metrics.get("template_lines", 0) >= args.minimum]

    if not scored:
        print(f"No Angular inline templates >= {args.minimum} lines under {args.path!r}.")
        return

    header = (
        f"Largest inline templates: {min(args.top, len(scored))} of {len(scored)} components "
        f"(TypeScript/TSX; tests {'included' if args.include_tests else 'excluded'}):"
    )

    h.print_table(
        scored,
        columns=[
            ("LINES", lambda m: m.metrics["template_lines"]),
            ("SELECTOR", lambda m: m.name),
            ("LOCATION", lambda m: m.location),
        ],
        sort_key=lambda m: m.metrics["template_lines"],
        top=args.top,
        header=header,
    )


if __name__ == "__main__":
    main()
