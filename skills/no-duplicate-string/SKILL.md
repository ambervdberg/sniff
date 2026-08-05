---
name: no-duplicate-string
description: >-
  Find string literals that appear in 3+ files across the codebase.
  Use when the user wants to identify hardcoded strings that should be extracted into
  a shared constant or config, hunts for strings duplicated across multiple modules,
  or asks to find magic strings that repeat. Returns a small ranked table showing the
  most common strings, not the files themselves.
---

# no-duplicate-string

Find hardcoded string literals that repeat across 3+ distinct files. Identifying
duplicated strings helps surface values that should be centralized (shared configs,
constants modules, environment variables). This is the **file-metric** engine: no
AST, just regex extraction per file, using the same ignore list and test handling
as the AST skills.

## Usage

Run the detector through the installed sniff CLI:

1. Ensure sniff is installed. Try `sniff version`. If it fails, install it:
   `uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`).
2. Run: `sniff --only no-duplicate-string DIR [--threshold N] [--min-len N]
   [--top N] [--include-tests]`
3. Report the table; do not paste raw file contents.

Flags:
- `--threshold N` (default 3): minimum distinct files a string must appear in to
  be flagged.
- `--min-len N` (default 4): minimum string length to avoid noise.
- `--top N` (default 10): how many strings to show.

**Print the entire table verbatim.** It IS the answer. Do NOT summarize it to
prose or drop rows. You may add ONE takeaway line after the table (e.g. the
most-duplicated string), but the full table comes first and in full.

## Caveats

- Extraction is regex-based and includes both `"..."` and `'...'` patterns;
  template literals (backticks) are not yet supported.
- Very short strings are filtered by default (`--min-len 4`) to reduce noise.
  Common keywords like `true`, `false`, `null`, `undefined` are also skipped.
- Duplicated strings in comments or documentation are not detected (analysis is
  source-code strings only).
- String normalization treats `\"` and `"` the same for deduplication purposes.
