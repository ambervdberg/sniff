# Contributing to sniff

## Dev setup

1. Clone the repo and install prerequisites (one-time):
   ```bash
   git clone https://github.com/ambervdberg/sniff.git
   cd sniff
   ```

2. Install [ast-grep](https://ast-grep.github.io) (required for all pattern-rule work):
   ```bash
   # macOS/Linux via Homebrew
   brew install ast-grep
   # Or download a pre-built binary from https://ast-grep.github.io
   ```

3. Verify setup:
   ```bash
   python skills/_ast-harness/test_harness.py
   python skills/sniff/scripts/run.py doctor
   ```

## Adding a pattern rule

Rules live in `skills/sniff-patterns/rules/` as YAML files. Use `sniff-create` to scaffold:

```bash
sniff-create
# follow the prompts, pick "pattern rule", and it generates rule + fixture template
```

Or hand-write a rule (e.g., `rules/no-console-log.yml`) and a fixture file (e.g., `rule-tests/no-console-log.yml`). Each fixture file must contain at least one invalid snippet (should be flagged) and one valid snippet (stays clean). See `no-empty-catch.yml` and `no-explicit-any.yml` for examples.

Test locally before committing:

```bash
python skills/sniff/scripts/run.py test-rules
# or if installed via `uv tool install .`:
sniff test-rules
```

All fixtures must pass before you open a PR.

## Promoting a local rule from a project that uses sniff

This section is for a *different* repo: one where you installed the sniff plugin
and wrote a project-specific rule that turned out generally useful. Run these
steps from that project, not from this sniff repo, to send the rule upstream
into this catalog.

1. In that project (not here), create a local rule under `.sniff/rules/<rule-id>.yml` with matching fixtures at `.sniff/rule-tests/<rule-id>.yml`.

2. Prove the rule works:
   ```bash
   sniff test-rules
   ```

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

A new check needs one of four engine types. Use the engine that fits your smell:

| Engine | For | Example |
| --- | --- | --- |
| **pattern rule** | a specific code shape, flagged with a severity | any type, empty imports: [] |
| **node metric** | score each method/class from its AST | nesting depth, cyclomatic / cognitive complexity, inline-template line count |
| **file metric** | a number per file, no AST | largest files (split candidates) |
| **cross-file** | needs a whole-project graph | inheritance depth |

Pattern rules and node metrics run on [ast-grep](https://ast-grep.github.io). File metrics are plain Python. New detectors need a `detector.yml` manifest in `skills/` (see `sniff-patterns/` for an example).

## PR checklist

Before opening a PR:

- [ ] `python skills/sniff/scripts/run.py test-rules` passes (or `sniff test-rules` if installed)
- [ ] Add a note to `CHANGELOG.md` under `## [Unreleased]`
- [ ] If this is a version bump, run `python scripts/bump_version.py <version>` (not for feature PRs)
- [ ] CI passes (GitHub Actions will run the checks)
