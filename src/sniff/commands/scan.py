"""Detector selection and the default `sniff [DIR]` scan.

Turns `main()`'s parsed CLI flags plus `.sniff.toml` into the final detector
list for a run: `select_with_config` narrows the discovered detectors by
--only/--skip and config, `_readable_here` drops anything that can't read
this repo's languages, and `apply_config_to_detector` folds per-detector
config overrides into each survivor's args. `_run_selected` then executes
that list and prints the result, in JSON or markdown.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from dataclasses import replace

from sniff import config, discovery
from sniff.execution import _detector_failed, _render_detector_result, run_detector_json


def _discover_with_warnings(scan_path: "str | None" = None) -> list[discovery.Detector]:
    """discovery.discover(scan_path), printing a warning per manifest error to stderr.

    Shared by the scan path, baseline write, and diff — each cares about the
    detector list, none of them need the errors beyond surfacing them. Passing
    `scan_path` also picks up external detectors from that directory's
    `.sniff/detectors/`; `--list`/`--list-patterns`, `doctor`, and `prime` omit
    it since they aren't scanning a specific directory's project detectors."""
    detectors, errors = discovery.discover(scan_path)
    for err in errors:
        print(f"warning: {err}", file=sys.stderr)
    return detectors


def select(detectors: list[discovery.Detector], only: set[str], skip: set[str]
           ) -> tuple[list[discovery.Detector], list[str]]:
    """Apply --only / --skip to the discovered detectors.

    Returns (selected, unknown) where `unknown` names any --only/--skip entry that
    matched no detector, so a typo surfaces instead of silently doing nothing."""
    known = {d.name for d in detectors}
    unknown = sorted((only | skip) - known)

    selected = [
        d for d in detectors
        if (not only or d.name in only) and d.name not in skip
    ]
    return selected, unknown


def select_with_config(
    detectors: list[discovery.Detector], only: set[str], skip: set[str], cfg: config.Config
) -> tuple[list[discovery.Detector], list[str]]:
    """select() with `.sniff.toml`'s `[detectors] skip = "..."` merged into --skip.

    A config-listed skip behaves exactly like a --skip flag: it removes the
    detector from the run, and it still participates in --skip's unknown-name
    warning (any typo in .sniff.toml's skip list surfaces the same as a CLI typo)."""
    return select(detectors, only, skip | cfg.skip_detectors)


def _readable_here(
    selected: list[discovery.Detector], present: "set[str]", only: set[str]
) -> list[discovery.Detector]:
    """Keep only the detectors that can read the languages this repo contains.

    A detector with no rules for any language present has nothing to report, and
    a "none found" line from it reads like a clean bill of health rather than the
    blind spot it is. Two exceptions keep the rule from hiding things: a detector
    named in `--only` was asked for by name, so it runs and explains itself, and a
    repo with no supported source files at all keeps everything, so the detectors
    produce their own "nothing to scan" message."""
    if not present:
        return selected

    return [d for d in selected if d.name in only or d.covers(present)]


def _override_args(args: list[str], overrides: dict[str, str]) -> list[str]:
    """Return `args` with each `--key value` pair in `overrides` applied.

    An existing `--key ...` pair in `args` is replaced in place; a key the
    detector's manifest never set is appended. Used to fold .sniff.toml's
    `detector.arg = value` thresholds into a detector's own CLI args before it runs,
    e.g. {"top": "15"} turns `--top 20` into `--top 15`, or adds `--top 15` if the
    manifest carried no --top at all."""
    result = list(args)
    for key, value in overrides.items():
        flag = f"--{key}"
        replaced = False
        i = 0
        while i < len(result):
            if result[i] == flag:
                if i + 1 < len(result):
                    result[i + 1] = value
                else:
                    result.append(value)
                replaced = True
                i += 2
                continue
            i += 1
        if not replaced:
            result.extend([flag, value])
    return result


def apply_config_to_detector(detector: discovery.Detector, cfg: config.Config) -> discovery.Detector:
    """Fold .sniff.toml overrides that target one detector into its args.

    Config can change what a selected detector's own run sees:
    `[detectors] <name>.<arg> = value` overrides that detector's CLI args;
    `[rules] <id> = false` (sniff-patterns only) becomes `--disable <ids>` so the
    pattern catalog skips those rules; `[rules] <id> = "<severity>"`
    (sniff-patterns only) becomes `--severity-override <id>=<severity>`; and
    `[ignore] globs = "..."` becomes repeated `--extra-ignore <glob>` args for a
    built-in (module) detector, since `module.main(argv)` parses that flag itself
    (an external, manifest-based detector still gets it via SNIFF_EXTRA_IGNORE,
    exported once in main() around the run, not here). Returns `detector`
    unchanged (same object) when none applies, so callers can skip work for the
    common no-config case."""
    args = detector.args
    overrides = cfg.thresholds.get(detector.name)
    if overrides:
        args = _override_args(args, overrides)
    if detector.name == "sniff-patterns" and cfg.disabled_rules:
        args = [*args, "--disable", ",".join(sorted(cfg.disabled_rules))]
    if detector.name == "sniff-patterns" and cfg.severity_overrides:
        for rule_id, level in sorted(cfg.severity_overrides.items()):
            args = [*args, "--severity-override", f"{rule_id}={level}"]
    if detector.module is not None and cfg.extra_ignores:
        for glob_pat in cfg.extra_ignores:
            args = [*args, "--extra-ignore", glob_pat]
    if args is detector.args:
        return detector
    return replace(detector, args=args)


def _reject_extras(parser: argparse.ArgumentParser, argv: list[str], extras: list[str]) -> None:
    """Exit 2 because `extras` cannot be forwarded to a detector.

    Unknown trailing arguments are only meaningful when the run resolves to
    exactly one detector, since sniff cannot know which of several detectors a
    stray `--top 5` was meant for. Every other case re-runs the strict parse so
    argparse emits its own "unrecognized arguments" error (and exit code 2)
    exactly as it did before passthrough existed, with our more specific reason
    printed just above it."""
    joined = " ".join(extras)
    print(
        f"error: extra detector flags require --only with exactly one detector: {joined}",
        file=sys.stderr,
    )
    parser.parse_args(argv)  # raises SystemExit(2) with argparse's own message
    raise SystemExit(2)      # unreachable safety net if argparse ever accepts argv


def _forward_extras(detectors: list[discovery.Detector], extras: list[str]) -> list[discovery.Detector]:
    """Append `extras` to the single selected detector's args, so CLI beats config.

    They land after the manifest- and `.sniff.toml`-derived args, and argparse's
    last-wins behaviour makes the CLI value the effective one. Applies to built-in
    (module) and external (subprocess) detectors alike: both invoke the detector
    with `detector.args`."""
    if not extras or len(detectors) != 1:
        return detectors
    detector = detectors[0]
    return [replace(detector, args=[*detector.args, *extras])]


@contextlib.contextmanager
def _exported_extra_ignore(globs: "list[str] | None"):
    """Export SNIFF_EXTRA_IGNORE for the duration of the block, then restore it.

    main() may be called in-process (tests, embedding) more than once, so the
    export must not outlive the run that needed it; without the restore a later
    call would silently inherit the previous run's ignore globs. `globs` of None
    means "export nothing", so the caller never needs a second code path."""
    if globs is None:
        yield
        return

    previous = os.environ.get("SNIFF_EXTRA_IGNORE")
    os.environ["SNIFF_EXTRA_IGNORE"] = ",".join(globs)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SNIFF_EXTRA_IGNORE", None)
        else:
            os.environ["SNIFF_EXTRA_IGNORE"] = previous


def _run_selected(selected: list[discovery.Detector], args: argparse.Namespace) -> int:
    """Run every selected detector over args.path and print the result.

    JSON mode emits one machine-readable object; markdown mode prints a header
    line plus one `## <detector>` section each. Both modes render the same
    `run_detector_json` results, so a detector that fails to run (crash,
    launch failure, non-zero exit) flips the process exit code to 1 in either
    mode. Findings alone (a detector that ran cleanly and reported smells)
    are not a failure and leave the exit code at 0."""
    results = [run_detector_json(d, args.path) for d in selected]

    if args.json:
        print(json.dumps({"path": args.path, "detectors": results}, indent=2))
    else:
        names = ", ".join(d.name for d in selected)
        print(f"sniff: {len(selected)} detectors over {args.path!r}: {names}\n")

        for detector, result in zip(selected, results):
            print(f"## {detector.name}\n")
            print(_render_detector_result(result))
            print()

    return 1 if any(_detector_failed(r) for r in results) else 0
