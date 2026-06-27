---
name: largest-files
description: >-
  Find the largest / longest source files in a codebase, ranked by non-blank line
  count. Use when the user wants to know which files are too big, hunts for files
  to split up, asks "what's the biggest file", wants a size hotspot list, or looks
  for god files / split candidates. Returns one small ranked table, not the files
  themselves, so it answers for a tiny number of tokens.
---

# largest-files

Rank the biggest source files by non-blank line count. Big files are split
candidates. This is the **file-metric** engine: no AST, just a count per file,
using the same ignore list and test handling as the AST skills.

## Prerequisites

- Python 3. (No `ast-grep` needed, this engine does not touch the AST.)

## Usage

```bash
python "<skill_dir>/scripts/largest-files.py" [PATH] [--top N] [--include-tests]
```

`<skill_dir>` is this skill's directory. `PATH` defaults to the current directory;
test files (`*.spec.*` / `*.test.*`) are excluded unless `--include-tests`;
vendored/build dirs (`node_modules`, `dist`, `.astro`, ...) are always skipped.

## Relaying the result

**Print the entire table to the user verbatim.** It IS the answer. Do NOT summarize
it to prose or drop rows. You may add ONE takeaway line after the table (e.g. the
single biggest file), but the full table comes first and in full.

## Caveats

- Counts **non-blank lines**, not comment-aware SLOC. A big file is a split
  *candidate*, not a verdict, generated or data files (e.g. a big constants table)
  can be legitimately large.
- Only known source extensions are counted (same set the AST skills detect).
