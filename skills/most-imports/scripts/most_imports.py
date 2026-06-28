#!/usr/bin/env python3
"""Rank files by number of import statements.

Files with many imports signal high coupling and are likely god files or good
candidates for refactoring. Uses ast-grep to find import declarations per file.

Usage:
    python most_imports.py [PATH] [--top N] [--include-tests]
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from dataclasses import dataclass

# Import the shared engine from the sibling _ast-harness directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_ast-harness"))
import harness as h  # noqa: E402


@dataclass
class FileStat:
    file: str
    count: int


def main() -> None:
    parser = argparse.ArgumentParser(description="Rank files by import statement count.")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=20, help="how many to show (default: 20)")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    args = parser.parse_args()

    # Supported languages for import counting: TypeScript, JavaScript variants.
    langs = ["typescript", "tsx", "javascript"]

    # Scan for all import_statement nodes.
    matches = h.run(
        {"typescript": ["import_statement"], "tsx": ["import_statement"], "javascript": ["import_statement"]},
        args.path,
        lang=langs,
        include_tests=args.include_tests,
        with_name=False,
    )

    if not matches:
        print(f"No import statements found under {args.path!r}.")
        return

    # Count imports per file.
    counts: dict[str, int] = defaultdict(int)
    for match in matches:
        counts[match.file] += 1

    stats = [FileStat(file=f, count=c) for f, c in counts.items()]

    header = (
        f"Files by import count: {min(args.top, len(stats))} of {len(stats)} files "
        f"(TypeScript/JavaScript; tests {'included' if args.include_tests else 'excluded'}):"
    )

    h.print_table(
        stats,
        columns=[
            ("COUNT", lambda s: s.count),
            ("FILE", lambda s: s.file),
        ],
        sort_key=lambda s: s.count,
        top=args.top,
        header=header,
    )


if __name__ == "__main__":
    main()
