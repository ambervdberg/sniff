# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

- **Breaking:** the old plugin-scripts layout (skills importing `_ast-harness`
  via a relative path hack) is replaced by an installable package, `sniff-smells`
  (`src/sniff/`). Install with `uv tool install sniff-smells`. The CLI surface is
  unchanged: same `sniff` command, same subcommands and flags.
- External, project-specific detectors: drop a `detector.yml` manifest under
  `.sniff/detectors/<name>/` in the scanned project to add a custom check.

## [0.9.5]

- `sniff version` prints the installed/checkout version.
- `sniff doctor` checks Python, ast-grep, detector manifests, and version consistency.
- `sniff prime` prints agent-optimized context (version, detectors, prerequisites, usage hints) without running a scan.
- `sniff baseline write` / `sniff diff` save and compare per-detector finding counts.
- `--json` output for `--list` and scans, for machine-parseable results.
- Every code-smell detector (complexity, nesting, parameters, method/class/file size, inline-template size, duplicate strings, sniff-patterns rule catalog) runnable standalone or aggregated via `sniff`.
- Native Codex plugin alongside the Claude Code plugin.
