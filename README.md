# sniff

Token-cheap **code-smell CLI for AI agents**. Point `sniff` at a repo, get back a small
ranked table or findings list, never raw source or AST dumped into the conversation.

The CLI is **agent-agnostic** (Claude Code, Codex, Gemini, ...) and installs with
`uv tool install sniff-smells`. The bundled `SKILL.md` wrappers and the `.claude-plugin/`
marketplace packaging are integrations layered on top: they teach an agent when to reach for
`sniff`, but each one shells out to the same CLI.

The goal: a self-serve, private alternative to a SonarCloud-style scan, assembled from small
detectors you can grow one at a time. Each smell is its own detector or catalog rule, so an
agent only loads what it needs and answers for a handful of tokens.

## Install

```bash
uv tool install sniff-smells
uv tool install ast-grep-cli
```

Requires Python 3.9+ and works the same on Windows, macOS, and Linux. The first line puts the
`sniff` command on PATH via [uv](https://docs.astral.sh/uv/); the second installs
[`ast-grep`](https://ast-grep.github.io), the scan engine most detectors run on. One-time per
machine, not per repo. Run `sniff doctor` to confirm both are present.

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

### Claude Code (plugin)

```bash
/plugin marketplace add https://github.com/ambervdberg/sniff
/plugin install sniff
```

To update: refresh the marketplace entry (`/plugin marketplace update sniff`), then re-run
`/plugin install sniff`. The plugin wraps the same `sniff` CLI as the skills do, so
`uv tool install sniff-smells` is still required underneath.

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
| `sniff --list-patterns` | List all pattern rules (RULE / SEVERITY / ORIGIN / MESSAGE). |
| `sniff --only a,b [DIR]` | Run only the named detectors (e.g. `--only sniff-patterns` for pattern rules). |
| `sniff --skip a,b [DIR]` | Run all detectors except the named ones. |
| `sniff --json [DIR]` | Scan output as JSON instead of markdown (also works with `--list`). |
| `sniff version` | Print the installed version. |
| `sniff doctor` | Check prerequisites (Python, ast-grep, manifests, version drift, `.sniff.toml`); exits 0/1. |
| `sniff prime` | Agent-optimized context (version, detectors, prereqs, usage hints); never scans. |
| `sniff baseline write [DIR]` | Save per-detector finding counts to `.sniff/baseline.json`. |
| `sniff diff [DIR]` | Compare a fresh scan to the saved baseline; exits 1 if any detector regressed. |
| `sniff diff --comment [DIR]` | Same as above, formatted as a markdown table for pasting into a PR comment. |
| `sniff contribute <rule-id>` | Promote a local rule to the shared catalog, via a local checkout or a `gh` fork + PR. |
| `sniff test-rules` | Run the rule fixture tests; needs a repo checkout, exits 0/1. |
| `sniff --help` | Show usage and examples. |

## Configuration

Drop a `.sniff.toml` in the root of the repo being scanned to turn rules off, re-grade
severities, skip detectors, retune thresholds, and ignore paths. `sniff doctor` validates it.

```toml
[rules]
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

- The parser is a hand-written TOML subset (stdlib only, Python 3.9): `[section]` headers plus
  flat `key = value` lines, with quoted strings, ints, or `true`/`false` as values. Unknown
  sections and keys produce a warning, never an error.
- `[ignore] globs` accepts the array form above or the flat form
  `globs = "docs/**,**/*.generated.ts"`. Globs are matched against the scan-root-relative path.
- `[rules]` targets the `sniff-patterns` catalog; `[detectors]` targets every detector, and its
  dotted keys are folded into that detector's own CLI args before it runs.

### Local rules

A repo can carry its own pattern rules in `.sniff/rules/*.yml` without touching this catalog.
They are discovered alongside the core rules and run in the same `ast-grep scan` pass, so core
and local findings arrive together. `sniff --list-patterns` tags each row `core` or `local` in
the ORIGIN column. A local rule whose id collides with a core rule id is ignored with a warning.

Add fixtures next to it at `.sniff/rule-tests/<rule-id>.yml`, then promote a rule that has
proven itself:

```bash
sniff contribute <rule-id> --dry-run    # show which backend would be used
sniff contribute <rule-id>
```

Two backends. If `SNIFF_REPO` (or `repo = "..."` in `~/.sniff/config.toml`) points at a local
sniff checkout, the rule and its fixtures are copied there on a `rule/<rule-id>` branch and the
fixture tests run, leaving the commit and PR to you. Otherwise `sniff contribute` falls back to
the `gh` CLI: fork, branch, commit, push, and open a PR against `ambervdberg/sniff`. Guards run
first, so a missing rule, missing fixtures, or a core-id collision fails before anything moves.

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

| Skill | Does |
| --- | --- |
| `largest-methods` | Rank the longest methods/functions by line count. |
| `large-classes` | Rank the longest classes by line count. |
| `largest-files` | Rank the largest source files by non-blank line count (no AST). |
| `deepest-nesting` | Rank functions by control-flow nesting depth (S134). |
| `cyclomatic-complexity` | Rank functions by cyclomatic complexity (S1541). |
| `cognitive-complexity` | Rank functions by cognitive complexity (nesting-weighted read difficulty). |
| `most-parameters` | Rank functions by parameter count (long-parameter-list smell). |
| `most-imports` | Rank files by import count (high-coupling smell). |
| `no-duplicate-string` | Flag repeated string literals that should be extracted as constants. |
| `large-inline-templates` | Rank Angular components by inline-template line count. |
| `sniff` | Umbrella runner: runs **all** detectors in one pass. Use this for a full scan. |
| `sniff-patterns` | Run the pattern rule catalog in one `ast-grep scan` pass; compact findings table. |
| `sniff-create` | Scaffold a new smell skill or catalog rule from a short conversation. |

`src/sniff/` contains the shared engine (harness.py for AST-grep integration,
node_metric.py for scoring).

## Engines

A smell needs an engine. `sniff-create` picks the right one when you make a new check:

| Engine | For | Example |
| --- | --- | --- |
| **pattern rule** | a specific code shape, flagged with a severity | `any` type, empty `imports: []` |
| **node metric** | score each method/class from its AST | nesting depth, cyclomatic / cognitive complexity, inline-template line count |
| **file metric** | a number per file, no AST | largest files (split candidates) |

`pattern rule` and `node metric` run on [ast-grep](https://ast-grep.github.io);
`file metric` is plain Python. A fourth engine (cross-file project graph, for smells like
inheritance depth) is planned, not available yet.

## Layout

```
.claude-plugin/   plugin.json (skills, Stop hook) + marketplace.json
.codex-plugin/    plugin.json (native Codex plugin manifest)
.github/workflows/  CI (test matrix, ubuntu + windows) and release (PyPI trusted publishing)
hooks.json        Codex lifecycle hooks (SessionStart -> sniff prime, Stop -> costly-search nudge)
evals/            LLM eval harness: cases.jsonl, runner.py (simulated), scorer.py, smoke/ (real-agent)
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

A `Stop` hook (declared in `plugin.json`) watches each turn and, when it spots a
costly repeated structural search (>= 6 read/grep/glob calls plus a structural
prompt), prints one line suggesting you run `sniff-create` to turn it into a
token-cheap skill. Suggest-only: it never creates anything and never blocks.
The detector lives in `skills/sniff-create/scripts/detect_costly_search.py`.

### Tuning

| Env var | Default | Effect |
| --- | --- | --- |
| `SNIFF_CREATE_NUDGE` | on | Set to `0`/`off`/`false`/`no` to silence the nudge entirely. |
| `SNIFF_MIN_CALLS` | `6` | Read/grep/glob calls in a turn needed to trip the heuristic. |

### Caveats

It is a **heuristic**, not a judgement of intent. The hook sees the turn's tool
calls and the prompt text, never your reasoning, so:

- Expect the occasional **miss** (a real repeated search the prompt did not phrase
  structurally) and the occasional **false positive** (lots of reads for an
  unrelated reason). Both are cheap: a missed nudge costs nothing, a stray one is a
  single ignorable line.
- It only inspects the **most recent turn**; a search spread across several turns
  does not accumulate.
- Raise `SNIFF_MIN_CALLS` if a project trips it too often; lower it to catch
  searches sooner. Turn it off per session with `SNIFF_CREATE_NUDGE=0` when it is
  noise for the task at hand.

## Tests

```bash
python -m pytest tests -q
```

## Release

`python scripts/bump_version.py <new-version>` rewrites the version in `pyproject.toml`,
`.claude-plugin/plugin.json`, and `.codex-plugin/plugin.json` together, so `sniff doctor`'s
version-drift check stays green. After bumping, update `CHANGELOG.md`, commit, and tag
`v<new-version>`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add new pattern rules, run tests, and promote
rules from consumer projects into the catalog.
