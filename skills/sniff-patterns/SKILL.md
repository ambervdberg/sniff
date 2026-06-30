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

## Command

```bash
python "<skill_dir>/scripts/format.py" [PATH] [--severity error|warning|info|hint] [--rule ID] [--top-locs N] [--list-rules]
```

`<skill_dir>` is this skill's directory. `PATH` defaults to the current directory.
Filter with `--severity` or a single `--rule`. Vendored/build dirs are skipped.
Use `--list-rules` to print the catalog (RULE / SEVERITY / MESSAGE) and exit without scanning.

## Adding rules

Use `sniff-create` (rule mode) to add a rule, or drop a standard ast-grep rule file
into `rules/`. Each rule file needs `id`, `language`, `severity`, `message`, `rule`.
Prerequisites: `ast-grep` on PATH, Python 3.

## Future: custom-ranking rules (dormant seam)

A rule that needs a *computed score* (nesting depth, complexity) rather than a plain
match cannot be expressed as a pattern. The planned hook: such a rule carries an
`x-harness: <script>` meta key, and a future runner routes it through `_ast-harness`
for scoring instead of plain `scan`. The current runner ignores `x-harness`, so the
seam is designed-in but inert. Until then, score-based smells are standalone
node-metric skills, not catalog rules.

## Caveats

- Each rule is single-language and single-file (ast-grep). Cross-file smells
  (e.g. inheritance depth) are out of scope, see the cross-file engine.
- Pattern matches flag a *shape*, not a proven defect. The `message` says why it is
  worth a look; the `LOCATION` column is authoritative.
- Test files are NOT excluded: a lint finding in a test still counts.
