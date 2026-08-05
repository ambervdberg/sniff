<div align="center">
  <img src="https://raw.githubusercontent.com/ambervdberg/sniff/main/assets/sniff-logo.png" alt="sniff logo" width="220">

  [![PyPI](https://img.shields.io/pypi/v/sniff-smells)](https://pypi.org/project/sniff-smells/)
</div>

> [!IMPORTANT]
> Sniff is still in early development. More detectors, pattern rules and language support are coming. <br>
> Sniff cannot find all mistakes. It is intended to be a cost-effective way to identify some obvious code quality issues.

# sniff

`sniff` prints ranked tables of the repo's "worst" code: longest methods, deepest nesting, empty catches etc in a concise way.

It complements linters and code checkers like ESLint, Ruff, or SonarQube. They judge lines per language; sniff ranks the whole repo.

Same CLI for you and your agent. Small output means an agent learns the worst offenders for a few tokens.

Measured against an agent working without it: **53% average cost reduction** per
question, and the agent reads almost no files. See
[Initial case study](#initial-case-study).

[Install](#install) · [Quickstart](#quickstart) ·
[Use it from an agent](#use-it-from-an-agent) · [Initial case study](#initial-case-study) ·
[Detectors vs pattern rules](#detectors-vs-pattern-rules) · [The detectors](#the-detectors) ·
[Pattern rules](#pattern-rules) · [Commands](#commands) ·
[Configuration](#configuration) · [Language support](#language-support) ·
[Hooks](#hooks) · [Contributing](#contributing)

## Install

```bash
uv tool install sniff-smells
```

One line installs the `sniff` command via [uv](https://docs.astral.sh/uv/), including
[`ast-grep`](https://ast-grep.github.io), the parser 9 of the 13 detectors run on.
One-time per machine, not per repo.

Needs Python 3.10+ and works the same on Windows, macOS, and Linux. Run `sniff doctor`
to confirm everything is present.

No `uv`? `pip install sniff-smells` works the same.

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
sniff: 13 detectors over '.': cognitive-complexity, cyclomatic-complexity, deepest-nesting, ...

## cognitive-complexity

Hardest to read: 10 of 412 functions by cognitive complexity (typescript; tests excluded):

| COGNITIVE | NAME           | LOCATION                         |
| --------- | -------------- | -------------------------------- |
| 31        | reconcileOrder | src/checkout/order-service.ts:88 |
| 24        | applyDiscounts | src/checkout/pricing.ts:142      |
| 19        | renderRow      | src/ui/cart-table.tsx:57         |

... one section per detector ...

## sniff-patterns

sniff-patterns: 23 findings, 4 of 22 rules matched in '.' (tests excluded)

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

Want more or fewer rows? Run one detector on its own and pass `--top`:

```bash
sniff --only cognitive-complexity . --top 25
```

Or set it for every scan in [`.sniff.toml`](#configuration). `--top` is a
per-detector flag, so it needs `--only`; see
[Passing flags to one detector](#passing-flags-to-one-detector).

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

## Initial case study

![average saved](https://img.shields.io/badge/average_cost_saved-53%25-brightgreen)

**Scope, stated plainly:** 2 repositories, 8 question/repo pairs, 1 model, 1 run
per condition, no variance data. This is one measurement, not an ongoing
benchmark.

**Repositories used**, pinned by commit:

| Repo | Language | Commit | Files | Lines |
|---|---|---|---|---|
| excalidraw | TypeScript, TSX | `786ab26` | 654 | 188k |
| scrapy | Python | `a499dc9` | 475 | 84k |

API costs from Claude Code runs on Sonnet 5, once with sniff on `PATH` and once
without. Average **53% cost reduction** across the 8 pairs (range 22% to 93%);
the saving scales with how vague the question is, since a vague one like "find
all code smells" has no natural stopping point for an unaided agent to read
toward.

Full methodology, the per-question cost table, accuracy scoring, what sniff
misses compared to an unaided read, and the caveats that come with a single-run
measurement: [docs/benchmark.md](https://github.com/ambervdberg/sniff/blob/main/docs/benchmark.md).

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
| `duplicate-code`         | Rank the largest blocks of copy-pasted code, renames and async twins included (no AST). |
| `self-admitted-debt`     | Rank files by the TODO/FIXME/HACK/XXX markers in their comments (no AST).          |
| `large-inline-templates` | Rank Angular components by inline-template line count.                            |
| `sniff-patterns`         | Run the pattern rule catalog in one `ast-grep scan` pass; compact findings table. |

With the plugin installed, two more skills are available beyond the detectors above:

| Skill          | Does                                                                                             |
| -------------- | ------------------------------------------------------------------------------------------------ |
| `sniff`        | Umbrella runner: runs **all** detectors in one pass. Wraps the CLI's default `sniff [DIR]` scan. |
| `sniff-create` | Scaffold a new smell skill or catalog rule from a short conversation. No CLI equivalent.         |

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
| warning | py-instantiated-default-arg | - | Default argument is instantiated once at def time and shared by every caller; use None and build it in the function body. |
| warning | py-mutable-class-attribute | - | Mutable class attribute is shared by every instance; build it per instance in __init__ instead. |
| warning | py-mutable-default-arg | - | Mutable default argument is shared across all calls; use None and initialize inside the function body instead. |
| warning | py-nested-conditional-expr | - | Nested conditional expression; extract to if/elif/else or a helper function for readability. |
| warning | py-private-attribute-access | - | Reaching into another object's private attribute; use its public API, or the owner can break you in a patch release. |
| info | py-global-statement | - | Rebinding module-level state with `global` hides the effect from the call site; pass the value or hold it on an object instead. |
| info | py-import-outside-toplevel | - | Import inside a function hides the dependency; move it to the top of the module unless it breaks a cycle. |
| info | py-magic-number | - | Unexplained numeric literal; bind it to a named constant so its meaning travels with it. |
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
| warning | no-private-property-access | tsx, javascript | Reaching into another object's private property; use its public API, or the owner can break you in a patch release. |
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
[CONTRIBUTING.md](https://github.com/ambervdberg/sniff/blob/main/CONTRIBUTING.md#promoting-a-local-rule-from-a-project-that-uses-sniff)
for the fixtures it expects and the two backends it can use.

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
| `sniff baseline write [DIR]`  | Save today's per-detector finding fingerprints to `.sniff/baseline.json`. Commit that file. |
| `sniff diff [DIR]`            | Re-scan and compare against that baseline; exits 1 if any detector regressed. Add `--comment` to format the result as a markdown table. |
| `sniff contribute <rule-id>`  | Send one of your local pattern rules upstream into the shared catalog.              |

The first two are a pair: write a baseline once, then have `sniff diff` answer "did this
change make the repo worse". Useful after an agent has edited a pile of files at once.
When it goes red, either fix the regression or accept it by re-running
`sniff baseline write` and committing the new `.sniff/baseline.json`: the baseline is a
snapshot you own, not a target sniff enforces. The third command is covered under
[Add a rule](#add-a-rule).

**Exit codes.**

`sniff doctor` and `sniff diff` exit 1 on failure, so both can gate a
build.

A plain `sniff [DIR]` exits 0 however many findings it reports: it reports, it does not
judge. It exits 1 only when the scan itself could not be trusted, meaning a `DIR` that
does not exist or a detector that failed to run. Use `sniff diff` for the gate.

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
severities, skip detectors, retune thresholds, and ignore paths; `sniff doctor` validates
it. Vendored/build directories and anything `.gitignore` excludes are skipped by default,
and every detector skips test code unless you pass `--include-tests`.

Full `.sniff.toml` syntax, the default skip list, and how to add local pattern rules or
external detectors without forking sniff:
[docs/configuration.md](https://github.com/ambervdberg/sniff/blob/main/docs/configuration.md).

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
| duplicate-code | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust, scala, swift |
| large-classes | yes | yes | yes | yes | - |
| large-inline-templates | yes | yes | no | no | - |
| largest-files | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust, scala, swift |
| largest-methods | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust, scala, swift |
| most-imports | yes | yes | yes | yes | - |
| most-parameters | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust |
| no-duplicate-string | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust, scala, swift |
| self-admitted-debt | yes | yes | yes | yes | c, cpp, csharp, go, java, kotlin, php, ruby, rust, scala, swift |
<!-- language-matrix:end -->

`large-inline-templates` is Angular-only by design. `sniff-patterns` is not in the
table: it covers whatever its rules declare, so see the [Pattern rules](#pattern-rules) catalog.

`sniff --list` prints the same coverage per detector, including any your repo adds. It
writes `all` where this table spells out fifteen language names; both mean the same
thing, every file type sniff walks.

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
For code, [CONTRIBUTING.md](https://github.com/ambervdberg/sniff/blob/main/CONTRIBUTING.md)
covers adding pattern rules and detectors, running the tests, and promoting a rule you
wrote in your own project into the shared catalog.

## License

MIT, see [LICENSE](LICENSE). Release notes live in
[CHANGELOG.md](https://github.com/ambervdberg/sniff/blob/main/CHANGELOG.md).
