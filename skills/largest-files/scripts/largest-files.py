#!/usr/bin/env python3
"""Rank the largest source files by non-blank line count.

The file-metric engine: no AST, just a line count per file. Big files are split
candidates. Uses the shared _ast-harness helpers for the file walk (same ignore
list and test handling as the AST skills) so behaviour stays consistent.

Usage:
    python largest-files.py [PATH] [--top N] [--include-tests]
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

# Import the shared engine from the sibling _ast-harness directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_ast-harness"))
import harness as h  # noqa: E402


@dataclass
class FileStat:
    file: str
    lines: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank the largest source files by non-blank line count.")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=20, help="how many to show (default: 20)")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    args = parser.parse_args()

    files = h.iter_source_files(args.path, include_tests=args.include_tests)
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


if __name__ == "__main__":
    main()
