# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

- Fix: lifecycle hooks never ran under Codex, and the Stop hook fired twice under
  Claude Code. Both hosts now load one file, `hooks/hooks.json`, and hook commands
  no longer depend on the working directory they were launched from.
- Fix: 8.5 MB of local `.beads` tracker state was published to PyPI. The sdist is
  now the `sniff` CLI and nothing else: 3956 KB to 49 KB.
- Added a MIT `LICENSE`. The project previously had none, which left it
  all-rights-reserved despite shipping on PyPI and as an installable plugin.
- Codex plugin manifest gained the metadata install surfaces expect: license,
  website, brand colour, logo, and prose starter prompts.
- Fix: `.claude-plugin/marketplace.json` was stuck at `0.1.1` while the plugin was
  at `0.10.0`, so Claude Code warned on every marketplace validation. Versions are
  now bumped together, and a test fails the build if they drift apart again.
- `sniff doctor` and `sniff prime` no longer report version drift; that check moved
  into the test suite.

## [0.10.0] - 2026-07-30

- **Breaking:** the plugin-scripts layout is replaced by an installable package,
  `sniff-smells`. Install with `uv tool install sniff-smells`. The `sniff` command
  and its flags are unchanged.
- Custom detectors: add a `detector.yml` under `.sniff/detectors/<name>/` in the
  scanned project. Local pattern rules in `.sniff/rules/` run alongside the catalog.
- Project config via `.sniff.toml`: `[rules]` to disable a rule or change severity,
  `[detectors]` to skip detectors or override thresholds, `[ignore]` for path globs.
- `sniff contribute <rule-id>` upstreams a local rule, into an existing checkout or
  via a `gh` fork and pull request.
- With `--only <one detector>`, trailing flags pass through to that detector and
  take precedence over `.sniff.toml`.

## [0.9.5]

- New subcommands: `sniff version`, `sniff doctor` (checks Python, ast-grep, and
  detector manifests), and `sniff prime` (agent context, no scan).
- `sniff baseline write` / `sniff diff` save and compare per-detector finding counts.
- `--json` output for `--list` and scans.
- Every detector (complexity, nesting, parameters, method/class/file size, inline
  templates, duplicate strings, pattern rules) runs standalone or aggregated.
- Native Codex plugin alongside the Claude Code plugin.
