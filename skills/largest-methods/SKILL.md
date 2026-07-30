---
name: largest-methods
description: >-
  Find the largest / longest methods or functions in a codebase, ranked by line
  count, using ast-grep structural matching. Use whenever the user wants to know
  which functions are too long, asks "what's the biggest method", hunts for
  refactor candidates, wants a complexity/length hotspot list, or asks to find
  long functions to split up. Prefer this over grep or reading files manually:
  it runs one bundled command and returns only a small ranked table, so it
  answers the question for a tiny number of tokens instead of pulling source or
  AST JSON into context.
---

# Largest Methods

Rank the longest methods/functions in a codebase by line count, cheaply.

## Why this exists

The naive way to answer "what's the biggest method?" is to read files or dump
AST JSON into the conversation, both of which burn thousands of tokens. This
skill runs all of that work through the installed sniff CLI: it runs `ast-grep`, parses
the JSON internally, folds away nested closures, and prints a ~20-row table. You
only ever see the table. Keep it that way, never pipe the raw `ast-grep --json`
output into your own context to re-rank it by hand.

## Usage

Run the detector through the installed sniff CLI:

1. Ensure sniff is installed. Try `sniff version`. If it fails, install it:
   `uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`),
   and if `ast-grep` is missing: `uv tool install ast-grep-cli`.
2. Run: `sniff --only largest-methods [DIR] [--top N] [--lang LANG]
   [--include-tests]`
3. Report the table; do not paste raw file contents.

The output is a `LINES / NAME / LOCATION` table sorted biggest-first.
**Print the entire table verbatim.** It IS the answer. Do NOT replace it with a
summary or describe it in prose; the user wants every row. You may add ONE
optional takeaway line after the table (e.g. which file is the hotspot), but the
full table must appear first and in full. Do not re-read listed files unless the
user then asks you to actually refactor one.

## What it counts, and the caveats worth stating

- **Languages**: auto-detected from file extensions. TypeScript/TSX, JavaScript,
  and Python are the best-tested; Go, Rust, Java, C#, Ruby, C/C++ and a few more
  are mapped but less battle-tested. If a language you expected shows nothing,
  pass `--lang` explicitly and sanity-check the result.
- **Line count, not cyclomatic complexity.** "Largest" here means physical line
  span (`end_line - start_line + 1`). A long function isn't automatically a bad
  one, present it as a refactor *candidate*, not a verdict.
- **Nested closures are folded into their parent.** A 200-line function that
  contains a 150-line arrow reports once, as 200. This avoids counting the same
  code twice. A class-field arrow or a top-level `const handler = () => {}` is
  top-level, so it still appears (named after the variable it's assigned to).
- **Tests excluded by default** (`*.spec.*`, `*.test.*`); add `--include-tests`
  to count them. `node_modules`, `dist`, `build`, and similar are always skipped.
- **Names are best-effort**, read from the definition's first line. Most resolve
  cleanly; a few may show `(anon)` for unusual syntax. The `LOCATION` column is
  authoritative, jump there if a name looks off.
