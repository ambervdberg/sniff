---
name: duplicate-code
description: >-
  Find the largest blocks of duplicated code (copy-pasted logic), ranked by size.
  Use when the user asks what code is duplicated, hunts for copy-paste, wants to
  find repeated logic, sync/async twin methods, or blocks worth extracting into a
  shared helper. This finds duplicated *logic*; no-duplicate-string finds
  duplicated *literals*. Returns a small ranked table, not the source.
---

# duplicate-code

Find copy-pasted code: the same block written out in two or more places. Every
file is turned into a normalised token stream and equal token windows are found
with a rolling hash, so this catches duplication a text diff misses:

- identifiers are normalised, so a clone survives renaming,
- literals are normalised, so a clone survives retuned constants,
- `async` and `await` are dropped, so a method and its async twin match.

Keywords and punctuation are kept, so two blocks match only when they do the
same thing in the same order. This is the **file-metric** engine: no AST, no
ast-grep needed.

## Usage

Run the detector through the installed sniff CLI:

1. Ensure sniff is installed. Try `sniff version`. If it fails, install it:
   `uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`).
2. Run: `sniff --only duplicate-code DIR [--min-tokens N] [--min-lines N]
   [--top N] [--include-tests]`
3. Report the table; do not paste raw file contents.

Flags:
- `--min-tokens N` (default 30): smallest clone to report, in tokens.
- `--min-lines N` (default 5): smallest clone to report, in lines.
- `--top N` (default 10): how many clones to show.

**Print the entire table verbatim.** It IS the answer. Do NOT summarize it to
prose or drop rows. You may add ONE takeaway line after the table (e.g. the two
files that share the most code), but the full table comes first and in full.

Columns: `TOKENS` is the clone's size and the ranking key; `LINES` is the line
span of the first copy; `COPIES` is how many places it was found; `LOCATIONS`
lists up to three of them as `file:start-end`.

## Caveats

- Ranking is by tokens, not lines: a block padded with comments and blank lines
  spans more lines without being more duplication.
- Blocks that are mostly imports, blocks with no keyword in them at all (a lookup
  table long enough that one half matches the other half), and minified bundles
  are excluded, since they otherwise outrank every real clone.
- Copies of one clone never overlap: a run of near-identical methods is reported
  as separate copies, not as one method matching itself.
- `COPIES` stops counting at 13 per block. When a block hits that, the header
  says so and the number is a floor, not a total.
- Duplication that was reworded rather than copied (same idea, different
  structure) is not token-level duplication and is not reported.
