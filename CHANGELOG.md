# Changelog

All notable changes to this project are documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

- `sniff diff` now flags only new or worsened violations, so adding clean code no longer fails the gate.
- `sniff baseline` and `sniff diff` now fail with an error when any detector cannot run.
- Baselines written by older versions must be refreshed with `sniff baseline write`.
- A scan now exits non-zero when a detector fails to run.
- Installing sniff now installs ast-grep automatically.
- sniff prime now checks PyPI for updates at most once every 4 hours.

## [0.15.0] - 2026-08-03

- New detector `duplicate-code`: the largest blocks of copy-pasted code, ranked by size.
- New detector `self-admitted-debt`: files ranked by the TODO/FIXME/HACK/XXX markers in their comments.
- Six new pattern rules: reaching into another object's privates (Python and TypeScript), mutable class attributes, `global` rebinding, instantiated default arguments, and unexplained numeric literals.

## [0.14.0] - 2026-08-03

- `sniff prime` now warns when a newer release is on PyPI. Set `SNIFF_NO_VERSION_CHECK=1` to skip the check.

## [0.13.0] - 2026-08-03

- Two new Python rules: `py-broad-except` and `py-import-outside-toplevel`.
- Pattern rules now skip test files too, like every other detector.
  `sniff --only sniff-patterns . --include-tests` reports them.
- `sniff --help` no longer lists `test-rules`, which only ever worked from a source checkout.
- Fix: `sniff prime` named the wrong detectors as the ones that still work without `ast-grep`.
- Fix: `--top` on `sniff-patterns` silently truncated the location lists; it is now ignored as documented.

## [0.12.1] - 2026-08-02

- Fix: detectors reported no findings when the scanned repo sat under a directory
  named `build`, `dist`, `out`, `target`, `vendor`, `venv`, or `.claude`.
- Fix: scans never finished on a repo with an uninitialized submodule.
- Fix: Python repos were scanned only partly; `large-classes` reported zero and detectors
  that cannot read Python still printed a no-findings line.
- Pattern rules now run on `.tsx` and `.js`, not only `.ts`.

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
