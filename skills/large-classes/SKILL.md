---
name: large-classes
description: >-
  Find the largest / longest classes in a codebase, ranked by line count, using ast-grep. Use when hunting for god classes or refactor candidates. Returns a small ranked table, not source.
---

# Largest classes by line count

Largest classes by line count

## Why this exists

The naive way to answer this is to read files or dump AST JSON into the
conversation, both of which burn thousands of tokens. This skill pushes all of
that into a bundled script: it runs `ast-grep`, parses the JSON internally, folds
nested matches into their parent, and prints a small ranked table. You only ever
see the table. Never pipe raw `ast-grep --json` output into your own context to
re-rank it by hand.

## Prerequisites

- `ast-grep` on PATH (`ast-grep --version`). Install: https://ast-grep.github.io
- Python 3 to run the bundled script.

## Usage

```bash
python "<skill_dir>/scripts/large-classes.py" [PATH] [--top N] [--lang L] [--include-tests]
```

`<skill_dir>` is the directory containing this SKILL.md. `PATH` defaults to the
current directory; languages auto-detect from file extensions unless `--lang` is
given; test files are excluded unless `--include-tests`.

## Relaying the result

**Print the entire table to the user verbatim.** It IS the answer. Do NOT replace
it with a summary, collapse it to "the largest is X", or describe it in prose, the
user wants every row. You may add ONE optional takeaway line after the table, but
the full table must appear first and in full. Do not re-read the listed files
unless the user then asks you to actually act on one.

## Caveats

- Ranked by physical **line span**, not a complexity metric. A long match is a
  *candidate* worth looking at, not a verdict.
- Nested matches are folded into their parent so the same code is not counted twice.
- Languages covered: typescript, tsx, javascript. If one you expected shows nothing, pass `--lang`
  explicitly and sanity-check.
- Names are best-effort from the definition's first line; the `LOCATION` column is
  authoritative.
