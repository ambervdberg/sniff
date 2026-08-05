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

## Usage

Run the detector through the installed sniff CLI:

1. If `sniff version` fails: `uv tool install sniff-smells`.
2. Run: `sniff --only largest-files DIR [--top N] [--include-tests]`
3. Report the table; do not paste raw file contents.

**Print the entire table verbatim.** It IS the answer. Do NOT summarize it to
prose or drop rows. You may add ONE takeaway line after the table (e.g. the
single biggest file), but the full table comes first and in full.

## Caveats

- Counts **non-blank lines**, not comment-aware SLOC. A big file is a split
  *candidate*, not a verdict, generated or data files (e.g. a big constants table)
  can be legitimately large.
- Only known source extensions are counted (same set the AST skills detect).
