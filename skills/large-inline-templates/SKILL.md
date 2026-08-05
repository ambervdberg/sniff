---
name: large-inline-templates
description: >-
  Find Angular components whose inline template is too large and should move to
  its own .html file, ranked by template line count, using ast-grep structural
  matching. Use whenever the user wants to know which Angular components have big
  inline templates, asks "which components should use templateUrl", hunts for
  inline-template refactor candidates, or wants an Angular template-size hotspot
  list. Prefer this over grep or reading files manually: it runs one bundled
  command and returns only a small ranked table, so it answers for a tiny number
  of tokens instead of pulling source into context.
---

# Large Inline Templates

Rank Angular components by inline-template size, cheaply.

## Why this exists

A short inline `template` is fine; a 60-line one buried in a decorator is a smell
that belongs in its own `.html` file. Spotting them by eye means reading
component files and burning tokens. This skill runs through the installed
sniff CLI: it asks `ast-grep` for the `@Component` decorators, reads each inline
template's line count from the decorator, and prints a ~20-row table. You only
ever see the table. Keep it that way, never pipe raw `ast-grep --json` output
into your own context.

## What it counts

The line count of each `@Component`'s inline `template: \`...\`` literal.
Components that use `templateUrl` (an external file) are ignored, they are not an
inline-template smell. The component's `selector` is used as the name.

## Usage

Run the detector through the installed sniff CLI:

1. Ensure sniff is installed. Try `sniff version`. If it fails, install it:
   `uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`),
   and if `ast-grep` is missing: `uv tool install ast-grep-cli`.
2. Run: `sniff --only large-inline-templates DIR [--top N] [--min N]
   [--include-tests]`
3. Report the table; do not paste raw file contents.

The output is a `LINES / SELECTOR / LOCATION` table sorted largest-first.
**Print the entire table verbatim.** It IS the answer. Do NOT replace
it with a summary or describe it in prose, the user wants every row. You may add
ONE optional takeaway line after the table, but the full table comes first and in
full. Do not re-read the listed files unless the user then asks you to extract one.

## Caveats worth stating

- **TypeScript/TSX only.** Angular components live there; other languages are not
  scanned.
- **Inline templates only.** `templateUrl` components are skipped by design.
- **Selector is read from the decorator text.** A component without a `selector`
  shows `(component)`; `LOCATION` is authoritative, jump there if a name looks off.
- **Backtick-in-template edge.** The template literal is read up to the first
  closing backtick; the rare component embedding a literal backtick in its
  template could under-count. `LOCATION` is authoritative.
- **Tests excluded by default** (`*.spec.*`, `*.test.*`); add `--include-tests`.
  `node_modules`, `dist`, `build` and similar are always skipped.
