---
name: sniff
description: >-
  Run every code-smell detector over a repo in one pass and return one compact
  section per detector. Use when the user wants the FULL smell scan, "find all
  code smells", "lint everything", "run all the checks", "sonar-style scan", or
  does not name a specific metric. Aggregates sniff-patterns (pattern rule catalog) plus
  every node-metric and file-metric detector (complexity, nesting, parameters,
  method/class/file size, inline-template size). For pattern rules only, invoke
  sniff:sniff-patterns directly. For a single metric, invoke that detector's own skill instead.
---

# sniff

Umbrella entry point that runs **all** detectors in one pass: `sniff-patterns`
(pattern rule catalog) plus every node-metric and file-metric detector (complexity,
nesting, parameters, method/class/file size, inline-template size). To run pattern
rules only, invoke `sniff:sniff-patterns` directly.

## Setup

Ensure sniff is installed. Try `sniff version`. If it fails, install it:
`uv tool install sniff-smells` (fallback: `pip install --user sniff-smells`),
and if `ast-grep` is missing: `uv tool install ast-grep-cli`.

## Quick start

Default: run `sniff [DIR]`.
Need pattern rules only: run `sniff --only sniff-patterns [DIR]`.
Need one metric: run `sniff --only <detector> [DIR]`.

## Intent routing

| User intent | Run |
| --- | --- |
| Full scan / find all code smells / run all checks | `sniff [DIR]` |
| See available detectors | `sniff --list` |
| Pattern rules only | `sniff --only sniff-patterns [DIR]` |
| List pattern rules | `sniff --list-patterns` |
| Single metric | `sniff --only <detector> [DIR]` |

Each detector skill ships a `detector.yml` manifest; `sniff` discovers every manifest under the skills root and
runs each detector's script over the scan path, printing one section per detector.

Adding a detector is zero-cost: drop a `detector.yml` next to its script and it joins
`sniff` automatically, no edit to the runner. This mirrors the sniff-patterns rule
catalog, where adding a rule file costs nothing.

## Relaying the result

**Reproduce the entire output (the `sniff:` header line + every `## <detector>`
section, each with its table) in your reply message, verbatim.** It IS the answer.
The sections only render as real tables when they live in your reply, NOT when left
inside the tool-output block. Do NOT summarize to prose or drop sections. You may add
ONE takeaway line at the end (e.g. the worst detector), but the full output comes
first and in full.

A detector reporting 0 findings is a valid, complete result: that smell is absent.
Relay its section as-is.

## Command

`sniff` is installed as a CLI on PATH. Use it directly — do NOT use `python "<skill_dir>/scripts/run.py"`.

```bash
sniff [DIR]                          # run every detector (default)
sniff --all [DIR]                    # same as above (explicit alias)
sniff --only <detector>[,...]        # targeted scan
sniff --skip <detector>[,...]        # exclude detectors
sniff --list                         # list available detectors and exit
sniff --list-patterns                # list pattern rules and exit
sniff --json [DIR]                   # scan or --list output as JSON
sniff version                        # print installed version
sniff doctor                         # check prerequisites, exit 0/1
sniff prime                          # agent-optimized context, never scans
sniff baseline write [DIR]           # save per-detector counts to .sniff/baseline.json
sniff diff [DIR]                     # compare current scan to the saved baseline
```

`DIR` defaults to the current directory.

## Detector names

Exact names (case-sensitive) for use with `--only` / `--skip`:

| Name | What it finds |
| --- | --- |
| `largest-files` | Files with the most lines |
| `largest-methods` | Methods/functions with the most lines |
| `large-classes` | Classes with the most lines |
| `cyclomatic-complexity` | High branching complexity |
| `cognitive-complexity` | Hard-to-read control flow |
| `deepest-nesting` | Deepest block nesting |
| `most-parameters` | Functions with most parameters |
| `most-imports` | Files with most imports |
| `no-duplicate-string` | Duplicate string literals |
| `sniff-patterns` | Pattern rule catalog (ast-grep rules) |
| `large-inline-templates` | Oversized Angular inline templates |

## Token cost

Each detector returns only its own compact table (ranked top-N or a location list),
never source, so the aggregate stays small for a normal repo. The runner just
concatenates sections. If a future repo makes default full-scan output genuinely large, narrow
it with `--only` / `--skip`; a smarter cap can come then, not before.

## Adding a detector

Author the detector as its own skill (use `sniff-create`), then drop a `detector.yml`
in that skill's directory:

```yaml
name: my-detector
title: One-line section heading
script: scripts/my_detector.py
args:                 # optional, space-separated extra args appended after DIR
```

`sniff --list` will then show it and `sniff` (no flags) will run it.

## Caveats

- The runner shells out to each detector's existing script; it never reimplements a
  detector, so the standalone skill and the aggregate run always agree.
- A failing detector yields an error section instead of aborting the run, so one
  broken detector cannot hide the others.
- Prerequisites: `ast-grep` on PATH (pattern + node-metric detectors), Python 3.
