<p align="center">
  <img src="https://raw.githubusercontent.com/ambervdberg/sniff/main/assets/sniff-logo.png" alt="sniff logo" width="220">
</p>

# sniff

Token-cheap **code-smell CLI for AI agents**. Point `sniff` at a repo, get back a small
ranked table or findings list, never raw source or AST dumped into the conversation.

The CLI is **agent-agnostic** (Claude Code, Codex, Gemini, ...) and installs with
`uv tool install sniff-smells`. The bundled `SKILL.md` wrappers and the plugin manifests
(`.claude-plugin/` for Claude Code, `.codex-plugin/` for Codex) are integrations layered on
top: they teach an agent when to reach for `sniff`, but each one shells out to the same CLI.

The goal: a self-serve, private alternative to a SonarCloud-style scan, assembled from small
detectors you can grow one at a time. Each smell is its own detector or catalog rule, so an
agent only loads what it needs and answers for a handful of tokens.

## Install

```bash
uv tool install sniff-smells
uv tool install ast-grep-cli
```

Requires Python 3.10+ and works the same on Windows, macOS, and Linux. The first line puts the
`sniff` command on PATH via [uv](https://docs.astral.sh/uv/); the second installs
[`ast-grep`](https://ast-grep.github.io), the scan engine most detectors run on. One-time per
machine, not per repo. Run `sniff doctor` to confirm both are present.

No `uv`? `pip install sniff-smells` works the same.

## Quickstart

```bash
sniff .
sniff prime
```

`sniff .` runs every detector against the current directory and prints compact
ranked tables. `sniff prime` prints agent-optimized context (version, detectors,
prerequisites, usage hints) so an agent can learn the CLI in one call instead of
reading this file.

## Per-ecosystem setup

Every option below wraps the same `sniff` CLI, so `uv tool install sniff-smells` (or
`pip install sniff-smells`, see Install above) is still required underneath.

### Claude Code (plugin)

```bash
/plugin marketplace add https://github.com/ambervdberg/sniff
/plugin install sniff
```

To update: refresh the marketplace entry (`/plugin marketplace update sniff`), then re-run
`/plugin install sniff`.

### Codex (plugin)

```bash
codex plugin marketplace add ambervdberg/sniff
```

Then, in a Codex CLI session, run `/plugins` to install the `sniff` plugin from that
marketplace, and start a new session before its skills and hooks are available. This reads
the native manifest at `.codex-plugin/plugin.json`; the git repo itself is the marketplace
source (`.claude-plugin/marketplace.json` is the legacy-compatible repo marketplace path the
Codex packaging spec also accepts). To update: `codex plugin marketplace upgrade sniff`, then
reinstall from `/plugins`.

### Any agent (Codex, Cursor, ...)

Add to your AGENTS.md:

    For code-quality questions (largest methods, complexity, smells), run
    `sniff [DIR]` and read its compact tables instead of scanning files.
    Run `sniff prime` once to learn all commands.

Or paste the live output of `sniff prime` into your agent's instructions file
for the exact command list.

## Commands

| Command | What it does |
| --- | --- |
| `sniff [DIR]` | Scan `DIR` (default: `.`) with all detectors. |
| `sniff --all [DIR]` | Same as above (explicit alias). |
| `sniff --list` | List all available detectors. |
| `sniff --list-patterns` | List all pattern rules (RULE / SEVERITY / ORIGIN / ALSO RUNS ON / MESSAGE). |
| `sniff --only a,b [DIR]` | Run only the named detectors (e.g. `--only sniff-patterns` for pattern rules). |
| `sniff --skip a,b [DIR]` | Run all detectors except the named ones. |
| `sniff --json [DIR]` | Scan output as JSON instead of markdown (also works with `--list`). |
| `sniff --ignore GLOB [DIR]` | Exclude paths matching `GLOB`; repeatable, adds to `.sniff.toml`. |
| `sniff version` | Print the installed version. |
| `sniff doctor` | Check prerequisites (Python, ast-grep, manifests, `.sniff.toml`); exits 0/1. |
| `sniff prime` | Agent-optimized context (version, detectors, prereqs, usage hints); never scans. |
| `sniff baseline write [DIR]` | Save per-detector finding counts to `.sniff/baseline.json`. |
| `sniff diff [DIR]` | Compare a fresh scan to the saved baseline; exits 1 if any detector regressed. |
| `sniff diff --comment [DIR]` | Same as above, formatted as a markdown table for pasting into a PR comment. |
| `sniff contribute <rule-id>` | Promote a local rule to the shared catalog, via a local checkout or a `gh` fork + PR. |
| `sniff test-rules` | Run the rule fixture tests; needs a repo checkout, exits 0/1. |
| `sniff --help` | Show usage and examples. |

With `--only <one detector>`, extra flags are forwarded to that detector and beat
`.sniff.toml`; put them **after** `DIR` (`sniff --only largest-methods . --top 5`), since
`--top 1 DIR` would bind `1` as the directory to scan.

## Configuration

Drop a `.sniff.toml` in the root of the repo being scanned to turn rules off, re-grade
severities, skip detectors, retune thresholds, and ignore paths. `sniff doctor` validates it.

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

- `[rules]` only affects pattern rules. `[detectors]` affects the detectors, and each `<detector>.<arg>`
  key becomes a `--arg` flag on that detector.
- `globs` also accepts one string: `globs = "docs/**,**/*.generated.ts"`.
  Paths are matched from the root of the repo you scan.
- A section or key that sniff does not recognize is a warning, not an error, so a typo never stops a scan.

### What gets skipped

Three layers stack, in this order:

1. **Vendored and build directories**, always: `node_modules`, `dist`, `build`, `out`,
   `coverage`, `target`, `vendor`, `.venv`, `venv`, `.git`, `.nx`, `.angular`, `.astro`,
   `.next`, `.svelte-kit`, `.nuxt`, `.turbo`, `__pycache__`, `.claude`.
2. **Anything `.gitignore` excludes**, when the scanned directory is a git repo. Your
   `.git/info/exclude` and global ignore file count too, since sniff asks git rather than
   parsing the ignore files itself. Outside a git repo this layer is simply absent.
3. **Your own globs**: `[ignore] globs` in `.sniff.toml`, plus any `--ignore` flags.

`--ignore` is repeatable and *adds to* `.sniff.toml` rather than replacing it, so a one-off
exclusion cannot silently drop the ones a repo already committed:

```bash
sniff --ignore "docs/**" --ignore "**/*.generated.ts" .
```

### Local rules

A repo can carry its own pattern rules in `.sniff/rules/*.yml` without touching this
catalog. See [Add a rule](#add-a-rule).

### External detectors

Drop a `detector.yml` manifest under `.sniff/detectors/<name>/` in the project being scanned to
add a custom check without touching this repo. `sniff --list` picks it up alongside the
built-ins.

## CI mode

Gate PRs on code-smell regressions using the committed baseline:

1. Run `sniff baseline write` once and commit the resulting `.sniff/baseline.json`.
2. Add this action to a workflow:

```yaml
- uses: ambervdberg/sniff@main
  with:
    path: .
```

The action installs `ast-grep` and `sniff`, then runs `sniff diff --comment` against the committed
baseline, failing the job if any detector regressed.

## What's here

Detectors: everything `sniff --list` prints, usable from the CLI alone with no plugin
installed. Each also ships as a thin SKILL.md wrapper so an agent can trigger it by name.

| Detector | Does |
| --- | --- |
| `largest-methods` | Rank the longest methods/functions by line count. |
| `large-classes` | Rank the longest classes by line count. |
| `largest-files` | Rank the largest source files by non-blank line count (no AST). |
| `deepest-nesting` | Rank functions by control-flow nesting depth. |
| `cyclomatic-complexity` | Rank functions by cyclomatic complexity. |
| `cognitive-complexity` | Rank functions by cognitive complexity (nesting-weighted read difficulty). |
| `most-parameters` | Rank functions by parameter count (long-parameter-list smell). |
| `most-imports` | Rank files by import count (high-coupling smell). |
| `no-duplicate-string` | Flag repeated string literals that should be extracted as constants. |
| `large-inline-templates` | Rank Angular components by inline-template line count. |
| `sniff-patterns` | Run the pattern rule catalog in one `ast-grep scan` pass; compact findings table. |

Skills the plugin surface adds on top of that detector list:

| Skill | Does |
| --- | --- |
| `sniff` | Umbrella runner: runs **all** detectors in one pass. Wraps the CLI's default `sniff [DIR]` scan. |
| `sniff-create` | Scaffold a new smell skill or catalog rule from a short conversation. No CLI equivalent. |

`src/sniff/` contains the shared engine (harness.py for AST-grep integration,
node_metric.py for scoring).

## Language support

TypeScript, TSX, JavaScript and Python are covered by every detector that can
apply to them. Other languages are covered where the table says so. A detector
that cannot read your files says so instead of reporting zero findings, and a
scan skips it entirely unless you name it in `--only`.

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
| sniff-patterns | yes | yes | yes | yes | - |
<!-- language-matrix:end -->

`large-inline-templates` is Angular-only by design. `sniff-patterns` covers
whatever its rules declare, including any you add under `.sniff/rules/`, so this
row grows with the catalog. Run `sniff --list` for the same coverage per
detector, including detectors your repo adds.

## Pattern rules

The catalog `sniff-patterns` runs, worst severity first within each language.
`sniff --list-patterns` prints the same rules, plus any your repo adds under
`.sniff/rules/`.

<!-- pattern-catalog:start -->
### python

| SEVERITY | RULE | ALSO RUNS ON | MESSAGE |
| --- | --- | --- | --- |
| warning | py-bare-except | - | Bare except: swallows all exceptions, including KeyboardInterrupt and SystemExit; catch Exception or a specific type instead. |
| warning | py-mutable-default-arg | - | Mutable default argument is shared across all calls; use None and initialize inside the function body instead. |
| warning | py-nested-conditional-expr | - | Nested conditional expression; extract to if/elif/else or a helper function for readability. |
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

1. **Work out the pattern.** You can checkout [astgrep.com/guide/](https://astgrep.com/guide/introduction) for help.
   You can test it here: [ast-grep playground](https://astgrep.com/playground.html).
2. **Save it** as `.sniff/rules/<id>.yml` in the repo you scan.

   ```yaml
   # .sniff/rules/no-alert.yml
   id: no-alert
   language: typescript      # one language per rule
   severity: warning         # error | warning | info
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

Want to contribute the rule to the catalog? Add examples at `.sniff/rule-tests/<id>.yml`
first:

```yaml
id: no-alert
valid:
  - |
    showDialog("boom");
invalid:
  - |
    alert("boom");
```

Then `sniff contribute <rule-id>` moves it upstream, `--dry-run` first if you want to
see which backend it would use. Point `SNIFF_REPO` (or `repo = "..."` in
`~/.sniff/config.toml`) at a local sniff checkout and the rule and its fixtures are
copied there on a `rule/<rule-id>` branch with the fixture tests run, leaving the commit
and PR to you. Otherwise it uses the `gh` CLI: fork, branch, commit, push, and open a PR
against `ambervdberg/sniff`. Guards run first, so a missing rule, missing fixtures, or a
colliding id fails before anything moves.

## Engines

A smell needs an engine. `sniff-create` picks the right one when you make a new check; see
[CONTRIBUTING.md](CONTRIBUTING.md#engines) for the full breakdown of all five.

| Engine | For | Example |
| --- | --- | --- |
| **pattern rule** | a specific code shape, flagged with a severity | `any` type, empty `imports: []` |
| **node span** | rank AST nodes by line count | largest methods, large classes |
| **node metric** | score each method/class from its AST | nesting depth, cyclomatic / cognitive complexity, inline-template line count |
| **file metric** | a number per file, no AST | largest files (split candidates) |

`pattern rule`, `node span`, and `node metric` run on [ast-grep](https://ast-grep.github.io);
`file metric` is plain Python. A fifth engine, cross-file (a whole-project graph, for smells
like inheritance depth), is planned but not built yet.

## Layout

```
.claude-plugin/   plugin.json (skills) + marketplace.json
.codex-plugin/    plugin.json (native Codex plugin manifest)
.github/workflows/  CI (test matrix, ubuntu + windows) and release (PyPI trusted publishing)
action.yml        composite GitHub Action; CI mode (see above) depends on it
hooks/hooks.json  lifecycle hooks (SessionStart -> sniff prime, Stop -> costly-search nudge);
                  single source for BOTH hosts, since Claude Code and Codex each
                  auto-discover this exact path
assets/           plugin logo + composer icon (the 1024px master is untracked, in docs/)
evals/            LLM eval harness: cases.jsonl, runner.py (simulated), scorer.py, smoke/ (real-agent)
LICENSE           MIT
src/sniff/        installable package (dist sniff-smells, command sniff)
  cli.py            entry point, argument parsing, subcommands
  config.py         .sniff.toml config loading
  discovery.py      built-in + external (.sniff/detectors/) detector discovery
  contribute.py     `sniff contribute` upstreaming flow
  harness.py        shared ast-grep integration
  node_metric.py    per-node scoring (complexity, nesting, ...)
  rules_testing.py  `sniff test-rules` fixture runner
  detectors/         one module per built-in metric detector (10)
  patterns_detector.py  the sniff-patterns rule-catalog detector (11th, at package root)
  patterns/          rule catalog: rules/, rule-tests/, sgconfig.yml
skills/           thin SKILL.md wrappers around the sniff CLI, one per detector
  largest-methods/  large-classes/  largest-files/  deepest-nesting/
  cyclomatic-complexity/  cognitive-complexity/  most-parameters/  most-imports/
  no-duplicate-string/  large-inline-templates/  sniff/  sniff-patterns/
  sniff-create/     scripts/ + templates/, the skill/rule generator
tests/            pytest suite
scripts/          bump_version.py and other maintenance scripts
docs/             design spec
```

## Suggest-create hook

A `Stop` hook (defined in `hooks/hooks.json`, auto-discovered by both Claude Code and Codex)
watches each turn and, when it spots a costly repeated structural search (>= 6
read/grep/glob calls plus a structural prompt), prints one line suggesting you run
`sniff-create` to turn it into a token-cheap skill. Suggest-only: it never creates
anything and never blocks.
The detector lives in `skills/sniff-create/scripts/detect_costly_search.py`.

### Tuning

| Env var | Default | Effect |
| --- | --- | --- |
| `SNIFF_CREATE_NUDGE` | on | Set to `0`/`off`/`false`/`no` to silence the nudge entirely. |
| `SNIFF_MIN_CALLS` | `6` | Read/grep/glob calls in a turn needed to trip the heuristic. |

### Caveats

It sees one turn's tool calls and the prompt text, nothing else. So it misses some
searches and fires on some unrelated ones.

Too chatty? Raise `SNIFF_MIN_CALLS`, or set `SNIFF_CREATE_NUDGE=0` to turn it off.

## Tests

```bash
uv sync --extra dev
uv run python -m pytest tests -q
```

## Release

`python scripts/bump_version.py <new-version>` rewrites the version in five places together:
`pyproject.toml`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, every plugin
entry in `.claude-plugin/marketplace.json`, and `uv.lock` (which it refreshes by running
`uv lock` itself). `tests/test_version_consistency.py` fails the build if any of the five
drift apart. After bumping, update `CHANGELOG.md`, commit, and tag `v<new-version>`.

What gets published is an explicit allowlist in `[tool.hatch.build.targets.sdist]`, not
whatever happens to sit in the repo. Hatchling's default sweeps in every file it can see,
including ones git ignores through a nested `.gitignore`, which is how 8.5 MB of `.beads`
tracker state ended up in a release. Patterns need a leading `/` to anchor them to the
project root, or they match at any depth. The plugin surface (`skills/`, `hooks/`, the two
`plugin.json` manifests) deliberately stays out: plugin users install from the git
marketplace, and the PyPI package is only the `sniff` CLI.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add new pattern rules, run tests, and promote
rules from consumer projects into the catalog.
