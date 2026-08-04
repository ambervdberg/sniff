#!/usr/bin/env python3
"""sniff: run every smell detector over a repo in one pass.

The umbrella entry point. Built-in detectors come from the static registry in
`sniff.detectors.BUILTIN` and run in-process; external, consumer-defined
detectors are discovered from `<scan DIR>/.sniff/detectors/*/detector.yml`
manifests and run as subprocesses (see discovery.py). Either way this prints one
markdown section per detector. Default runs all detectors with no flag; narrow
with --only / --skip, or just list what is available with --list.

Each detector returns only its own compact table (ranked top-N or location list),
never source, so the aggregate stays token-cheap: this runner just concatenates
those sections under per-detector headings. It never reimplements a detector; it
calls the detector's own entry point, so the standalone skill and the aggregate
run always agree.

Usage:
    sniff [DIR] [--only a,b] [--skip a,b] [--ignore GLOB ...] [--list]
    sniff version
    sniff doctor
    sniff prime
    sniff baseline write [DIR]
    sniff diff [DIR]
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import urllib.request  # noqa: F401  (re-export: tests patch run_module.urllib.request.urlopen)
from dataclasses import replace

from sniff import config, contribute, discovery, gate, harness, rules_testing
from sniff.commands.doctor import run_doctor, run_prime
from sniff.execution import _detector_failed, _render_detector_result, run_detector_json
from sniff.versioning import _REPO_ROOT, get_version
# Re-exports: not called from this module, but tests patch these via sniff.cli.<name>,
# and versioning.py itself reads _latest_released_version/_version_cache_path back
# through this module so those patches take effect (see versioning.py's docstring).
from sniff.versioning import _latest_released_version, _upgrade_available_caveat, _version_cache_path  # noqa: F401


# Flags seen hallucinated in eval runs (gpt-5.4-nano, gpt-5.4-mini, sonnet-4-6).
# Mapped to the real flag/command so the hint can correct the agent before
# argparse's generic "unrecognized arguments" error fires.
HALLUCINATED_FLAG_HINTS = {
    "--detectors": "use --only <names> to pick detectors (see `sniff --list`)",
    "--rules": "use --list-patterns to see pattern rules, or --only sniff-patterns",
    "--verbose": "no --verbose flag; sniff output is already compact",
    "--complexity": "use --only cyclomatic-complexity or --only cognitive-complexity",
    "--format": "no --format flag; sniff always prints markdown",
}


def warn_hallucinated_flags(argv: list[str]) -> None:
    """Print a hint to stderr for any known-hallucinated flag in argv.

    Runs before argparse.parse_args() so the hint appears ahead of argparse's
    generic error and exit, instead of being replaced by it."""
    for token in argv:
        flag = token.split("=", 1)[0]
        hint = HALLUCINATED_FLAG_HINTS.get(flag)
        if hint:
            print(f"hint: {flag!r} is not a sniff flag. {hint}", file=sys.stderr)


def _split_csv(value: str | None) -> set[str]:
    """Parse a comma-separated --only/--skip value into a set of detector names."""
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


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


def run_baseline(argv: list[str]) -> int:
    """`sniff baseline write [DIR]`: scan DIR, save per-detector fingerprints as JSON.

    Saved to <DIR>/.sniff/baseline.json so a later `sniff diff` can compare
    against it. Returns 0 on success, 1 on a usage, path, or detector error."""
    if not argv or argv[0] != "write":
        print("usage: sniff baseline write [DIR]", file=sys.stderr)
        return 1

    path = argv[1] if len(argv) > 1 else "."
    if not os.path.isdir(path):
        print(f"error: {path!r} is not a directory. Check the path and try again.", file=sys.stderr)
        return 1

    try:
        fingerprints = gate.scan_fingerprints(_discover_with_warnings(path), path)
    except gate.DetectorFailure as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    payload = {"version": 2, "path": path, "fingerprints": fingerprints}

    baseline_dir = os.path.join(path, ".sniff")
    os.makedirs(baseline_dir, exist_ok=True)
    baseline_path = os.path.join(baseline_dir, "baseline.json")
    with open(baseline_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print(f"sniff: baseline written to {baseline_path} ({len(fingerprints)} detectors)")
    return 0


def run_diff(argv: list[str]) -> int:
    """`sniff diff [DIR]`: compare a fresh fingerprint scan of DIR against its baseline.

    A regression is a fingerprint that is new (absent from the baseline) or whose
    value increased; fixed or removed fingerprints count as improvements instead.
    Returns 0 if no detector regressed (same or better), 1 if any detector has a
    new or worsened fingerprint, so the exit code alone answers "did this get
    worse?" without adding clean, unrelated growth to the count.

    --comment switches the table to markdown with a bold verdict line, suitable
    to paste as a PR comment."""
    comment = "--comment" in argv
    argv = [a for a in argv if a != "--comment"]
    path = argv[0] if argv else "."
    if not os.path.isdir(path):
        print(f"error: {path!r} is not a directory. Check the path and try again.", file=sys.stderr)
        return 1

    baseline_path = os.path.join(path, ".sniff", "baseline.json")
    if not os.path.isfile(baseline_path):
        print(f"error: no baseline at {baseline_path!r}. Run `sniff baseline write {path}` first.", file=sys.stderr)
        return 1

    with open(baseline_path, "r", encoding="utf-8") as fh:
        baseline_data = json.load(fh)

    if baseline_data.get("version") != 2:
        print(
            "error: baseline is in an old format. "
            f"Run `sniff baseline write {path}` to refresh it.",
            file=sys.stderr,
        )
        return 1

    try:
        current = gate.scan_fingerprints(_discover_with_warnings(path), path)
    except gate.DetectorFailure as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    baseline_fps: dict[str, dict[str, int]] = baseline_data.get("fingerprints", {})

    # A fingerprint is a regression when it is new to a detector's set or its
    # value climbed; the inverse (present in the baseline, gone or lower now)
    # is an improvement. Comparing on value, not presence alone, is what lets a
    # repeated duplicate-code block register even though its fingerprint (the
    # pair of files it spans) does not change between the two scans.
    names = sorted(set(baseline_fps) | set(current))
    regressions: dict[str, list[str]] = {}
    improvements = 0
    for name in names:
        before, after = baseline_fps.get(name, {}), current.get(name, {})
        new = [fp for fp, v in after.items() if v > before.get(fp, 0)]
        improvements += sum(1 for fp in before if before[fp] > after.get(fp, 0))
        if new:
            regressions[name] = sorted(new)

    if comment:
        return _print_diff_comment(names, regressions)
    return _print_diff_text(regressions, improvements)


def _print_diff_comment(names: list[str], regressions: dict[str, list[str]]) -> int:
    """Markdown table for `sniff diff --comment`, one row per detector.

    NEW VIOLATIONS lists up to 5 fingerprints per detector, then a `+N more`
    tally, so a detector with dozens of new violations doesn't blow up a PR
    comment."""
    lines = ["| DETECTOR | REGRESSIONS | NEW VIOLATIONS |", "| --- | --- | --- |"]
    for name in names:
        new = regressions.get(name, [])
        shown = ", ".join(new[:5])
        if len(new) > 5:
            shown += f", +{len(new) - 5} more"
        lines.append(f"| {name} | {len(new)} | {shown} |")
    print("\n".join(lines))
    print()
    print("**worse**" if regressions else "**same or better**")
    return 1 if regressions else 0


def _print_diff_text(regressions: dict[str, list[str]], improvements: int) -> int:
    """Plain-text `sniff diff` output: regression lines when any exist, the
    exact `same or better` phrase (CI greps for it) when none do."""
    if regressions:
        lines = [f"{'DETECTOR':<24} NEW VIOLATIONS"]
        for name in sorted(regressions):
            lines.append(f"{name:<24} {', '.join(regressions[name])}")
        print("\n".join(lines))
        print()
        total_new = sum(len(fps) for fps in regressions.values())
        print(f"worse: {total_new} new violation(s), {improvements} improvement(s)")
        return 1

    print(f"same or better ({improvements} improvement(s))" if improvements else "same or better")
    return 0


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


def main(argv: "list[str] | None" = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # version/doctor are subcommands, not detector flags, so they're handled before
    # the DIR-positional parser below would otherwise treat "doctor" as a path.
    if argv[:1] == ["version"]:
        print(f"sniff {get_version()}")
        return 0
    if argv[:1] == ["doctor"]:
        return run_doctor()
    if argv[:1] == ["prime"]:
        run_prime()
        return 0
    if argv[:1] == ["baseline"]:
        return run_baseline(argv[1:])
    if argv[:1] == ["diff"]:
        return run_diff(argv[1:])
    if argv[:1] == ["test-rules"]:
        return rules_testing.run_test_rules(_REPO_ROOT)
    if argv[:1] == ["contribute"]:
        import argparse as _ap
        p = _ap.ArgumentParser(prog="sniff contribute")
        p.add_argument("rule_id")
        p.add_argument("--dir", default=".", help="project dir holding .sniff/ (default: .)")
        p.add_argument("--dry-run", action="store_true")
        a = p.parse_args(argv[1:])
        return contribute.run_contribute(a.rule_id, a.dir, a.dry_run)

    parser = argparse.ArgumentParser(
        prog="sniff",
        description="Run every code-smell detector over a repo in one pass.",
        epilog=(
            "Default: `sniff [DIR]` runs all detectors; `--all` is accepted as an explicit alias.\n\n"
            "Examples:\n"
            "  sniff                        # scan current directory, all detectors\n"
            "  sniff <dir>                  # scan any directory\n"
            "  sniff --list                 # show available detectors\n"
            "  sniff --only largest-methods,cyclomatic-complexity\n"
            "  sniff --only largest-methods . --top 5   # extra flags go to that one detector\n"
            "  sniff --skip sniff-patterns  # skip pattern rules\n"
            "  sniff --ignore \"docs/**\"      # exclude paths (repeatable)\n"
            "  sniff version                # print installed version\n"
            "  sniff doctor                 # check prerequisites and exit 0/1\n"
            "  sniff prime                  # agent-optimized context (no scan)\n"
            "  sniff baseline write [DIR]   # save per-detector fingerprints to .sniff/baseline.json\n"
            "  sniff diff [DIR]             # compare current scan to the saved baseline\n"
            "  sniff contribute <rule>      # move a local rule into the plugin repo\n"
            "\n"
            "Pattern rules only:  sniff --only sniff-patterns [DIR]\n"
            "List pattern rules:  sniff --list-patterns\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", nargs="?", default=".", metavar="DIR", help="directory to scan (default: current directory)")
    parser.add_argument("--only", help="comma-separated detector names to run (default: all)")
    parser.add_argument("--skip", help="comma-separated detector names to skip")
    parser.add_argument("--all", action="store_true", help="run all detectors (default behaviour; alias for no flags)")
    parser.add_argument("--list", action="store_true", help="list discovered detectors and exit")
    parser.add_argument("--list-patterns", action="store_true",
                        help="list pattern rules catalog (RULE / SEVERITY / ORIGIN / ALSO RUNS ON / MESSAGE) and exit")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown (works with scan and --list)")
    parser.add_argument("--ignore", action="append", default=[], metavar="GLOB",
                        help="glob to exclude, relative to DIR (repeatable); adds to .sniff.toml [ignore] globs")

    warn_hallucinated_flags(argv)

    # parse_known_args (not parse_args) so unknown trailing flags can be forwarded
    # to a single --only detector; anything else still errors out below.
    # Whether extras are forwardable depends on how many detectors the run actually
    # resolves to, which is only known after selection; the listing modes never run
    # a detector at all, so they can reject extras right away.
    args, extras = parser.parse_known_args(argv)
    if extras and (args.list or args.list_patterns):
        _reject_extras(parser, argv, extras)

    # --list/--list-patterns describe detectors in general, not a scan of `path`,
    # so they omit the scan path (matching doctor/prime, handled earlier above).
    detectors = _discover_with_warnings(None if (args.list or args.list_patterns) else args.path)

    if args.list:
        if args.json:
            print(json.dumps([
                {"name": d.name, "title": d.title, "script": d.script, "args": d.args,
                 "languages": d.languages}
                for d in detectors
            ], indent=2))
        else:
            print(discovery.render_list(detectors))
        return 0

    if args.list_patterns:
        patterns_detector = next((d for d in detectors if d.name == "sniff-patterns"), None)
        if not patterns_detector:
            print("error: sniff-patterns detector not found (run --list to see available detectors)", file=sys.stderr)
            return 1
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = patterns_detector.module.main(["--list-rules", args.path])
        print(buf.getvalue().strip())
        return code if isinstance(code, int) else 0

    if not detectors:
        print("No detectors found (empty built-in registry and no .sniff/detectors/*/detector.yml manifests).")
        return 0

    if not os.path.isdir(args.path):
        print(f"error: {args.path!r} is not a directory. Check the path and try again.", file=sys.stderr)
        return 1

    cfg = config.load(args.path)

    # `--ignore` adds to the scanned repo's `[ignore] globs` instead of replacing
    # them: a one-off exclusion on the command line should not silently discard the
    # exclusions that repo already committed. Folding it into cfg here means every
    # downstream consumer (per-detector --extra-ignore args and the
    # SNIFF_EXTRA_IGNORE export for external detectors) picks it up for free.
    cfg.extra_ignores = [*cfg.extra_ignores, *args.ignore]

    only = _split_csv(args.only)
    selected, unknown = select_with_config(detectors, only, _split_csv(args.skip), cfg)
    for name in unknown:
        import difflib
        known = [d.name for d in detectors]
        close = difflib.get_close_matches(name, known, n=3, cutoff=0.4)
        hint = f" Did you mean: {', '.join(close)}?" if close else f" Run `sniff --list` to see all detectors."
        print(f"warning: unknown detector {name!r}.{hint}", file=sys.stderr)

    # Checked against the resolved selection, not the raw --only names, so a typo'd
    # or fully skipped detector name cannot silently swallow the extras.
    if extras and len(selected) != 1:
        _reject_extras(parser, argv, extras)

    if not selected:
        if args.json:
            print(json.dumps({"path": args.path, "detectors": []}, indent=2))
        else:
            print("No detectors selected after --only/--skip.")
        return 0

    present = harness.detect_languages(args.path, cfg.extra_ignores)
    selected = _readable_here(selected, present, only)

    if not selected:
        found = ", ".join(sorted(present)) or "no supported source files"
        message = (f"No detector covers {found}. "
                   f"Run `sniff --list` to see what each detector reads.")
        if args.json:
            print(json.dumps({"path": args.path, "detectors": []}, indent=2))
        else:
            print(message)
        return 0

    selected = [apply_config_to_detector(d, cfg) for d in selected]
    selected = _forward_extras(selected, extras)

    # Built-ins get the extra-ignore globs as --extra-ignore args (folded in by
    # apply_config_to_detector above); the env var is only needed for external,
    # manifest-based detectors, which inherit it through subprocess.run.
    needs_env = bool(cfg.extra_ignores) and any(d.module is None for d in selected)
    with _exported_extra_ignore(cfg.extra_ignores if needs_env else None):
        return _run_selected(selected, args)


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


if __name__ == "__main__":
    sys.exit(main())
