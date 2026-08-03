# Contributing to sniff

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
  detectors/           one module per built-in metric detector (10)
  patterns/            the rule catalog: rules/, rule-tests/, sgconfig.yml
  patterns_detector.py the 11th detector, at the package root rather than in detectors/
skills/              one thin SKILL.md wrapper per detector, plus sniff/ and sniff-create/
hooks/hooks.json     lifecycle hooks, and the single source for BOTH hosts, since Claude
                     Code and Codex each auto-discover this exact path
.claude-plugin/      plugin.json + marketplace.json (Claude Code)
.codex-plugin/       plugin.json (Codex)
action.yml           composite GitHub Action behind the README's CI mode
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

Or hand-write a rule (e.g., `rules/no-console-log.yml`) and a fixture file (e.g., `rule-tests/no-console-log.yml`). Each fixture file must contain at least one invalid snippet (should be flagged) and one valid snippet (stays clean). See `no-empty-catch.yml` and `no-explicit-any.yml` for examples.

Test locally before committing:

```bash
uv run sniff test-rules
```

All fixtures must pass before you open a PR.

`sniff test-rules` is a maintainer command: it reads the catalog sources under
`src/sniff/patterns/`, which the published wheel does not ship, so it only works from a
checkout. That is why it is absent from `sniff --help` and from the README's command
table, and why it always runs through `uv run` here.

## Promoting a local rule from a project that uses sniff

This section is for a *different* repo: one where you installed the sniff CLI
and wrote a project-specific rule that turned out generally useful. Run these
steps from that project, not from this sniff repo, to send the rule upstream
into this catalog.

1. In that project (not here), create a local rule under `.sniff/rules/<rule-id>.yml` with matching fixtures at `.sniff/rule-tests/<rule-id>.yml`.

2. Prove the rule works by scanning that project with it:
   ```bash
   sniff --only sniff-patterns .
   ```

   `sniff test-rules` is NOT available here: it runs the catalog's fixture suite and needs
   a sniff repo checkout. Your fixtures are tested for you in the next step, once the rule
   has been copied into the catalog.

3. Contribute:
   ```bash
   sniff contribute <rule-id>
   ```

Contribution backend depends on config:
   - If `SNIFF_REPO` env var or `~/.sniff/config.toml` (with `repo = "..."`) points to a local sniff checkout, the rule is copied there, fixtures tested, and staged on a branch. Review and open a PR yourself.
   - Otherwise, `sniff contribute` forks the repo via `gh` CLI and opens a PR automatically.

Guards: the rule must exist locally, have a fixture file, and not collide with a rule id already in the catalog.

## Regenerating the docs

Two README tables are generated from the code, not written by hand: the language
support matrix (which languages each detector reads) and the pattern rule catalog.
Run this after adding a rule, changing a rule's `metadata: languages:`, or changing
a detector's `LANGUAGES`:

```bash
uv run python scripts/update_docs.py
```

It rewrites only the text between the `<!-- language-matrix:start -->` and
`<!-- pattern-catalog:start -->` markers. Add `--check` to see whether the README is
stale without changing it.

Tests enforce this, so a forgotten run shows up as a failing test rather than a README
that claims support sniff does not have.

## Evals

`evals/` measures whether an agent picks the right `sniff` command from a prompt. Not
part of CI and not needed for most PRs: run it when you change a surface an agent reads,
meaning a SKILL.md, `sniff prime`, `sniff --help`, or the README's command table.

```bash
python evals/runner.py --dry-run    # prints the prompts, no API calls
python evals/runner.py              # simulated agent, one API call per case
python evals/scorer.py --results evals/results/<file>.jsonl
```

`evals/cases.jsonl` holds the prompts, `runner.py` simulates an agent in a single API
call, and `scorer.py` grades routing and hallucinated flags. A simulated pass is not
proof: `evals/smoke/README.md` describes the hand-run real-session complement, which
sees context the simulation does not and so catches regressions it misses.

## Conventions

Name rule ids in kebab-case. Prefix with `no-` to forbid a pattern (e.g., `no-console-log`, `no-explicit-any`), or `prefer-` to recommend an alternative (e.g., `prefer-const-over-let`).

Severity guidance:
   - `error`: nearly always a real bug (e.g., empty catch block, explicit any)
   - `warning`: maintainability smell, likely a real issue (default; e.g., cognitive complexity)
   - `info` or `hint`: stylistic preference, not actionable for all projects (e.g., prefer trailing commas)

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

Built-in detectors are registry modules: add `src/sniff/detectors/<name>.py` (exposing
`NAME`, `TITLE`, `DEFAULT_ARGS`, `main(argv)`) and list it in `BUILTIN` in
`src/sniff/detectors/__init__.py`. They run in-process, no manifest involved.

External, project-specific detectors need no code in this repo: drop a `detector.yml`
manifest plus its script under `<scan-dir>/.sniff/detectors/<name>/` and sniff discovers
it automatically when scanning that directory.

Consumer repos can also tune a run without touching this repo, via a `.sniff.toml`
config file (see the Configuration section of the README).

## PR checklist

Before opening a PR:

- [ ] `uv run sniff test-rules` passes
- [ ] `uv run python scripts/update_docs.py` run, if a rule or a detector's languages changed
- [ ] `uv run python -m pytest tests -q` passes
- [ ] Add a note as a new entry at the top of `CHANGELOG.md`
- [ ] If this is a version bump, run `python scripts/bump_version.py <version>` (not for feature PRs).
      Never hand-edit a version: the script is the only thing that keeps `pyproject.toml`,
      both `plugin.json` files, and the `marketplace.json` entries in lockstep, and
      `tests/test_version_consistency.py` fails the build if they drift apart.
- [ ] CI passes (GitHub Actions will run the checks)

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
