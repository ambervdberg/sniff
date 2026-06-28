---
name: most-imports
description: >-
  Find files with the most import statements in a codebase, ranked by import
  count. Use when the user wants to know which files are too tightly coupled,
  hunts for god files or circular dependency sources, asks "what imports the
  most", or looks for files to split up. High import count signals complex
  dependencies and likely refactor candidates. Returns one small ranked table,
  not the files themselves, so it answers for a tiny number of tokens.
---

# most-imports

Rank files by the number of import statements they contain. High import counts
signal tight coupling and potential god files. This is the **file-metric**
engine: counts import declarations per file using ast-grep, using the same
ignore list and test handling as the AST skills.

## Prerequisites

- `ast-grep` on PATH (`ast-grep --version`). Install: https://ast-grep.github.io
- Python 3. (Any recent version to run the bundled script.)

## Usage

```bash
python "<skill_dir>/scripts/most_imports.py" [PATH] [--top N] [--include-tests]
```

`<skill_dir>` is this skill's directory. `PATH` defaults to the current directory;
test files (`*.spec.*` / `*.test.*`) are excluded unless `--include-tests`;
vendored/build dirs (`node_modules`, `dist`, `.astro`, ...) are always skipped.

## Relaying the result

**Print the entire table to the user verbatim.** It IS the answer. Do NOT
summarize it to prose or drop rows. You may add ONE takeaway line after the
table (e.g. the file with the most imports), but the full table comes first and
in full.

## Caveats

- **Import count is one metric of coupling, not a verdict.** A file with 50
  imports is not automatically wrong if they are all typed utility imports from
  a single package. Use this as a starting point for refactoring, not an
  absolute rule.
- **TypeScript/JavaScript only.** Other languages are not yet supported; add
  them if needed.
- Counts **top-level import statements** only. Re-exports and dynamic imports
  (e.g. `await import(...)`) are structured differently and not counted.
