---
name: self-admitted-debt
description: >-
  Rank files by the TODO, FIXME, HACK and XXX markers in their comments.
  Use when the user asks what technical debt the codebase admits to, wants the
  TODOs/FIXMEs found, asks where the known-broken parts are, or wants a debt
  backlog from the code itself. Returns a small ranked table, not the comments.
---

# self-admitted-debt

Find the debt the authors already wrote down. `TODO`, `FIXME`, `HACK` and `XXX`
mark problems somebody hit, understood, and left behind, which makes them the
cheapest debt in a repo to act on. This is the **file-metric** engine: a scan of
each file's comments, no AST and no ast-grep needed.

## Usage

Run the detector through the installed sniff CLI:

1. Ensure sniff is installed. Try `sniff version`. If it fails, install it:
   `uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`).
2. Run: `sniff --only self-admitted-debt [DIR] [--markers A,B] [--top N]
   [--include-tests]`
3. Report the table; do not paste the comments themselves.

Flags:
- `--markers A,B` (default `TODO,FIXME,HACK,XXX`): which markers to count. The
  list replaces the defaults, so pass every marker you want.
- `--top N` (default 10): how many files to show.

**Print the entire table verbatim.** It IS the answer. Do NOT summarize it to
prose or drop rows. You may add ONE takeaway line after the table (e.g. the file
carrying the most debt), but the full table comes first and in full.

Columns: `MARKERS` is the file's total and the ranking key; `KINDS` breaks it
down per marker; `FILE` is where to look.

## Caveats

- Markers only count inside comments, so a `"TODO"` string in the UI is not
  debt. A line that opens a URL (`"http://..."`) before the marker can still be
  counted, since `//` reads as a comment opener.
- Matching is case-sensitive and whole-word: `TODOS` and `todo` are not markers.
- Ranking is per file, not per marker, so the table says where the debt is
  concentrated, not what each item says. Open the file for that.
