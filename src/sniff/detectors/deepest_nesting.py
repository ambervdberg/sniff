#!/usr/bin/env python3
"""Rank functions/methods by their maximum control-flow nesting depth (S134).

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

import argparse
import sys

from sniff import harness as h
from sniff import node_metric as nm

NAME = "deepest-nesting"
TITLE = "Deepest nested blocks"
DEFAULT_ARGS: "list[str]" = []


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description="Rank functions by control-flow nesting depth (S134).")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=10, help="how many to show (default: 10)")
    parser.add_argument("--lang", action="append", help="force a language (repeatable); skips auto-detect")
    parser.add_argument("--min-depth", type=int, default=1,
                        help="only show functions at least this deep (default: 1, hide flat ones)")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    parser.add_argument("--extra-ignore", action="append", default=[],
                        help="glob to exclude, relative to PATH (repeatable)")
    args = parser.parse_args(argv)

    langs = sorted(set(args.lang)) if args.lang else sorted(h.detect_languages(args.path, args.extra_ignore))
    if not langs:
        sys.exit(f"No supported source files found under {args.path!r}.")

    scored = nm.nesting_depth(args.path, langs=langs, include_tests=args.include_tests,
                               extra_ignores=args.extra_ignore)

    # Drop functions below the threshold so the table is all genuine smells.
    scored = [m for m in scored if m.metrics.get("depth", 0) >= args.min_depth]

    if not scored:
        scorable = ", ".join(l for l in langs if l in nm.NESTING_KINDS) or "none"
        print(f"No functions at nesting depth >= {args.min_depth} (scorable languages: {scorable}).")
        return 0

    header = (
        f"Deepest {min(args.top, len(scored))} of {len(scored)} functions by nesting depth "
        f"({', '.join(langs)}; tests {'included' if args.include_tests else 'excluded'}):"
    )

    h.print_table(
        scored,
        columns=[
            ("DEPTH", lambda m: m.metrics["depth"]),
            ("NAME", lambda m: m.name),
            ("LOCATION", lambda m: m.location),
        ],
        sort_key=lambda m: m.metrics["depth"],
        top=args.top,
        header=header,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
