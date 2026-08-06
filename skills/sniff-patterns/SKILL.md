---
name: sniff-patterns
description: >-
  Run the sniff-patterns code-smell rule catalog over a repo in one pass and return a
  compact findings table. Use when the user wants to "lint the codebase", "find
  code smells", "run the smell checks", "scan for anti-patterns", "sonar-style
  scan", or check many small rules at once (e.g. explicit any, nested ternaries,
  empty Angular metadata). Returns a RULE / SEVERITY / LOCATION summary,
  never raw per-match output.
---

# sniff-patterns

Run the whole rule catalog (`rules/*.yml`) in a single `ast-grep scan` and report a
small findings table. Adding rules costs nothing here: they are inert data files,
loaded only when this skill runs, so the catalog can grow to hundreds of rules
without bloating context.

## Relaying the result

**Reproduce the entire output (header line + every per-rule table) in your reply
message, verbatim.** It IS the answer. The script emits one markdown table per rule
(heading = rule/severity/count, rows = locations); tables only render as real tables
when they live in your reply, NOT when left inside the tool-output block. Do NOT
summarize to prose or drop rows. You may add ONE takeaway line at the end (e.g. the
worst rule), but the full output comes first and in full.

A "Clean: 0 findings. Ran N rules (...)" line is a **valid, complete result**: the
codebase passed every rule. Relay it as-is. Do NOT speculate that the plugin "has no
rules" or is "new/empty", the line already names the rules that ran; trust it.

## Usage

Run the detector through the installed sniff CLI:

1. If `sniff version` fails: `uv tool install sniff-smells` (and `uv tool install ast-grep-cli` if `ast-grep` is missing).
2. Run: `sniff --only sniff-patterns DIR [--severity error|warning|info|hint]
   [--rule ID] [--top-locs N]`, or `sniff --list-patterns` to see the catalog.
3. Report the findings; do not paste raw rule files.

`DIR` defaults to the current directory. Filter with `--severity` or a single
`--rule`. Vendored/build dirs are always skipped.

Rules print worst severity first (error, warning, info, hint). Each heading carries
the rule's full hit count, but only its first 10 locations are listed; the rest
collapse into a `+N more` row. Use `--top-locs 0` to list every location of every
rule, or `--top-locs N --rule <id>` to expand one rule.

## Adding rules

Use `sniff-create` (rule mode) to add a rule, or drop a standard ast-grep rule file
into `rules/`. Each rule file needs `id`, `language`, `severity`, `message`, `rule`.
Prerequisites: `ast-grep` installed (`pip install ast-grep-cli`), Python 3.

## Caveats

- Each rule is single-language and single-file (ast-grep). Cross-file smells
  (e.g. inheritance depth) are out of scope, see the cross-file engine.
- Pattern matches flag a *shape*, not a proven defect. The `message` says why it is
  worth a look; the `LOCATION` column is authoritative.
- Test files are NOT excluded: a lint finding in a test still counts.
