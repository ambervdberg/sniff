# Contributing to sniff

Found a bug, or want a detector sniff does not have? Open an
[issue](https://github.com/ambervdberg/sniff/issues). Include the command you ran, what
you expected, and the output of `sniff doctor`. No checkout needed.

Came here to send a rule you wrote in your own project upstream? Also no checkout
needed: skip to
[Promoting a local rule](#promoting-a-local-rule-from-a-project-that-uses-sniff).

The rest of this file is for changing sniff itself.

## Dev setup

Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.10+.

1. Clone the repo and install prerequisites (one-time):
   ```bash
   git clone https://github.com/ambervdberg/sniff.git
   cd sniff
   uv sync --extra dev
   ```

   This installs ast-grep too, so no separate install is needed for development.

2. Verify setup:
   ```bash
   uv run sniff doctor
   ```

3. Run the test suite:
   ```bash
   uv run python -m pytest tests -q
   ```

Always go through `uv run`. It puts this repo's `sniff` on PATH, so tests that
shell out to the CLI exercise your working tree rather than whatever global
`uv tool install sniff-smells` build happens to be installed.

## Repo layout

Only the entries a change tends to land in. Everything else is named for what it does.

```
src/sniff/           the installable package (dist sniff-smells, command sniff)
  detectors/           one module per built-in metric detector (11)
  patterns/            the rule catalog: rules/, rule-tests/, sgconfig.yml
  patterns_detector.py the 12th detector, at the package root rather than in detectors/
skills/              one thin SKILL.md wrapper per detector, plus sniff/ and sniff-create/
hooks/hooks.json     lifecycle hooks, and the single source for BOTH hosts, since Claude
                     Code and Codex each auto-discover this exact path
.claude-plugin/      plugin.json + marketplace.json (Claude Code)
.codex-plugin/       plugin.json (Codex)
action.yml           composite GitHub Action behind the README's CI mode
scripts/             update_docs.py (PR checklist) and bump_version.py (releases only)
evals/               agent-routing eval harness; see Evals below
```

The git repo is itself the plugin marketplace for both hosts. Codex reads the native
manifest at `.codex-plugin/plugin.json`; `.claude-plugin/marketplace.json` is the
legacy-compatible repo marketplace path the Codex packaging spec also accepts, and the
one Claude Code uses.

## Adding a pattern rule

Rules live in `src/sniff/patterns/rules/` as YAML files, with fixtures alongside in
`src/sniff/patterns/rule-tests/`.

The quickest way to add one is the `sniff-create` Claude skill: ask Claude to "create a
sniff rule for <the smell>". It drafts the rule with you, validates it against the current
repo, then writes the rule and its fixture file.

To hand-write one instead, add the rule (e.g. `rules/no-console-log.yml`) and a fixture
file of the same name under `rule-tests/`. Every fixture file needs at least one invalid
snippet (must be flagged) and one valid snippet (must stay clean). `no-empty-catch.yml`
and `no-explicit-any.yml` are the ones to copy.

A rule with no fixture file fails `sniff test-rules` by name. The one exception is a rule
implemented in Python inside `patterns/format.py` rather than as ast-grep YAML, which
`ast-grep test` cannot run: those are listed in `PYTHON_RULES` in
`src/sniff/rules_testing.py` and skipped. Adding to that set means giving up fixture
coverage, so treat it as a last resort.

Either way, run the fixture suite before committing. All fixtures must pass:

```bash
uv run sniff test-rules
```

`sniff test-rules` is maintainer-only: it reads the catalog sources under
`src/sniff/patterns/`, which the published wheel does not ship, so it works from a
checkout and nowhere else. That is why it is absent from `sniff --help` and from the
README's command table, and why it always runs through `uv run` here.

## Promoting a local rule from a project that uses sniff

This section is for a *different* repo: one where you installed the sniff CLI
and wrote a project-specific rule that turned out generally useful. Run these
steps from that project, not from this sniff repo, to send the rule upstream
into this catalog.

1. In that project (not here), create a local rule under `.sniff/rules/<rule-id>.yml`,
   with matching fixtures at `.sniff/rule-tests/<rule-id>.yml`.

2. Prove the rule works by scanning that project with it:
   ```bash
   sniff --only sniff-patterns .
   ```

   `sniff test-rules` is maintainer-only, so it is not available here. Your fixtures get
   tested in the next step instead, once the rule has been copied into the catalog.

3. Contribute:
   ```bash
   sniff contribute <rule-id>
   ```

Which backend that uses depends on your config:

- If the `SNIFF_REPO` env var or `~/.sniff/config.toml` (with `repo = "..."`) points at a
  local sniff checkout, the rule is copied there, its fixtures are tested, and it is
  staged on a branch. Review and open the PR yourself.
- Otherwise it forks the repo through the `gh` CLI and opens the PR for you.

Guards: the rule must exist locally, have a fixture file, and not collide with a rule id
already in the catalog.

## Regenerating the docs

Two README tables are generated from the code, not written by hand: the language
support matrix (which languages each detector reads) and the pattern rule catalog.
Run this after adding a rule, changing a rule's `metadata: languages:`, or changing
a detector's `LANGUAGES`:

```bash
uv run python scripts/update_docs.py
```

Each table sits between its own pair of markers, `<!-- language-matrix:start -->` to
`<!-- language-matrix:end -->` and `<!-- pattern-catalog:start -->` to
`<!-- pattern-catalog:end -->`, and the script rewrites only what is inside those two
spans. Everything else in the README stays hand-written. Add `--check` to see whether the
README is stale without changing it.

Tests enforce this, so a forgotten run shows up as a failing test rather than a README
that claims support sniff does not have.

## Evals

`evals/` measures whether an agent picks the right `sniff` command from a prompt. Not
part of CI and not needed for most PRs: run it when you change a surface an agent reads,
meaning a SKILL.md, `sniff prime`, `sniff --help`, or the README's command table.

A real run calls a hosted model, so it needs more than the dev extra installs. `--dry-run`
does not, and is the only part that works out of the box:

```bash
uv run python evals/runner.py --dry-run    # prints the prompts, no API calls
```

For a real run, install the client for whichever model you target and export its key.
The default model is `gpt-5.4-nano`; a `--model claude-*` value routes to Anthropic
instead.

```bash
uv run --with openai python evals/runner.py               # needs OPENAI_API_KEY
uv run --with anthropic python evals/runner.py --model claude-haiku-4-5-20251001
uv run python evals/scorer.py --results evals/results/<file>.jsonl
```

`evals/cases.jsonl` holds the prompts, `runner.py` simulates an agent in a single API
call, and `scorer.py` grades routing and hallucinated flags. A simulated pass is not
proof: `evals/smoke/README.md` describes the hand-run real-session complement, which
sees context the simulation does not and so catches regressions it misses.

## Conventions

Name rule ids in kebab-case. Prefix with `no-` to forbid a pattern (`no-console-log`,
`no-explicit-any`), or `prefer-` to recommend an alternative (`prefer-const-over-let`).

Severity guidance, with a shipped rule as the example of each:

- `error`: nearly always a real bug (`no-empty-catch`)
- `warning`: maintainability smell, likely a real issue. The default
  (`no-explicit-any`, `no-nested-ternary`)
- `info` or `hint`: stylistic preference, not actionable for every project
  (`py-print-statement`)

There is no linter or formatter in this repo, and CI runs none, so nothing will reformat
your patch. Match the surrounding file instead: markdown wraps near 90 columns, Python
stays comfortably under 120, and both use plain LF endings.

## Engines

A new check needs one of five engine types (the same five `sniff-create` picks from).
Use the engine that fits your smell:

| Engine | For | Example |
| --- | --- | --- |
| **pattern rule** | a specific code shape, flagged with a severity | any type, empty imports: [] |
| **node span** | rank AST nodes by line count | largest methods, large classes |
| **node metric** | score each method/class from its AST | nesting depth, cyclomatic / cognitive complexity, inline-template line count |
| **file metric** | a number per file, no AST | largest files (split candidates) |
| **cross-file** (planned, not built yet) | needs a whole-project graph | inheritance depth |

Pattern rules and node metrics run on [ast-grep](https://ast-grep.github.io). File metrics
are plain Python.

Pattern rules go in the catalog (see [Adding a pattern rule](#adding-a-pattern-rule)).
The other three engines are detectors; see below.

External, project-specific detectors need no code in this repo at all: drop a
`detector.yml` manifest plus its script under `<scan-dir>/.sniff/detectors/<name>/` and
sniff discovers it automatically when scanning that directory. Consumer repos can also
tune a run through a `.sniff.toml` config file (see the Configuration section of the
README) without touching this repo.

## Adding a detector

Built-in detectors are registry modules, run in-process, with no manifest involved. Four
things have to land together, and a detector that skips any of them is half-wired:

1. **The module.** Add `src/sniff/detectors/<name>.py`. Copy the closest existing
   detector rather than starting blank: `deepest_nesting.py` for a node metric,
   `largest_files.py` for a file metric. It must expose `NAME`, `TITLE`, `DEFAULT_ARGS`,
   `LANGUAGES`, and `main(argv) -> int`, and its argument parser should accept `--top`,
   `--include-tests`, and `--extra-ignore` like every other detector does.

2. **The registration.** Import the module in `src/sniff/detectors/__init__.py` and add
   it to `BUILTIN`. Nothing discovers it otherwise.

3. **The skill wrapper.** Add `skills/<name>/SKILL.md`, one per detector, so agents can
   trigger it by name. Copy `skills/deepest-nesting/SKILL.md` and rewrite the
   frontmatter `description`: that text is the whole routing signal, so spell out the
   questions a user would actually ask.

4. **The generated docs.** Run `uv run python scripts/update_docs.py` so the README's
   language matrix picks up your `LANGUAGES`. `tests/test_detector_languages.py` fails
   the build if you forget.

Then `uv run sniff --list` should show it and `uv run sniff doctor` should still pass.

## PR checklist

Before opening a PR:

- [ ] `uv run sniff test-rules` passes
- [ ] `uv run python scripts/update_docs.py` run, if a rule or a detector's languages changed
- [ ] `uv run python -m pytest tests -q` passes
- [ ] Add a note as a new entry at the top of `CHANGELOG.md`
- [ ] If this is a version bump (not a feature PR), see [Release](#release). Never
      hand-edit a version.
- [ ] CI passes (GitHub Actions will run the checks)

## Release

Never hand-edit a version. `python scripts/bump_version.py <new-version>` rewrites all
six declarations together, and `tests/test_version_consistency.py` fails the build if any
of them drift apart:

- `pyproject.toml`
- `.claude-plugin/plugin.json`
- `.codex-plugin/plugin.json`
- every plugin entry in `.claude-plugin/marketplace.json`
- `uv.lock`, refreshed by running `uv lock` itself
- the `ambervdberg/sniff@v<version>` action pin in the README's CI-mode snippet, which
  users copy verbatim into their own workflow

After bumping, update `CHANGELOG.md`, commit, and tag `v<new-version>`.

What gets published is an explicit allowlist in `[tool.hatch.build.targets.sdist]`, not
whatever happens to sit in the repo. Hatchling's default sweeps in every file it can see,
including ones git ignores through a nested `.gitignore`, which is how 8.5 MB of `.beads`
tracker state ended up in a release. Patterns need a leading `/` to anchor them to the
project root, or they match at any depth. The plugin surface (`skills/`, `hooks/`, the two
`plugin.json` manifests) deliberately stays out: plugin users install from the git
marketplace, and the PyPI package is only the `sniff` CLI.
