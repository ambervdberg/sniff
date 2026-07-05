# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

## [0.9.5]

- `sniff version` prints the installed/checkout version.
- `sniff doctor` checks Python, ast-grep, detector manifests, and version consistency.
- `sniff prime` prints agent-optimized context (version, detectors, prerequisites, usage hints) without running a scan.
- `sniff baseline write` / `sniff diff` save and compare per-detector finding counts.
- `--json` output for `--list` and scans, for machine-parseable results.
- Every code-smell detector (complexity, nesting, parameters, method/class/file size, inline-template size, duplicate strings, sniff-patterns rule catalog) runnable standalone or aggregated via `sniff`.
- Native Codex plugin alongside the Claude Code plugin.
