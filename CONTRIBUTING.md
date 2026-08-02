# Contributing to sniff

## Dev setup

1. Clone the repo and install prerequisites (one-time):
   ```bash
   git clone https://github.com/ambervdberg/sniff.git
   cd sniff
   uv pip install -e ".[dev]"
   ```

2. Install [ast-grep](https://ast-grep.github.io) (required for all pattern-rule work):
   ```bash
   # macOS/Linux via Homebrew
   brew install ast-grep
   # Or download a pre-built binary from https://ast-grep.github.io
   ```

3. Verify setup:
   ```bash
   sniff doctor
   ```

4. Run the test suite:
   ```bash
   python -m pytest tests -q
   ```

## Adding a pattern rule

Rules live in `src/sniff/patterns/rules/` as YAML files, with fixtures alongside in
`src/sniff/patterns/rule-tests/`.

The quickest way to add one is the `sniff-create` Claude skill: ask Claude to "create a
sniff rule for <the smell>". It drafts the rule with you, validates it against the current
repo, then writes the rule and its fixture file.

Or hand-write a rule (e.g., `rules/no-console-log.yml`) and a fixture file (e.g., `rule-tests/no-console-log.yml`). Each fixture file must contain at least one invalid snippet (should be flagged) and one valid snippet (stays clean). See `no-empty-catch.yml` and `no-explicit-any.yml` for examples.

Test locally before committing:

```bash
sniff test-rules
```

All fixtures must pass before you open a PR.

## Promoting a local rule from a project that uses sniff

This section is for a *different* repo: one where you installed the sniff plugin
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
| **cross-file** | needs a whole-project graph | inheritance depth |

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

- [ ] `sniff test-rules` passes
- [ ] `python -m pytest tests -q` passes
- [ ] Add a note as a new entry at the top of `CHANGELOG.md`
- [ ] If this is a version bump, run `python scripts/bump_version.py <version>` (not for feature PRs).
      Never hand-edit a version: the script is the only thing that keeps `pyproject.toml`,
      both `plugin.json` files, and the `marketplace.json` entries in lockstep, and
      `tests/test_version_consistency.py` fails the build if they drift apart.
- [ ] CI passes (GitHub Actions will run the checks)
