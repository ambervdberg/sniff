---
name: no-duplicate-string
description: >-
  Find string literals that appear in 3+ files across the codebase (SonarQube S1192).
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

## Prerequisites

- Python 3. (No `ast-grep` needed, this engine does not touch the AST.)

## Usage

```bash
python "<skill_dir>/scripts/no_duplicate_string.py" [PATH] [--threshold N] [--min-len N] [--top N] [--include-tests]
```

`<skill_dir>` is this skill's directory. `PATH` defaults to the current directory;
test files (`*.spec.*` / `*.test.*`) are excluded unless `--include-tests`;
vendored/build dirs (`node_modules`, `dist`, `.astro`, ...) are always skipped.

### Arguments

- `--threshold N` (default 3): minimum number of distinct files a string must appear
  in to be flagged. Lower thresholds show more candidates; higher thresholds focus
  on the worst offenders.
- `--min-len N` (default 4): minimum string length to consider. Avoids noise from
  very short strings (e.g., single letters, common punctuation).
- `--top N` (default 10): how many strings to show in the output.

## Relaying the result

**Print the entire table to the user verbatim.** It IS the answer. Do NOT summarize
it to prose or drop rows. You may add ONE takeaway line after the table (e.g. the
most-duplicated string), but the full table comes first and in full.

## Caveats

- Extraction is regex-based and includes both `"..."` and `'...'` patterns;
  template literals (backticks) are not yet supported.
- Very short strings are filtered by default (`--min-len 4`) to reduce noise.
  Common keywords like `true`, `false`, `null`, `undefined` are also skipped.
- Duplicated strings in comments or documentation are not detected (analysis is
  source-code strings only).
- String normalization treats `\"` and `"` the same for deduplication purposes.
