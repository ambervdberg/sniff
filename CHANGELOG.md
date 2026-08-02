# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [0.12.0] - 2026-08-02

- Every detector now skips files in `.gitignore`.
- New `sniff --ignore GLOB` flag to exclude paths. Repeatable, adds to `.sniff.toml`.
- `sniff-patterns` lists at most 10 locations per rule. `--top-locs N` to change,
  `0` for all.

## [0.11.0] - 2026-08-02

- Fix: hooks never ran under Codex, and the Stop hook fired twice under Claude Code.
- The SessionStart hook no longer needs the CLI preinstalled; it falls back to `uvx`.
- Fix: the sdist is the `sniff` CLI and nothing else: 3956 KB to 49 KB.
- Added a MIT `LICENSE`.
- Codex plugin manifest gained the metadata install surfaces expect.
- Fix: `.claude-plugin/marketplace.json` no longer drifts from the plugin version.
- `sniff doctor` and `sniff prime` no longer report version drift.

## [0.10.0] - 2026-07-30

- **Breaking:** now an installable package. Install with `uv tool install sniff-smells`;
  the `sniff` command and its flags are unchanged.
- Custom detectors via `.sniff/detectors/<name>/detector.yml`, local rules via
  `.sniff/rules/`.
- Project config via `.sniff.toml`: `[rules]`, `[detectors]`, `[ignore]`.
- `sniff contribute <rule-id>` upstreams a local rule.
- With `--only <one detector>`, trailing flags pass through to it.

## [0.9.5]

- New subcommands: `sniff version`, `sniff doctor`, `sniff prime`.
- `sniff baseline write` / `sniff diff` save and compare per-detector finding counts.
- `--json` output for `--list` and scans.
- Every detector runs standalone or aggregated.
- Native Codex plugin alongside the Claude Code plugin.
