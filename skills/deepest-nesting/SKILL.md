---
name: deepest-nesting
description: >-
  Find the most deeply nested functions/methods in a codebase, ranked by
  control-flow nesting depth, using ast-grep structural
  matching. Use whenever the user wants to know which functions are too deeply
  nested, asks "what's the most nested / deepest function", hunts for arrow-code
  or pyramid-of-doom refactor candidates, wants a nesting-depth hotspot list, or
  asks where to flatten guards / extract methods. Prefer this over grep or
  reading files manually: it runs one bundled command and returns only a small
  ranked table, so it answers for a tiny number of tokens instead of pulling
  source or AST JSON into context.
---

# Deepest Nesting

Rank functions/methods by how deeply their control flow nests, cheaply.

## Why this exists

Deeply nested loops and branches (the "pyramid of doom") are a top refactor
smell, but spotting them by eye means reading files and burning thousands of
tokens. This skill runs through the installed sniff CLI: it asks `ast-grep` for
the functions and the nesting constructs, derives each function's depth from
node containment, and prints a ~20-row table. You only ever see the table. Keep
it that way, never pipe raw `ast-grep --json` output into your own context.

## What "depth" means

Depth is the deepest stack of control-flow blocks inside a function: an `if`
holding a `for` holding a `while` is depth 3. Sibling blocks at the same level do
NOT add up (two sequential `if`s are still depth 1). Depth is computed from the
AST node ranges, not from indentation or braces in text.

## Usage

Run the detector through the installed sniff CLI:

1. Ensure sniff is installed. Try `sniff version`. If it fails, install it:
   `uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`),
   and if `ast-grep` is missing: `uv tool install ast-grep-cli`.
2. Run: `sniff --only deepest-nesting DIR [--top N] [--lang LANG]
   [--min-depth N] [--include-tests]`
3. Report the table; do not paste raw file contents.

The output is a `DEPTH / NAME / LOCATION` table sorted deepest-first. **Print the
entire table verbatim.** It IS the answer. Do NOT replace it with a summary or
describe it in prose; the user wants every row. You may add ONE optional takeaway
line after the table (e.g. the worst offender), but the full table comes first and
in full. Do not re-read listed files unless the user then asks you to actually
refactor one.

## What it counts, and the caveats worth stating

- **Languages**: auto-detected. TypeScript/TSX, JavaScript and Python are the
  best-tested; Java, C#, Go, Rust, Ruby, C/C++, PHP, Kotlin are mapped but less
  battle-tested. A language with no nesting-kinds mapping is skipped (not scored);
  if something you expected shows nothing, pass `--lang` and sanity-check.
- **Depth, not size or complexity.** A deep function isn't automatically the
  longest or the most complex, present it as a refactor *candidate*. Cyclomatic
  and cognitive complexity are separate metrics (their own skills).
- **`else if` counts as deeper.** Physical nesting is measured, so a long
  `if/else if` chain reads deeper than a cognitive-complexity model would score
  it. Treat the ranking as a hotspot finder, not an exact value.
- **`--min-depth` defaults to 1**, hiding flat functions. Raise it to focus on
  the worst, or pass `--min-depth 0` to list everything.
- **Tests excluded by default** (`*.spec.*`, `*.test.*`); add `--include-tests`.
  `node_modules`, `dist`, `build` and similar are always skipped.
- **Names are best-effort**, read from the definition's first line; `LOCATION` is
  authoritative.
