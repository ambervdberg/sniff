#!/usr/bin/env python3
"""Find string literals duplicated across 3+ files (SonarQube S1192).

Extracts string literals from TypeScript/JavaScript files and identifies strings
that appear in multiple distinct files. Useful for spotting constants that should
be centralized or extracted into a shared module. Uses the shared _ast-harness
helpers for the file walk (same ignore list and test handling as AST skills) so
behaviour stays consistent.

Usage:
    python no_duplicate_string.py [PATH] [--threshold N] [--min-len N] [--top N] [--include-tests]

PATH defaults to '.'; threshold (default 3) is how many distinct files a string must
appear in to be flagged; min-len (default 4) filters out very short strings that
produce noise (e.g., 'a', 'or'); top (default 10) limits output rows. Import/export
specifier strings (module paths in `import`/`export`/`require` statements) are
excluded, since those duplicates are structural, not smell.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from collections import defaultdict

# Import the shared engine from the sibling _ast-harness directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "_ast-harness"))
import harness as h  # pylint: disable=wrong-import-position


# Regex to extract string literals: "..." or '...' (non-empty, single-line only).
# Uses a negative lookahead to avoid matching escaped quotes inside the string.
STRING_LITERAL_RE = re.compile(
    r'''(?:[^\\]["']|^["'])'''  # start of string (not preceded by backslash)
    r'''(["'])'''  # capture quote style
    r'''(?:(?=(\\?))\2.)*?'''  # non-greedy match any char (escaped or not)
    r'''\1'''  # closing quote matches opening
)

# Simpler approach: match strings with basic escaping rules.
# Matches: "..." and '...' but allows \" and \' inside.
STRING_LITERAL_SIMPLE = re.compile(
    r'''(['"])(?:\\.|(?!\1).)*?\1'''
)

# Matches the text immediately before a string literal when that string is a
# module specifier: `import ... from '...'`, `export ... from '...'`, a
# side-effect `import '...'`, dynamic `import('...')`, or `require('...')`.
# Those duplicates (e.g. '@angular/core' repeated across files) are structural,
# not a code smell, so they are excluded before dedup counting.
IMPORT_SPECIFIER_PREFIX_RE = re.compile(
    r'(^\s*import\b|\bfrom\s*$|\brequire\(\s*$|\bimport\(\s*$)'
)


def extract_strings(path: str, min_len: int = 4) -> set[str]:
    """Extract string literals from a source file.

    Looks for both "..." and '...' patterns, filters out very short ones (noise),
    skips pure punctuation and common keywords. Returns set of normalized strings."""
    strings = set()

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return strings

    # Find all quoted strings.
    for match in STRING_LITERAL_SIMPLE.finditer(content):
        raw = match.group(0)
        # Remove quotes.
        value = raw[1:-1]

        # Skip empty strings.
        if not value:
            continue

        # Skip module specifiers: 'import ... from', 'require(', dynamic 'import('.
        line_start = content.rfind("\n", 0, match.start()) + 1
        line_prefix = content[line_start:match.start()]
        if IMPORT_SPECIFIER_PREFIX_RE.search(line_prefix):
            continue

        # Skip if too short (noise).
        if len(value) < min_len:
            continue

        # Skip pure whitespace or punctuation.
        if not any(c.isalnum() for c in value):
            continue

        # Skip common noise: single keywords.
        if value.lower() in {"true", "false", "null", "undefined", "this", "super"}:
            continue

        # Unescape common sequences for deduplication (treat \" and " as the same).
        normalized = value.replace(r"\"", '"').replace(r"\'", "'")
        strings.add(normalized)

    return strings


@dataclass
class DuplicateString:
    string: str
    count: int  # number of distinct files
    locations: list[str]  # file:line pointers (up to 3)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find string literals duplicated across 3+ files (SonarQube S1192)."
    )
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument(
        "--threshold", type=int, default=3,
        help="minimum number of distinct files a string must appear in to be flagged (default: 3)"
    )
    parser.add_argument(
        "--min-len", type=int, default=4,
        help="minimum string length to consider (filters noise; default: 4)"
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="how many to show (default: 10)"
    )
    parser.add_argument(
        "--include-tests", action="store_true",
        help="include *.spec.* / *.test.* files"
    )
    args = parser.parse_args()

    # Scan for source files.
    files = h.iter_source_files(args.path, include_tests=args.include_tests)
    if not files:
        sys.exit(f"No supported source files found under {args.path!r}.")

    # Extract strings from each file and track which files contain each string.
    string_files: dict[str, set[str]] = defaultdict(set)

    for filepath in files:
        extracted = extract_strings(filepath, min_len=args.min_len)
        for s in extracted:
            string_files[s].add(filepath)

    # Filter to strings appearing in threshold+ files and build output.
    duplicates = []
    for string, file_set in string_files.items():
        if len(file_set) >= args.threshold:
            # Take first 3 file locations as examples.
            locations = sorted(file_set)[:3]
            duplicates.append(
                DuplicateString(
                    string=string,
                    count=len(file_set),
                    locations=locations,
                )
            )

    if not duplicates:
        print(
            f"No strings duplicated in {args.threshold}+ files "
            f"(min length: {args.min_len}; tests {'included' if args.include_tests else 'excluded'})."
        )
        return

    # Sort by count descending.
    duplicates.sort(key=lambda d: d.count, reverse=True)

    header = (
        f"Strings duplicated in {args.threshold}+ distinct files "
        f"({len(duplicates)} found; tests {'included' if args.include_tests else 'excluded'}):"
    )

    h.print_table(
        duplicates,
        columns=[
            ("COUNT", lambda d: d.count),
            ("STRING", lambda d: d.string),
            ("EXAMPLE LOCATIONS", lambda d: ", ".join(d.locations[:3]) or "(unknown)"),
        ],
        sort_key=lambda d: d.count,
        top=args.top,
        header=header,
    )


if __name__ == "__main__":
    main()
