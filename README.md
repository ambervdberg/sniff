<div align="center">
  <img src="https://raw.githubusercontent.com/ambervdberg/sniff/main/assets/sniff-logo.png" alt="sniff logo" width="220">
</div>

# sniff

`sniff` prints ranked tables of the repo's "worst" code: longest methods, deepest nesting, empty catches etc in a concise way.

It complements linters and code checkers like ESLint, Ruff, or SonarQube. They judge lines per language; sniff ranks the whole repo.

Same CLI for you and your agent. Small output means an agent learns the worst offenders for a few tokens.

[Install](#install) · [Quickstart](#quickstart) · [Use it from an agent](#use-it-from-an-agent) ·
[Detectors vs pattern rules](#detectors-vs-pattern-rules) · [The detectors](#the-detectors) ·
[Commands](#commands) ·
[Configuration](#configuration) · [Language support](#language-support) ·
[Pattern rules](#pattern-rules) · [CI mode](#ci-mode) · [Hooks](#hooks) ·
[Contributing](#contributing)

## Install

```bash
uv tool install sniff-smells
uv tool install ast-grep-cli
```

Both lines are required. The first puts the `sniff` command on PATH via
[uv](https://docs.astral.sh/uv/); the second installs
[`ast-grep`](https://ast-grep.github.io), the parser 9 of the 11 detectors run on. Skip
it and only `largest-files` and `no-duplicate-string` still work; every other detector
exits with `error: ast-grep is not installed or not on PATH`. One-time per machine, not
per repo.

Needs Python 3.10+ and works the same on Windows, macOS, and Linux. Run `sniff doctor`
to confirm both pieces are present.

No `uv`? `pip install sniff-smells ast-grep-cli` works the same.

Upgrade later with `uv tool upgrade sniff-smells` (or `pip install -U sniff-smells`).

## Quickstart

```bash
sniff .
```

That runs every detector against the current directory and prints compact ranked
tables.

### What a scan looks like

```console
$ sniff .
sniff: 11 detectors over '.': cognitive-complexity, cyclomatic-complexity, deepest-nesting, ...

## cognitive-complexity

Hardest to read: 10 of 412 functions by cognitive complexity (typescript; tests excluded):

| COGNITIVE | NAME           | LOCATION                         |
| --------- | -------------- | -------------------------------- |
| 31        | reconcileOrder | src/checkout/order-service.ts:88 |
| 24        | applyDiscounts | src/checkout/pricing.ts:142      |
| 19        | renderRow      | src/ui/cart-table.tsx:57         |

... one section per detector ...

## sniff-patterns

sniff-patterns: 23 findings, 4 of 16 rules matched in '.' (tests excluded)

### no-empty-catch (error): 2

| LOCATION                          |
| --------------------------------- |
| src/checkout/order-service.ts:113 |
| src/api/client.ts:64              |
```

That's the whole output: file and line only, never source code or an AST dump.

**How to read it.** Ranked sections are sorted worst-first and show the top 10 (configurable).

There is no pass/fail line: `31` is not "failing", it is just the hardest thing to read in this
repo, so start at the top row and stop caring wherever the numbers flatten out. 

Pattern
rule sections are the opposite: every row is one concrete mistake with a severity, and a
clean repo prints none.

Want more or fewer rows? `--top` is a per-detector flag, so `sniff . --top 25` is
rejected. Either run that one detector on its own, or set it for every scan in
[`.sniff.toml`](#configuration):

```bash
sniff --only cognitive-complexity . --top 25
```

## Use it from an agent

Nothing extra is required: any agent that can run a shell command can already run
`sniff`. Point it at `sniff prime`, which prints agent-optimized context (version,
detectors, prerequisites, usage hints) so it learns the whole CLI in one call instead
of reading this file.

The plugin is the optional next step. It adds a skill per detector so an agent can
trigger a check by name, plus `sniff-create` for writing new ones. It wraps the same
CLI, so the install above is still required underneath.

### Claude Code

```bash
/plugin marketplace add https://github.com/ambervdberg/sniff
/plugin install sniff
```

To update: `/plugin marketplace update sniff`, then re-run `/plugin install sniff`.

### Codex

```bash
codex plugin marketplace add ambervdberg/sniff
```

Then, in a Codex CLI session, run `/plugins` to install the `sniff` plugin from that
marketplace, and start a new session before its skills and hooks are available. To
update: `codex plugin marketplace upgrade sniff`, then reinstall from `/plugins`.

### Any other agent (Cursor, ...)

Add to your AGENTS.md:

>For code-quality questions (largest methods, complexity, smells), run `sniff [DIR]` and read its compact tables instead of scanning files.
>Run `sniff prime` once to learn all commands.

Or paste the live output of `sniff prime` into your agent's instructions file for the
exact command list.

## Detectors vs pattern rules

**Two kinds of checks: Detectors and Patterns.**

- **Detectors rank.** *"Which are the worst?"* Each one sorts your code by a number
  (lines, complexity, parameters) and prints the top N. There is always a longest
  method, so a detector always has an answer, even in a healthy repo. Nothing is
  right or wrong, just bigger or smaller.
- **Pattern rules flag.** *"Does this specific mistake appear?"* Each rule matches one
  shape (`as any`, an empty `catch`) and reports every hit with a severity. A clean
  repo produces nothing at all.

`sniff-patterns` runs the whole rule catalog in a single pass. That is why rules
appear inside a detector's section.

|                   | Detectors                           | Pattern rules                           |
| ----------------- | ----------------------------------- | --------------------------------------- |
| Output            | ranked table, top N                 | every location, with a severity         |
| On clean code     | still ranks something               | silent                                  |
| Tune by           | thresholds and flags                | turning off, re-grading severity        |
| Add custom one by | writing a module, or `sniff-create` | dropping in a `.yml`, or `sniff-create` |

(`sniff-create` scaffolds a new detector or pattern rule for you from a short
conversation, more on it below. `no-duplicate-string` is the one detector that behaves
a little like a rule: it ranks, but only counts literals repeated across 3+ files, so it
can come back empty.)

### The detectors

Everything `sniff --list` prints. They work from the CLI alone, with no plugin installed;
each also ships as a thin SKILL.md wrapper so an agent can trigger it by name.

| Detector                 | Does                                                                              |
| ------------------------ | --------------------------------------------------------------------------------- |
| `largest-methods`        | Rank the longest methods/functions by line count.                                 |
| `large-classes`          | Rank the longest classes by line count.                                           |
| `largest-files`          | Rank the largest source files by non-blank line count (no AST).                   |
| `deepest-nesting`        | Rank functions by control-flow nesting depth.                                     |
| `cyclomatic-complexity`  | Rank functions by cyclomatic complexity.                                          |
| `cognitive-complexity`   | Rank functions by cognitive complexity (nesting-weighted read difficulty).        |
| `most-parameters`        | Rank functions by parameter count (long-parameter-list smell).                    |
| `most-imports`           | Rank files by import count (high-coupling smell).                                 |
| `no-duplicate-string`    | Rank string literals by how many files repeat them (extract-as-constant candidates). |
| `large-inline-templates` | Rank Angular components by inline-template line count.                            |
| `sniff-patterns`         | Run the pattern rule catalog in one `ast-grep scan` pass; compact findings table. |

With the plugin installed, two more skills are available beyond the detectors above:

| Skill          | Does                                                                                             |
| -------------- | ------------------------------------------------------------------------------------------------ |
| `sniff`        | Umbrella runner: runs **all** detectors in one pass. Wraps the CLI's default `sniff [DIR]` scan. |
| `sniff-create` | Scaffold a new smell skill or catalog rule from a short conversation. No CLI equivalent.         |

## Commands

| Command                     | What it does                                                                     |
| --------------------------- | -------------------------------------------------------------------------------- |
| `sniff [DIR]`               | Scan `DIR` (default: `.`) with all detectors.                                    |
| `sniff --list`              | List all available detectors.                                                    |
| `sniff --list-patterns`     | List all pattern rules (RULE / SEVERITY / ORIGIN / ALSO RUNS ON / MESSAGE).      |
| `sniff --only a,b [DIR]`    | Run only the named detectors (e.g. `--only sniff-patterns` for pattern rules).   |
| `sniff --skip a,b [DIR]`    | Run all detectors except the named ones.                                         |
| `sniff --all [DIR]`         | Explicit alias for the default: run every detector.                              |
| `sniff --json [DIR]`        | Scan output as JSON instead of markdown (also works with `--list`).              |
| `sniff --ignore GLOB [DIR]` | Exclude paths matching `GLOB`; repeatable, and adds to whatever `.sniff.toml` already excludes. |
| `sniff version`             | Print the installed version.                                                     |
| `sniff doctor`              | Check prerequisites (Python, ast-grep, manifests, `.sniff.toml`); exits 0/1.     |
| `sniff prime`               | Agent-optimized context (version, detectors, prereqs, usage hints);         |
| `sniff --help`              | Show usage and examples.                                                         |

Three more commands belong to a workflow of their own rather than to a one-off scan:

| Command                       | What it does                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------------ |
| `sniff baseline write [DIR]`  | Save today's per-detector counts to `.sniff/baseline.json`. Commit that file.       |
| `sniff diff [DIR]`            | Re-scan and compare against that baseline; exits 1 if any detector regressed. Add `--comment` to format the result as a PR comment body. |
| `sniff contribute <rule-id>`  | Send one of your local pattern rules upstream into the shared catalog.              |

The first two are the [CI mode](#ci-mode) pair; the third is covered under
[Add a rule](#add-a-rule).

**Exit codes.**

`sniff doctor` and `sniff diff` exit 1 on failure, so both can gate a
build.

A plain `sniff [DIR]` exits 0, findings or not: it reports, it does not judge.
(The only exception: a `DIR` that does not exist exits 1.) Use `sniff diff` for the gate.

### Passing flags to one detector

Some flags belong to a single detector rather than to `sniff` itself, which is why they
are missing from the table above. Every ranking detector takes `--top N` and
`--include-tests`, and some add a threshold of their own, such as `--min-depth` on
`deepest-nesting` and `--threshold` on `no-duplicate-string`. (`sniff-patterns` accepts
`--top` but ignores it: it reports every match, so there is nothing to cut off.)

To use one, name exactly one detector with `--only` and put the flag **after** `DIR`:

```bash
sniff --only largest-methods . --top 5    # yes: 5 longest methods in '.'
sniff --only largest-methods --top 5 .    # no: binds '5' as the directory to scan
sniff . --top 5                           # no: rejected, --top needs --only
```

These override `.sniff.toml`. To change a detector's flag for every scan instead of one
run, set it in [`.sniff.toml`](#configuration).

## Configuration

Drop a `.sniff.toml` in the root of the repo being scanned to turn rules off, re-grade
severities, skip detectors, retune thresholds, and ignore paths. `sniff doctor` validates it.

Scanning a subdirectory still picks it up: sniff looks in the directory you scan, then
walks up to the repository root and uses the first file it finds. So `sniff packages/api`
honours the repo's committed config, and a `packages/api/.sniff.toml` of its own would
override it rather than merge with it.

```toml
[rules]                           # targets the sniff-patterns catalog only. Key is a rule id:
no-console-log = false            # turn a pattern rule off
no-explicit-any = "error"         # re-grade it (error | warning | info | hint)

[detectors]
skip = "most-imports,largest-files"   # comma-separated detector names
largest-methods.top = 15              # <detector>.<arg> becomes --arg on that detector
deepest-nesting.min-depth = 3

[ignore]
globs = ["docs/**", "**/*.generated.ts"]
```

Details worth knowing:

- **Keep every value on one line.** sniff reads this file line by line rather than with a
  full TOML parser, so an array split across lines is not understood. Write
  `globs = ["docs/**", "**/*.generated.ts"]` on one line.
- Note the two shapes above: `skip` takes one comma-separated **string**, `globs` takes a
  **list**. `globs` also accepts a string (`globs = "docs/**,**/*.generated.ts"`); `skip`
  does not accept a list.
- `[rules]` only affects pattern rules. `[detectors]` affects the detectors, and each `<detector>.<arg>`
  key becomes a `--arg` flag on that detector. Only flags that take a value work here, so
  `--include-tests` cannot be set this way.
- Ignore paths are matched from the root of the repo you scan.
- A section or key that sniff does not recognize is a warning, not an error, so a typo does not stop a scan.
  Run `sniff doctor` to see those warnings.

### What gets skipped

1. **Vendored and build directories**, always: `node_modules`, `dist`, `build`, `out`,
   `coverage`, `target`, `vendor`, `.venv`, `venv`, `.git`, `.nx`, `.angular`, `.astro`,
   `.next`, `.svelte-kit`, `.nuxt`, `.turbo`, `__pycache__`, `.claude`.
2. **Anything `.gitignore` excludes**, when the scanned directory is a git repo. Your
   `.git/info/exclude` and global ignore file count too, since sniff asks git rather than
   parsing the ignore files itself. Outside a git repo this layer is simply absent.
3. **Your own globs**: `[ignore] globs` in `.sniff.toml`, plus any `--ignore` flags.

Every detector also skips test code, so the tables describe the source you ship.
That means `*.test.*` and `*.spec.*` files in any language, `test_*.py`, `*_test.py`,
`conftest.py`, `*_test.go`, and anything inside a `tests/`, `test/`, `__tests__/`,
`spec/`, or `specs/` directory.

To rank test code too, add `--include-tests` to a single detector (see
[Passing flags to one detector](#passing-flags-to-one-detector)). There is no whole-repo
equivalent, so scan the detectors you care about one at a time:

```bash
sniff --only largest-methods . --include-tests
```

`--ignore` is the one exclusion you can pass to a whole scan. It is repeatable, and it
adds to the repo's committed globs rather than replacing them:

```bash
sniff --ignore "docs/**" --ignore "**/*.generated.ts" .
```

### Custom checks, without forking sniff

 Two ways to teach sniff your repo's conventions:

- **Local pattern rules.** Drop a `.yml` in `.sniff/rules/` and it runs in the same pass
  as the catalog. See [Add a rule](#add-a-rule).
- **External detectors.** Drop a `detector.yml` manifest under `.sniff/detectors/<name>/`
  and `sniff --list` picks it up alongside the built-ins.

Either way `sniff-create` picks the engine for you; [CONTRIBUTING.md](CONTRIBUTING.md#engines)
lists all five if you want to choose by hand.

## Language support

TypeScript, TSX, JavaScript and Python are covered by every detector that can
apply to them. Other languages are covered where the table says so. A detector
that cannot read your files says so instead of reporting zero findings, and a
scan skips it entirely unless you name it in `--only`.

**ALSO COVERS** lists the extra languages that detector reads beyond the four columns;
`-` means those four and nothing more.

<!-- language-matrix:start -->
| DETECTOR | typescript | tsx | javascript | python | ALSO COVERS |
| --- | --- | --- | --- | --- | --- |
| cognitive-complexity | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust |
| cyclomatic-complexity | yes | yes | yes | yes | c, cpp, csharp, go, java, ruby |
| deepest-nesting | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust |
| large-classes | yes | yes | yes | yes | - |
| large-inline-templates | yes | yes | no | no | - |
| largest-files | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust, scala, swift |
| largest-methods | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust, scala, swift |
| most-imports | yes | yes | yes | yes | - |
| most-parameters | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust |
| no-duplicate-string | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust, scala, swift |
<!-- language-matrix:end -->

`large-inline-templates` is Angular-only by design. `sniff-patterns` is not in the
table: it covers whatever its rules declare, so see the catalog below.

`sniff --list` prints the same coverage per detector, including any your repo adds. It
writes `all` where this table spells out fifteen language names; both mean the same
thing, every file type sniff walks.

## Pattern rules

The catalog `sniff-patterns` runs, grouped by the language a rule is written for and
sorted worst severity first. **ALSO RUNS ON** lists the other languages the same rule
applies to, so `-` means that one language only.

`sniff --list-patterns` prints the same rules plus any your repo adds under
`.sniff/rules/`, with one extra **ORIGIN** column marking each rule `core` or `local`.

<!-- pattern-catalog:start -->
### python

| SEVERITY | RULE | ALSO RUNS ON | MESSAGE |
| --- | --- | --- | --- |
| warning | py-bare-except | - | Bare except: swallows all exceptions, including KeyboardInterrupt and SystemExit; catch Exception or a specific type instead. |
| warning | py-broad-except | - | Catching Exception hides unrelated failures; catch the specific exception you can handle. |
| warning | py-mutable-default-arg | - | Mutable default argument is shared across all calls; use None and initialize inside the function body instead. |
| warning | py-nested-conditional-expr | - | Nested conditional expression; extract to if/elif/else or a helper function for readability. |
| info | py-import-outside-toplevel | - | Import inside a function hides the dependency; move it to the top of the module unless it breaks a cycle. |
| info | py-print-statement | - | Bare print() call; use a logging library instead of print for anything beyond throwaway debugging. |

### typescript

| SEVERITY | RULE | ALSO RUNS ON | MESSAGE |
| --- | --- | --- | --- |
| error | no-empty-catch | tsx, javascript | Empty catch block swallows errors; add error handling or use a comment explaining why. |
| warning | no-any-cast | tsx | 'as any' defeats type safety; use a precise type or 'unknown'. |
| warning | no-boolean-param | tsx | Boolean parameter enables unclear call sites; use a more descriptive type, enum, or extracted method. |
| warning | no-console-log | tsx, javascript | Remove console.log/debug/info in production; use a logging library. |
| warning | no-explicit-any | tsx | Explicit 'any' defeats type safety; use a precise type or 'unknown'. |
| warning | no-multiline-single-comment | tsx, javascript | Block comment spans multiple lines with only one content line; use single-line syntax instead. |
| warning | no-nested-ternary | tsx, javascript | Nested ternary; extract to if/else or a helper for readability. |
| warning | no-non-null-assertion | tsx | Non-null assertion operator `!` bypasses type safety; use proper null checks instead. |
| warning | prefer-at-over-length-index | tsx, javascript | Use `.at(-N)` instead of `arr[arr.length - N]`. |
| warning | prefer-optional-chain | tsx, javascript | Use optional chaining `?.` instead of `&&` guard for property access. |
<!-- pattern-catalog:end -->

### Add a rule

**With the plugin installed, ask your agent:** *"use sniff-create to add a rule that
flags X"*. The `sniff-create` skill picks the engine, writes the pattern, and checks
it against your actual code before saving anything, so you never guess at syntax.

**By hand**, if you would rather write it yourself:

1. **Work out the pattern.** Check out the
   [ast-grep guide](https://ast-grep.github.io/guide/introduction.html) for help, then
   try it live in the [playground](https://ast-grep.github.io/playground.html).
2. **Save it** as `.sniff/rules/<id>.yml` in the repo you scan.

   ```yaml
   # .sniff/rules/no-alert.yml
   id: no-alert
   language: typescript      # one language per rule
   severity: warning         # error | warning | info | hint
   message: "alert() blocks the page; use a dialog component instead."
   rule:
     pattern: alert($MSG)
   ```

3. **Run it.** `sniff --only sniff-patterns .` reports its findings alongside the
   catalog's. If nothing shows up, `sniff --list-patterns` tells you whether the rule
   loaded at all: yours appears tagged `local`.

Local rules run in the same `ast-grep scan` pass as the catalog, so both sets of
findings arrive together. An id that collides with a catalog rule is ignored with a
warning.

Want to contribute the rule to the global catalog? `sniff contribute <rule-id>` moves it upstream
into this catalog; see
[CONTRIBUTING.md](CONTRIBUTING.md#promoting-a-local-rule-from-a-project-that-uses-sniff)
for the fixtures it expects and the two backends it can use.

## CI mode

Gate PRs on code-smell regressions using the committed baseline:

1. Run `sniff baseline write` once and commit the resulting `.sniff/baseline.json`.
2. Add this action to a workflow, after a checkout step:

```yaml
- uses: actions/checkout@v4
- uses: ambervdberg/sniff@v0.14.0
  with:
    path: .
```

The action installs `ast-grep` and `sniff`, then runs `sniff diff --comment` against the
committed baseline, failing the job if any detector regressed. It needs the checkout: on
its own it would scan an empty workspace and find nothing to compare.

`--comment` only *formats* the result as a PR comment body; the action saves it to
`sniff-diff.md` in the workspace. (Running `sniff diff --comment` yourself just prints
it.) Nothing is posted for you. To get a comment on the PR, add a step that posts that
file.

Pin a release tag, as above, so a push to this repo cannot change what runs in your CI.
`@main` tracks the latest instead, at that cost.

**When the gate goes red.** Either fix the regression, or accept it: re-run
`sniff baseline write` and commit the updated `.sniff/baseline.json` in the same PR. The
baseline is a snapshot you own, not a target sniff enforces, so raising it deliberately
is a normal move. What it buys you is that the next PR cannot raise it by accident.

## Hooks

Installing the plugin registers two hooks on both Claude Code and Codex.

**At session start**, `sniff prime` runs once and its output goes into the agent's
context, so it knows the detectors and commands without being told. If the `sniff`
command is not on PATH the hook falls back to `uvx`, and if that is unavailable it
prints a one-line install hint and gets out of the way.

**On stop**, a suggest-create hook watches each turn and, when it spots a costly repeated
structural search (>= 6 read/grep/glob calls plus a structural prompt), prints one line
suggesting you run `sniff-create` to turn it into a token-cheap skill. Suggest-only: it
never creates anything and never blocks.

### Tuning the suggest-create hook

| Env var              | Default | Effect                                                       |
| -------------------- | ------- | ------------------------------------------------------------ |
| `SNIFF_CREATE_NUDGE` | on      | Set to `0`/`off`/`false`/`no` to silence the nudge entirely. |
| `SNIFF_MIN_CALLS`    | `6`     | Read/grep/glob calls in a turn needed to trip the heuristic. |

### Caveats

It sees one turn's tool calls and the prompt text, nothing else. So it misses some
searches and fires on some unrelated ones.

Too chatty? Raise `SNIFF_MIN_CALLS`, or set `SNIFF_CREATE_NUDGE=0` to turn it off.

## Contributing

Bugs and ideas go to the [issue tracker](https://github.com/ambervdberg/sniff/issues).
For code, [CONTRIBUTING.md](CONTRIBUTING.md) covers adding pattern rules and detectors,
running the tests, and promoting a rule you wrote in your own project into the shared
catalog.

## License

MIT, see [LICENSE](LICENSE). Release notes live in
[CHANGELOG.md](https://github.com/ambervdberg/sniff/blob/main/CHANGELOG.md).
