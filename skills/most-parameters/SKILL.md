---
name: most-parameters
description: >-
  Find the functions/methods with the most parameters in a codebase, ranked by
  parameter count, using ast-grep structural matching. Use whenever the user
  wants to know which functions take too many arguments, asks "what has the most
  parameters / longest argument list", hunts for long-parameter-list refactor
  candidates, or asks where to introduce a parameter object. Prefer this over
  grep or reading files manually: it runs one bundled command and returns only a
  small ranked table, so it answers for a tiny number of tokens instead of
  pulling source or AST JSON into context.
---

# Most Parameters

Rank functions/methods by how many parameters they take, cheaply.

## Why this exists

Long parameter lists are a classic smell (hard to call, easy to mix up
arguments), but counting them by hand means reading files and burning tokens.
This skill pushes the work into a bundled script: it asks `ast-grep` for the
functions and their parameter lists, counts each list's top-level entries, and
prints a ~20-row table. You only ever see the table. Keep it that way, never
pipe raw `ast-grep --json` output into your own context.

## What it counts

Top-level parameters in each function's signature. Commas inside generics or
defaults (`Map<string, number>`, `x = {a, b}`) are NOT counted as separators, so
those stay one parameter. Rest/spread params (`*args`, `...rest`) count as one
each. A function's own signature is measured, not the parameters of functions
nested inside it.

## Usage

Run the detector through the installed sniff CLI:

1. Ensure sniff is installed. Try `sniff version`. If it fails, install it:
   `uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`),
   and if `ast-grep` is missing: `uv tool install ast-grep-cli`.
2. Run: `sniff --only most-parameters [DIR] [--top N] [--lang LANG] [--min N]
   [--include-tests]`
3. Report the table; do not paste raw file contents.

The output is a `PARAMS / NAME / LOCATION` table sorted most-first. **Print the
entire table verbatim.** It IS the answer. Do NOT replace it with a summary or
describe it in prose; the user wants every row. You may add ONE optional takeaway
line after the table, but the full table comes first and in full. Do not re-read
listed files unless the user then asks you to refactor one.

## Caveats worth stating

- **Languages**: auto-detected. TypeScript/TSX, JavaScript and Python are the
  best-tested; Java, C#, Go, Rust, Ruby, C/C++, PHP, Kotlin are mapped but less
  battle-tested. A language with no parameter-kinds mapping is skipped; if
  something you expected shows nothing, pass `--lang` and sanity-check.
- **Counting is text-bracket-aware, not full type analysis.** A signature with an
  unusual default expression containing a top-level comma is a rare edge that
  could miscount; `LOCATION` is authoritative, jump there if a number looks off.
- **`this`/`self` may or may not appear** depending on the language grammar;
  treat the ranking as a smell finder, not an exact ABI parameter count.
- **`--min` defaults to 3** (2 or fewer params isn't a smell). Raise it further to
  focus on the worst offenders.
- **Tests excluded by default** (`*.spec.*`, `*.test.*`); add `--include-tests`.
  `node_modules`, `dist`, `build` and similar are always skipped.
