#!/usr/bin/env python3
"""Rank files by the debt their own comments admit to.

TODO, FIXME, HACK and XXX are debt the authors already found, wrote down, and
moved on from, which makes it the cheapest debt in the repo to act on. The
markers live in comments and read the same in every language, so this is the
file-metric engine: no AST, no ast-grep, just a scan of each file's comments.

Usage:
    python -m sniff.detectors.self_admitted_debt [PATH] [--markers A,B] [--top N] [--include-tests]

PATH defaults to '.'.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass

from sniff import harness as h

NAME = "self-admitted-debt"
TITLE = "Self-admitted technical debt"
DEFAULT_ARGS: "list[str]" = []

# The scan is over comment text, which every language spells with one of a
# handful of openers, so every language the file walk recognizes is covered.
LANGUAGES = list(h.ALL_LANGUAGES)

DEFAULT_MARKERS = ("TODO", "FIXME", "HACK", "XXX")

# What starts a comment, across the supported languages: `//`, `#`, `/*`, and the
# `*` that continues a block comment. A marker is only debt when it sits in prose
# the compiler ignores; the same word inside a string is usually a UI label or a
# test fixture.
COMMENT_OPENER_RE = re.compile(r"(//|#|/\*|\*|<!--|--\s)")


@dataclass
class DebtFile:
    """One file's admitted debt: how much, and of which kinds."""

    file: str
    markers: Counter

    @property
    def count(self) -> int:
        return sum(self.markers.values())

    @property
    def kinds(self) -> str:
        """Which markers, most common first: `TODO 3, FIXME 1`."""
        return ", ".join(f"{marker} {n}" for marker, n in self.markers.most_common())


def count_markers(path: str, markers: "tuple[str, ...]") -> Counter:
    """Count debt markers in one file's comments."""
    pattern = re.compile(rf"\b({'|'.join(re.escape(m) for m in markers)})\b")
    found: Counter = Counter()

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                found.update(_markers_in_comment(line, pattern))
    except OSError:
        return found

    return found


def _markers_in_comment(line: str, pattern: "re.Pattern[str]") -> "list[str]":
    """The markers on one line that a comment opener precedes."""
    return [match.group(1) for match in pattern.finditer(line)
            if COMMENT_OPENER_RE.search(line[:match.start()])]


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rank files by TODO/FIXME/HACK/XXX markers in their comments."
    )
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument(
        "--markers", default=",".join(DEFAULT_MARKERS),
        help=f"comma-separated markers to count (default: {','.join(DEFAULT_MARKERS)})"
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="how many files to show (default: 10)"
    )
    parser.add_argument(
        "--include-tests", action="store_true",
        help="include *.spec.* / *.test.* files"
    )
    parser.add_argument(
        "--extra-ignore", action="append", default=[],
        help="glob to exclude, relative to PATH (repeatable)"
    )
    args = parser.parse_args(argv)

    markers = tuple(m.strip() for m in args.markers.split(",") if m.strip())
    if not markers:
        sys.exit("error: --markers needs at least one marker.")

    files = h.iter_source_files(args.path, include_tests=args.include_tests,
                                extra_ignores=args.extra_ignore)
    if not files:
        sys.exit(f"No supported source files found under {args.path!r}.")

    debt = [DebtFile(file=path, markers=counted)
            for path in files
            if (counted := count_markers(path, markers))]

    if not debt:
        print(
            f"No {'/'.join(markers)} markers found "
            f"(tests {'included' if args.include_tests else 'excluded'})."
        )
        return 0

    total = sum(d.count for d in debt)
    header = (
        f"Most admitted debt: {min(args.top, len(debt))} of {len(debt)} files "
        f"carrying {total} {'/'.join(markers)} markers "
        f"(tests {'included' if args.include_tests else 'excluded'}):"
    )

    h.print_table(
        debt,
        columns=[
            ("MARKERS", lambda d: d.count),
            ("KINDS", lambda d: d.kinds),
            ("FILE", lambda d: d.file),
        ],
        sort_key=lambda d: d.count,
        top=args.top,
        header=header,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
