#!/usr/bin/env python3
"""Find string literals duplicated across 3+ files.

Extracts string literals from every supported source file and identifies strings
that appear in multiple distinct files. Useful for spotting constants that should
be centralized or extracted into a shared module. Uses the shared harness
helpers for the file walk (same ignore list and test handling as AST detectors)
so behaviour stays consistent.

Usage:
    python -m sniff.detectors.no_duplicate_string [PATH] [--threshold N] [--min-len N] [--top N] [--include-tests]

PATH defaults to '.'; threshold (default 3) is how many distinct files a string must
appear in to be flagged; min-len (default 4) filters out very short strings that
produce noise (e.g., 'a', 'or'); top (default 10) limits output rows. Import/export
specifier strings (module paths in `import`/`export`/`require` statements) are
excluded, since those duplicates are structural, not smell.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from collections import defaultdict

from sniff import harness as h

NAME = "no-duplicate-string"
TITLE = "Duplicated string literals"
DEFAULT_ARGS: "list[str]" = []

# Literals are found by regex, not by a parser, so every language the file walk
# recognizes is covered.
LANGUAGES = list(h.ALL_LANGUAGES)

# No parser involved, so this one still runs when ast-grep is missing.
NEEDS_AST_GREP = False


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

# Strings that repeat across files as language or library idiom, not as
# extractable constants: encoding names passed to open(), and argparse action
# names. Dunders (e.g. __main__) are matched separately by shape.
IDIOM_STOPLIST = {
    "utf-8", "utf8", "ascii", "latin-1",
    "store", "store_true", "store_false", "store_const", "append", "count", "extend",
}

# A quoted forward-reference type annotation, e.g. "list[str] | None" or
# "dict[str, int]". Only strings containing type syntax ([ or |) built purely
# from identifiers, dots, brackets, commas, pipes and spaces qualify.
TYPE_EXPRESSION_RE = re.compile(r"[\w.\[\],| ]+")


def is_idiom(value: str) -> bool:
    """True for strings whose cross-file repetition is idiom, not a smell."""
    if value.startswith("__") and value.endswith("__"):
        return True
    if value in IDIOM_STOPLIST:
        return True
    if ("[" in value or "|" in value) and TYPE_EXPRESSION_RE.fullmatch(value):
        return True
    return False


# Matches the text immediately before a string literal when that string is a
# module specifier: `import ... from '...'`, `export ... from '...'`, a
# side-effect `import '...'`, dynamic `import('...')`, or `require('...')`.
# Those duplicates (e.g. '@angular/core' repeated across files) are structural,
# not a code smell, so they are excluded before dedup counting.
IMPORT_SPECIFIER_PREFIX_RE = re.compile(
    r'(^\s*import\b|\bfrom\s*$|\brequire\(\s*$|\bimport\(\s*$)'
)


def extract_strings(path: str, min_len: int = 4) -> "dict[str, int]":
    """Extract string literals from a source file.

    Looks for both "..." and '...' patterns, filters out very short ones (noise),
    skips pure punctuation, common keywords and idiom strings (see is_idiom).
    Returns a dict mapping each normalized string to the line number of its
    first occurrence in the file."""
    strings: "dict[str, int]" = {}

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

        # Skip idiom strings: dunders, encodings, argparse actions, quoted
        # type annotations. They repeat by convention, not by copy-paste.
        if is_idiom(value):
            continue

        # Unescape common sequences for deduplication (treat \" and " as the same).
        normalized = value.replace(r"\"", '"').replace(r"\'", "'")

        # Record the first occurrence's line for the file:line location output.
        line = content.count("\n", 0, match.start()) + 1
        strings.setdefault(normalized, line)

    return strings


@dataclass
class DuplicateString:
    string: str
    count: int  # number of distinct files
    locations: "list[str]"  # file:line pointers (up to 3)


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find string literals duplicated across 3+ files."
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
    parser.add_argument(
        "--extra-ignore", action="append", default=[],
        help="glob to exclude, relative to PATH (repeatable)"
    )
    args = parser.parse_args(argv)

    # Scan for source files.
    files = h.iter_source_files(args.path, include_tests=args.include_tests,
                                 extra_ignores=args.extra_ignore)
    if not files:
        sys.exit(f"No supported source files found under {args.path!r}.")

    # Extract strings from each file and track, per string, the line of its
    # first occurrence in each file that contains it.
    string_files: "dict[str, dict[str, int]]" = defaultdict(dict)

    for filepath in files:
        extracted = extract_strings(filepath, min_len=args.min_len)
        for s, line in extracted.items():
            string_files[s][filepath] = line

    # Filter to strings appearing in threshold+ files and build output.
    duplicates = []
    for string, file_lines in string_files.items():
        if len(file_lines) >= args.threshold:
            # Take first 3 file:line locations as examples.
            locations = [f"{f}:{file_lines[f]}" for f in sorted(file_lines)[:3]]
            duplicates.append(
                DuplicateString(
                    string=string,
                    count=len(file_lines),
                    locations=locations,
                )
            )

    if not duplicates:
        print(
            f"No strings duplicated in {args.threshold}+ files "
            f"(min length: {args.min_len}; tests {'included' if args.include_tests else 'excluded'})."
        )
        return 0

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
