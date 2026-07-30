---
name: cognitive-complexity
description: >-
  Find the functions/methods that are hardest to read in a codebase, ranked by
  cognitive complexity (SonarSource-style, nesting-weighted), using ast-grep
  structural matching. Use whenever the user wants to know which functions are
  hardest to follow, asks "what's the most complex / hardest to read function",
  hunts for tangled control-flow refactor candidates, or asks where to flatten
  and extract. Prefer this over grep or reading files manually: it runs one
  bundled command and returns only a small ranked table, so it answers for a
  tiny number of tokens instead of pulling source or AST JSON into context.
---

# Cognitive Complexity

Rank functions/methods by how hard they are to read, cheaply.

## Why this exists

Cyclomatic complexity counts paths; cognitive complexity tries to model how hard
code is for a human to follow, by punishing deep nesting more than flat
branching. Measuring it by hand means reading files and burning tokens. This
skill pushes the work into a bundled script: it asks `ast-grep` for the functions
and their control structures, derives each function's score from node
containment, and prints a ~20-row table. You only ever see the table. Keep it
that way, never pipe raw `ast-grep --json` output into your own context.

## What "cognitive" means

Each control structure (if, loop, switch, try/catch) costs 1, plus a nesting
penalty equal to how many control structures enclose it. So a branch three levels
deep costs 1 + 3 = 4, while two sibling branches cost 1 + 1 = 2. This is the
nesting model behind SonarSource cognitive complexity, computed from AST node
ranges. It is the read-difficulty companion to `cyclomatic-complexity` (path
count) and `deepest-nesting` (depth only).

## Usage

Run the detector through the installed sniff CLI:

1. Ensure sniff is installed. Try `sniff version`. If it fails, install it:
   `uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`),
   and if `ast-grep` is missing: `uv tool install ast-grep-cli`.
2. Run: `sniff --only cognitive-complexity [DIR] [--top N] [--lang LANG]
   [--min N] [--include-tests]`
3. Report the table; do not paste raw file contents.

The output is a `COGNITIVE / NAME / LOCATION` table sorted hardest-first.
**Print the entire table verbatim.** It IS the answer. Do NOT replace it with a
summary or describe it in prose; the user wants every row. You may add ONE
optional takeaway line after the table (e.g. the worst offender), but the full
table comes first and in full. Do not re-read listed files unless the user then
asks you to actually refactor one.

## Caveats worth stating

- **Languages**: auto-detected. TypeScript/TSX, JavaScript and Python are the
  best-tested; Java, C#, Go, Rust, Ruby, C/C++, PHP, Kotlin are mapped but less
  battle-tested. A language with no nesting-kinds mapping is skipped; if something
  you expected shows nothing, pass `--lang` and sanity-check.
- **Approximate, not exact Sonar parity.** Boolean-operator sequences (`a && b`)
  are NOT scored here yet (use `cyclomatic-complexity` for boolean-heavy code),
  and `else`/`else if` are treated like a nested branch rather than Sonar's flat
  +1. Treat the ranking as a hotspot finder, not a certified score.
- **`--min` defaults to 1.** Raise it to focus on the worst offenders.
- **Tests excluded by default** (`*.spec.*`, `*.test.*`); add `--include-tests`.
  `node_modules`, `dist`, `build` and similar are always skipped.
- **Names are best-effort**, read from the definition's first line; `LOCATION` is
  authoritative.
