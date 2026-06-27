---
name: cyclomatic-complexity
description: >-
  Find the most cyclomatically complex functions/methods in a codebase, ranked
  by number of independent paths (SonarSource S1541), using ast-grep structural
  matching. Use whenever the user wants to know which functions are too complex,
  asks "what's the most complex function", hunts for branch-heavy refactor
  candidates, wants a complexity hotspot list, or asks where to simplify control
  flow. Prefer this over grep or reading files manually: it runs one bundled
  command and returns only a small ranked table, so it answers for a tiny number
  of tokens instead of pulling source or AST JSON into context.
---

# Cyclomatic Complexity

Rank functions/methods by cyclomatic complexity, cheaply.

## Why this exists

Branch-heavy functions are hard to test and to read, but counting paths by hand
means reading files and burning tokens. This skill pushes the work into a
bundled script: it asks `ast-grep` for the functions and the decision points,
derives each function's complexity from node containment, and prints a ~20-row
table. You only ever see the table. Keep it that way, never pipe raw
`ast-grep --json` output into your own context.

## What "complexity" means

Cyclomatic complexity = 1 + the number of decision points in a function: each
`if`/`elif`, loop, `case`, `catch`/`except`, ternary, and boolean operator
(`&&`/`||`/`and`/`or`) adds one. A straight-line function is 1. This is
SonarSource rule **S1541**, computed from AST node ranges, not text.

## Prerequisites

- `ast-grep` on PATH (`ast-grep --version`). Install: https://ast-grep.github.io
- Python 3 (any recent version) to run the bundled script.

## Usage

Run the script and report the table. `PATH` defaults to the current directory.

```bash
python "<skill_dir>/scripts/cyclomatic_complexity.py" [PATH] [--top N] [--lang L] [--min N] [--include-tests]
```

`<skill_dir>` is the directory containing this SKILL.md. Examples:

```bash
# Whole repo, top 20, languages auto-detected, tests excluded
python "<skill_dir>/scripts/cyclomatic_complexity.py"

# Frontend, only functions with complexity 10+
python "<skill_dir>/scripts/cyclomatic_complexity.py" apps/web --min 10

# Force a language when auto-detect is too broad
python "<skill_dir>/scripts/cyclomatic_complexity.py" src --lang typescript
```

The output is already final-form, a `COMPLEXITY / NAME / LOCATION` table sorted
most-complex-first.

**Print the entire table to the user verbatim.** It IS the answer. Do NOT replace
it with a summary or describe it in prose, the user wants every row. You may add
ONE optional takeaway line after the table (e.g. the worst offender), but the full
table comes first and in full. Do not re-read the listed files unless the user
then asks you to actually refactor one.

## What it counts, and the caveats worth stating

- **Languages**: auto-detected. TypeScript/TSX, JavaScript and Python are the
  best-tested; Java, C#, Go, Ruby, C/C++ are mapped but less battle-tested. A
  language with no decision-kinds mapping is skipped (not scored); if something
  you expected shows nothing, pass `--lang` and sanity-check.
- **Approximate, not exact Sonar parity.** Boolean operators are counted per
  operator (`a && b && c` adds 2), and decision points inside a nested function
  currently count toward the enclosing function too. Treat the ranking as a
  hotspot finder, not a certified S1541 value.
- **Complexity, not size or nesting.** A complex function isn't always the
  longest or the deepest, those are separate skills (`largest-methods`,
  `deepest-nesting`).
- **`--min` defaults to 1** (show everything). Raise it to focus on the worst.
- **Tests excluded by default** (`*.spec.*`, `*.test.*`); add `--include-tests`.
  `node_modules`, `dist`, `build` and similar are always skipped.
- **Names are best-effort**, read from the definition's first line; `LOCATION` is
  authoritative.
