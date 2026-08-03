#!/usr/bin/env python3
"""Rank the largest source files by non-blank line count.

The file-metric engine: no AST, just a line count per file. Big files are split
candidates. Uses the shared harness helpers for the file walk (same ignore
list and test handling as the AST detectors) so behaviour stays consistent.

Usage:
    python -m sniff.detectors.largest_files [PATH] [--top N] [--include-tests]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from sniff import harness as h

NAME = "largest-files"
TITLE = "Largest files"
DEFAULT_ARGS: "list[str]" = []

# Counting lines needs no parser, so every language the file walk recognizes is
# covered.
LANGUAGES = list(h.ALL_LANGUAGES)

# No parser: the file walk and a line count are the whole detector, so this one
# still runs when ast-grep is missing.
NEEDS_AST_GREP = False


@dataclass
class FileStat:
    file: str
    lines: int


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description="Rank the largest source files by non-blank line count.")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=10, help="how many to show (default: 10)")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    parser.add_argument("--extra-ignore", action="append", default=[],
                        help="glob to exclude, relative to PATH (repeatable)")
    args = parser.parse_args(argv)

    files = h.iter_source_files(args.path, include_tests=args.include_tests,
                                 extra_ignores=args.extra_ignore)
    if not files:
        sys.exit(f"No supported source files found under {args.path!r}.")

    stats = [FileStat(file=f, lines=h.count_code_lines(f)) for f in files]

    header = (
        f"Largest {min(args.top, len(stats))} of {len(stats)} source files "
        f"(non-blank lines; tests {'included' if args.include_tests else 'excluded'}):"
    )

    h.print_table(
        stats,
        columns=[
            ("LINES", lambda s: s.lines),
            ("FILE", lambda s: s.file),
        ],
        sort_key=lambda s: s.lines,
        top=args.top,
        header=header,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
