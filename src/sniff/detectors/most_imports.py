#!/usr/bin/env python3
"""Rank files by number of import statements.

Files with many imports signal high coupling and are likely god files or good
candidates for refactoring. Uses ast-grep to find import declarations per file.

Usage:
    python -m sniff.detectors.most_imports [PATH] [--top N] [--include-tests]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass

from sniff import harness as h

NAME = "most-imports"
TITLE = "Files by import count"
DEFAULT_ARGS: "list[str]" = []

# The node kinds that count as "an import" per language. Python spells a plain
# `import x` and a `from x import y` as two different kinds, so both are listed.
# Every language absent here is reported as out of scope.
LANG_KINDS = {
    "typescript": ["import_statement"],
    "tsx": ["import_statement"],
    "javascript": ["import_statement"],
    "python": ["import_statement", "import_from_statement"],
}

LANGUAGES = sorted(LANG_KINDS)


@dataclass
class FileStat:
    file: str
    count: int


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description="Rank files by import statement count.")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=10, help="how many to show (default: 10)")
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    parser.add_argument("--extra-ignore", action="append", default=[],
                        help="glob to exclude, relative to PATH (repeatable)")
    args = parser.parse_args(argv)

    present = sorted(h.detect_languages(args.path, args.extra_ignore))
    if not present:
        sys.exit(f"No supported source files found under {args.path!r}.")

    langs = h.covered_languages(present, LANGUAGES)
    if not langs:
        print(h.not_applicable(present, LANGUAGES))
        return 0

    # Scan for every import node kind these languages use.
    matches = h.run(
        LANG_KINDS,
        args.path,
        lang=langs,
        include_tests=args.include_tests,
        with_name=False,
        extra_ignores=args.extra_ignore,
    )

    if not matches:
        print(f"No import statements found under {args.path!r}.")
        return 0

    # Count imports per file.
    counts: dict[str, int] = defaultdict(int)
    for match in matches:
        counts[match.file] += 1

    stats = [FileStat(file=f, count=c) for f, c in counts.items()]

    header = (
        f"Files by import count: {min(args.top, len(stats))} of {len(stats)} files "
        f"({', '.join(langs)}; tests {'included' if args.include_tests else 'excluded'}):"
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
