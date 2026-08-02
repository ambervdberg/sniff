# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

- Fix: `.claude-plugin/marketplace.json` declared version `0.1.1` while
  `plugin.json` was at `0.10.0`. plugin.json wins at install time, so the stale
  entry was silently ignored and Claude Code warned on every marketplace validation.
  The marketplace also gained the missing top-level `description`.
- `scripts/bump_version.py` now rewrites the marketplace plugin entries too, and
  `tests/test_version_consistency.py` fails CI if any manifest version disagrees,
  so this drift cannot come back unnoticed.
- `sniff doctor` and `sniff prime` no longer report version drift between
  `pyproject.toml` and `plugin.json`. That now lives in the test suite with the rest of the
  version checks.

## [0.10.0] - 2026-07-30

- **Breaking:** the old plugin-scripts layout (skills importing `_ast-harness`
  via a relative path hack) is replaced by an installable package, `sniff-smells`
  (`src/sniff/`). Install with `uv tool install sniff-smells`. The `sniff` command
  and existing flags are unchanged.
- External, project-specific detectors: drop a `detector.yml` manifest under
  `.sniff/detectors/<name>/` in the scanned project to add a custom check.
- Project config via `.sniff.toml` in the scanned repo: `[rules]` to disable a
  pattern rule or change its severity, `[detectors]` to skip detectors or override
  their thresholds, `[ignore]` for extra path globs.
- Consumer-local pattern rules: drop rule files in `.sniff/rules/` and they run
  alongside the built-in catalog.
- `sniff contribute <rule-id>` upstreams a local rule into the sniff repo, either
  into an existing checkout or via a `gh` fork and pull request.
- Detector flag passthrough: with `--only <one detector>`, unknown trailing flags
  are forwarded to that detector and take precedence over `.sniff.toml`.

## [0.9.5]

- `sniff version` prints the installed/checkout version.
- `sniff doctor` checks Python, ast-grep, detector manifests, and version consistency.
- `sniff prime` prints agent-optimized context (version, detectors, prerequisites, usage hints) without running a scan.
- `sniff baseline write` / `sniff diff` save and compare per-detector finding counts.
- `--json` output for `--list` and scans, for machine-parseable results.
- Every code-smell detector (complexity, nesting, parameters, method/class/file size, inline-template size, duplicate strings, sniff-patterns rule catalog) runnable standalone or aggregated via `sniff`.
- Native Codex plugin alongside the Claude Code plugin.
