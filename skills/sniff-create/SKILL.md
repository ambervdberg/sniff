---
name: sniff-create
description: >-
  Create a new code-smell skill or sniff-patterns rule from a short
  conversation. Use when the user wants to "make a skill that finds X", "add a
  lint/smell check", "find a code smell", "enforce a clean-code rule", 
  turn a repeated structural query into a reusable token-cheap skill, or
  scaffold a new code-pattern/metric check (complexity, nesting, duplication,
  anti-patterns). Picks the right engine, drafts and validates the rule on the
  current repo before writing anything, then generates a standalone skill or a
  catalog rule which is a token efficient way to improve the code base.
---

# sniff-create

Turn "I keep checking for X" into a reusable, token-cheap smell skill. Every skill
it makes returns a small table or findings list; the calling agent never sees raw
source or AST. Do not hand-write skill files, drive the steps below and let
`create.py` scaffold. The point is the **validate-before-write** gate.

## Step 1 — Classify the smell into an engine (do this first)

Every check fits exactly one engine. Pick before anything else; it decides the tool.

| Engine | Use when the smell is... | Built? |
| --- | --- | --- |
| **pattern rule** | a specific code shape, flagged with a severity (e.g. `any` type, empty `imports: []`) | yes |
| **node-span** | "largest X" ranked by line count (methods, classes, ...) | yes |
| **node-metric** | a *computed score* per method/class: nesting depth, cyclomatic / cognitive complexity, params, inline-template line count | engine yes (`sniff.node_metric`): depth (`deepest-nesting`), cyclomatic (`cyclomatic-complexity`), cognitive (`cognitive-complexity`), params (`most-parameters`), inline-template LOC (`large-inline-templates`) done; create generator in progress (`sniff-...6.5`) |
| **file-metric** | a number per *file*, no AST: largest files, lines of code | engine yes (`largest-files`); no create generator yet |
| **cross-file** | needs a whole-project graph: inheritance depth | not yet (`sniff-...8`) |

### Scope gate

- `create.py` can scaffold **pattern rule**, **node-span**, and **node-metric**
  skills today, plus a full **detector** (see Step 5a) for either this repo's
  registry or a consuming repo.
- **node-metric**: the engine ships five metrics (`depth`, `cyclomatic`,
  `cognitive`, `params`, `template-lines`). Scaffold a skill around one with
  `create.py node-metric --metric <m>` (see Step 3). To add a *new* metric the
  engine does not have yet, extend `node_metric.py` the same two-pass way
  (functions + the nodes the metric counts) and add it to `NODE_METRICS` in
  `create.py`, then it is createable too.
- **file-metric** has a working engine (`sniff.harness.iter_source_files` /
  `count_code_lines`, see the `largest-files` skill) but no create generator yet;
  add a new file-metric skill by hand against those helpers, the same shape as
  `largest-files`.
- **cross-file** engine is not built. Do NOT hand-write a one-off script to fake
  it. Say so and file a bead to add the engine first. A bespoke bypass defeats the
  shared-engine design, the exact thing this create exists to prevent.

## Step 2 — Intake

Ask, one at a time, only what you can't infer: what to find (plain words),
languages, and for a pattern smell whether it's a **standalone skill** (a distinct,
frequently-run check you invoke by name) or a **sniff-patterns rule** (one of many
catalog checks, run together in a single scan). Recommend a catalog rule for
SonarCloud-style checks, a standalone skill for a distinct ranked query.

## Step 3 — Draft the ast-grep rule

For non-trivial patterns, invoke the `ast-grep` skill for syntax. A **kinds** match
(node type, e.g. `class_declaration`) suits node-span skills; a **pattern**
(e.g. `$A ? $B : $C ? $D : $E`) suits a specific shape.

## Step 4 — Validate on the current repo (the gate)

Before writing any file, run the rule and look at real matches. Write the rule YAML
to a scratch file first; a multi-line `--inline-rules` argument gets mangled when
ast-grep is a Windows `.cmd` shim:

```bash
ast-grep scan --rule <scratch>.yml <a real repo path> --json=compact \
  | python -c "import sys,json; d=json.load(sys.stdin); print(len(d),'matches'); [print(m['file']+':'+str(m['range']['start']['line']+1)) for m in d[:5]]"
```

Show the user ~5 samples and the count. If wrong (false positives, missed cases,
zero when there should be hits), fix and re-run. Only proceed once it's right.

## Step 5 — Scaffold with create.py

Standalone skill:

```bash
python "<skill_dir>/scripts/create.py" standalone \
  --name <kebab-name> --noun "<plural noun>" \
  --title "<one-line title>" \
  --description "<triggering description; mention it returns a small table, not source>" \
  --langs <csv ast-grep langs> \
  --kinds <csv node kinds>          # OR: --pattern '<ast-grep pattern>'
```

node-metric skill (wraps an existing engine score: `depth`, `cyclomatic`,
`cognitive`, `params`, `template-lines`). No ast-grep drafting needed, the engine
already computes the metric:

```bash
python "<skill_dir>/scripts/create.py" node-metric \
  --metric cognitive \
  --name <kebab-name> \
  --title "<one-line title>" \
  --description "<triggering description; mention it returns a small table, not source>"
```

sniff-patterns rule (pass the samples gathered in Step 4 as fixtures: matches as
`--test-invalid`, near-misses as `--test-valid`):

```bash
python "<skill_dir>/scripts/create.py" rule \
  --name <kebab-id> --language <lang> --severity warning \
  --title "<one-line title>" --message "<finding message>" \
  --pattern '<ast-grep pattern>'    # OR: --rule-body-file <file with raw rule yaml>
  --test-invalid '<snippet that should match>'   # repeatable, required in repo mode
  --test-valid '<snippet that should not match>' # repeatable, optional
```

Working **outside the sniff repo** (this skill installed as a plugin in some other
project)? Add `--local` (this is the default recommendation off-repo). It writes
the rule to `<cwd>/.sniff/rules/<id>.yml` and the fixture to
`<cwd>/.sniff/rule-tests/<id>.yml` instead of into this repo's catalog. `--local`
makes `--test-valid`/`--test-invalid` optional (the contributing project's own
pipeline enforces fixtures later, not this create step).

Add `--dry-run` first to preview. `<skill_dir>` is this skill's directory.

## Step 5a: Scaffold a detector instead (`--target core|external`)

Use this instead of Step 5 when the goal is a real **detector** that shows up
in `sniff --list` / a full `sniff` scan, not a one-off query skill. Pick a
target:

- **`--target external`** (default): for a *consuming* repo, not this one. Run
  it with `--dest <that repo's root>`. Writes a self-contained manifest +
  script under `<dest>/.sniff/detectors/<name>/`: no import of `sniff`, so it
  keeps working across sniff version upgrades. Auto-discovered the next time
  `sniff` runs there, no registration step.
- **`--target core`**: for *this* repo, to become a real built-in. Writes
  `src/sniff/detectors/<name>.py` with the `NAME`/`TITLE`/`DEFAULT_ARGS`/`main`
  shape every built-in has, importing `from sniff import harness as h`. The
  script prints a reminder afterward: add the import and a `BUILTIN` entry in
  `src/sniff/detectors/__init__.py` yourself, `create.py` does not touch the
  registry.

```bash
python "<skill_dir>/scripts/create.py" detector \
  --name <kebab-name> --title "<one-line title>" --description "<what it detects>" \
  --target external --dest <consuming-repo-root>   # or: --target core
```

`--title`/`--description` default from `--name` if omitted. Both scaffolds
leave a `TODO:` marker in the generated script's body, the mechanical shape is
in place but the actual detection logic (ast-grep call, node-metric wiring, or
plain file walk) is still yours to write and validate (Step 4) before it goes
live.

## Step 6 — Self-test, then make it live

`create.py` prints the exact follow-up commands. Always:

1. **Run** the generated script (standalone) or `ast-grep scan` over the new rule and
   confirm the table / findings render.
2. **Commit** the new files.
3. **Make it live**: a freshly created skill is not loaded until the plugin refreshes.
   Run `/plugin update sniff` (or reinstall from the local path). Until then the
   script still works run directly by path.
