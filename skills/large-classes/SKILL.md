---
name: large-classes
description: >-
  Find the largest / longest classes in a codebase, ranked by line count, using ast-grep. Use when hunting for god classes or refactor candidates. Returns a small ranked table, not source.
---

# Largest classes by line count

Largest classes by line count

## Why this exists

The naive way to answer this is to read files or dump AST JSON into the
conversation, both of which burn thousands of tokens. This skill runs all of
that through the installed sniff CLI: it runs `ast-grep`, parses the JSON internally, folds
nested matches into their parent, and prints a small ranked table. You only ever
see the table. Never pipe raw `ast-grep --json` output into your own context to
re-rank it by hand.

## Usage

Run the detector through the installed sniff CLI:

1. Ensure sniff is installed. Try `sniff version`. If it fails, install it:
   `uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`),
   and if `ast-grep` is missing: `uv tool install ast-grep-cli`.
2. Run: `sniff --only large-classes [DIR] [--top N] [--lang LANG]
   [--include-tests]`
3. Report the table; do not paste raw file contents.

**Print the entire table verbatim.** It IS the answer. Do NOT replace it with a
summary or describe it in prose; the user wants every row. You may add ONE
optional takeaway line after the table, but the full table must appear first and
in full. Do not re-read listed files unless the user then asks you to actually
act on one.

## Caveats

- Ranked by physical **line span**, not a complexity metric. A long match is a
  *candidate* worth looking at, not a verdict.
- Nested matches are folded into their parent so the same code is not counted twice.
- Languages covered: typescript, tsx, javascript, python. Another language is reported
  as out of scope rather than as zero classes; `sniff --list` shows every detector's coverage.
- Names are best-effort from the definition's first line; the `LOCATION` column is
  authoritative.
