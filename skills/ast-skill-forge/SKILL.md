---
name: ast-skill-forge
description: >-
  Create a new ast-grep structural-search skill, or a new ast-lint rule, from a
  short conversation. Use when the user wants to "make a skill that finds X",
  "bake this search", "add an ast-lint rule", turn a repeated structural query
  into a reusable token-cheap skill, or scaffold a new code-pattern search. Drafts
  the ast-grep rule, validates it on the current repo before writing anything, then
  generates either a standalone skill or a catalog rule.
---

# ast-skill-forge

Turn "I keep searching for X" into a reusable, token-cheap skill. Every skill it
makes follows the same shape: ast-grep does the AST work, the shared `_ast-harness`
engine ranks and prints, the calling agent only ever sees a small table.

Do not write skill files by hand. Drive the steps below, then call `forge.py` to
scaffold. The whole point is the **validate-before-write** gate: a skill built on a
wrong rule is worse than no skill.

## Prerequisites

- `ast-grep` on PATH and Python 3.
- This repo (`ast-skills`) checked out; `forge.py` writes into it.

## Step 1 — Intake (ask, do not assume)

Ask the user, one at a time, only what you can't infer:

1. **What to find** in plain words (e.g. "functions with too many parameters",
   "nested ternaries", "classes over N lines", "catch blocks that swallow errors").
2. **Languages** (e.g. typescript, tsx, python). Default: ask which apply.
3. **Output mode**:
   - **standalone skill** — a distinct, frequently-run query you'll invoke by name.
     Ranked by line span, returns a `LINES / NAME / LOCATION` table.
   - **ast-lint rule** — one of many lint-style checks; goes in the catalog and runs
     with all the others in a single scan. No new skill, no description weight.
   Recommend **ast-lint rule** for SonarCloud-style checks (many small rules), and
   **standalone** for a distinct ranked query.

## Step 2 — Draft the ast-grep rule

Write the rule. For non-trivial patterns, invoke the `ast-grep` skill for syntax.

- A **kinds** match (node type, e.g. `class_declaration`) suits "largest X" skills.
- A **pattern** (e.g. `$A ? $B : $C ? $D : $E`) suits specific code shapes.

## Step 3 — Validate on the current repo (the gate)

Before writing any file, run the rule and look at real matches:

```bash
ast-grep scan --inline-rules "<your rule yaml>" <a real repo path> --json=compact \
  | python -c "import sys,json; d=json.load(sys.stdin); print(len(d),'matches'); [print(m['file']+':'+str(m['range']['start']['line']+1)) for m in d[:5]]"
```

Show the user ~5 sample matches and the count. If they look wrong (false positives,
missed cases, zero when there should be hits), fix the rule and re-run. Only proceed
once the matches are right. Do not skip this step.

## Step 4 — Scaffold with forge.py

Standalone skill:

```bash
python "<skill_dir>/scripts/forge.py" standalone \
  --name <kebab-name> --noun "<plural noun>" \
  --title "<one-line title>" \
  --description "<triggering description; mention it returns a small table, not source>" \
  --langs <csv ast-grep langs> \
  --kinds <csv node kinds>          # OR: --pattern '<ast-grep pattern>'
```

ast-lint rule:

```bash
python "<skill_dir>/scripts/forge.py" rule \
  --name <kebab-id> --language <lang> --severity warning \
  --title "<one-line title>" --message "<finding message>" \
  --pattern '<ast-grep pattern>'    # OR: --rule-body-file <file with raw rule yaml>
```

Add `--dry-run` first to preview the files. `<skill_dir>` is this skill's directory.

## Step 5 — Self-test, then make it live

`forge.py` prints the exact follow-up commands. Always:

1. **Run** the generated script (standalone) or `ast-grep scan` over the new rule and
   confirm the table / findings render.
2. **Commit** the new files.
3. **Make it live on this PC**: a freshly forged skill is not loaded until the plugin
   is refreshed. Run `/plugin update ast-skills` (or reinstall from the local path).
   Until then the script still works when run directly by path.

## What forge.py does and does not do

- It only does the mechanical file generation from resolved inputs. All the judgment
  (intent, rule correctness, language choice, validation) is yours, in steps 1-3.
- Standalone skills rank by **line span** today. A metric like parameter count or
  nesting depth needs a harness extension; if the user needs that, say so rather than
  shipping a line-span proxy that doesn't answer their question.
