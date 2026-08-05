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
from dataclasses import dataclass
import shutil  # noqa: F401  (re-export: tests patch run_module.shutil.which)
import sys

from sniff import config, contribute, discovery, harness, rules_testing
from sniff.commands.baseline_diff import run_baseline, run_diff
from sniff.commands.doctor import run_doctor, run_prime
from sniff.commands.scan import (
    discover_with_warnings,
    exported_extra_ignore,
    forward_extras,
    readable_here,
    reject_extras,
    run_selected,
    apply_config_to_detector,
    select_with_config,
    warn_config,
)
from sniff.versioning import _REPO_ROOT, get_version


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


def main(argv: "list[str] | None" = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # version/doctor/prime/etc. are subcommands, not detector flags, so they're
    # handled before the DIR-positional parser would otherwise treat "doctor" as
    # a path. `_dispatch_subcommand` returns None when argv names none of them,
    # meaning this is an ordinary scan invocation that falls through below.
    subcommand_result = _dispatch_subcommand(argv)
    if subcommand_result is not None:
        return subcommand_result

    parser = _build_parser()
    warn_hallucinated_flags(argv)

    # parse_known_args (not parse_args) so unknown trailing flags can be forwarded
    # to a single --only detector; anything else still errors out below.
    # Whether extras are forwardable depends on how many detectors the run actually
    # resolves to, which is only known after selection; the listing modes never run
    # a detector at all, so they can reject extras right away.
    args, extras = parser.parse_known_args(argv)
    if extras and (args.list or args.list_patterns):
        reject_extras(parser, argv, extras)

    # --list/--list-patterns describe detectors in general, not a scan of `path`,
    # so they omit the scan path (matching doctor/prime, handled earlier above).
    detectors = discover_with_warnings(None if (args.list or args.list_patterns) else args.path)

    listing_result = _handle_listing_modes(args, detectors)
    if listing_result is not None:
        return listing_result

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
    trailing = _TrailingFlags(parser, argv, extras)
    selected = _select_detectors(detectors, args, cfg, trailing)
    if isinstance(selected, int):
        return selected

    present = harness.detect_languages(args.path, cfg.extra_ignores)
    selected = _apply_language_filter(selected, present, only, args)
    if isinstance(selected, int):
        return selected

    selected = [apply_config_to_detector(d, cfg) for d in selected]
    selected = forward_extras(selected, extras)

    # Built-ins get the extra-ignore globs as --extra-ignore args (folded in by
    # apply_config_to_detector above); the env var is only needed for external,
    # manifest-based detectors, which inherit it through subprocess.run.
    needs_env = bool(cfg.extra_ignores) and any(d.module is None for d in selected)
    with exported_extra_ignore(cfg.extra_ignores if needs_env else None):
        return run_selected(selected, args, cfg.warnings)


def _dispatch_subcommand(argv: list[str]) -> "int | None":
    """Handle the non-scan subcommands (version/doctor/prime/baseline/diff/...).

    Returns the process exit code for a recognized subcommand, or None when
    `argv` names none of them, telling the caller to fall through to the
    ordinary `sniff [DIR]` scan flow instead."""
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
    return None


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the default `sniff [DIR]` scan flow.

    Only reached once `_dispatch_subcommand` has ruled out every other
    subcommand, so this parser only ever needs to understand scan flags."""
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
    return parser


def _handle_listing_modes(args: argparse.Namespace, detectors: list[discovery.Detector]) -> "int | None":
    """Handle --list and --list-patterns, the two flags that describe detectors
    instead of running them.

    Returns an exit code when one of these modes fired, or None when neither
    flag was passed, telling the caller to continue into the scan flow."""
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

    return None


@dataclass(frozen=True)
class _TrailingFlags:
    """The argparse state `_select_detectors` needs only to reject un-forwardable
    trailing flags.

    `parser` and `argv` let `reject_extras` re-run the strict parse so argparse
    prints its own "unrecognized arguments" error (and exit code); `extras` is
    the leftover, unrecognized flags themselves. Bundled together because the
    three always travel as a unit and this is their only consumer."""

    parser: argparse.ArgumentParser
    argv: list[str]
    extras: list[str]


def _select_detectors(
    detectors: list[discovery.Detector],
    args: argparse.Namespace,
    cfg: config.Config,
    trailing: _TrailingFlags,
) -> "list[discovery.Detector] | int":
    """Apply --only/--skip/config to `detectors`, warn on typos, and gate extras.

    Returns the narrowed detector list on success, or an int exit code when the
    selection is empty (nothing left to run) or extras can't be forwarded
    (resolves to more than one detector), telling `main` to return early."""
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
    if trailing.extras and len(selected) != 1:
        reject_extras(trailing.parser, trailing.argv, trailing.extras)

    if not selected:
        if args.json:
            print(json.dumps({"path": args.path, "detectors": []}, indent=2))
        else:
            print("No detectors selected after --only/--skip.")
        return 0

    return selected


def _apply_language_filter(
    selected: list[discovery.Detector], present: "set[str]", only: set[str], args: argparse.Namespace
) -> "list[discovery.Detector] | int":
    """Drop detectors that can't read any language this repo contains.

    Returns the filtered list, or an int exit code (0) when nothing survives
    the filter, printing the same "nothing to scan" message in either JSON or
    markdown mode, telling `main` to return early."""
    selected = readable_here(selected, present, only)
    if selected:
        return selected

    found = ", ".join(sorted(present)) or "no supported source files"
    message = (f"No detector covers {found}. "
               f"Run `sniff --list` to see what each detector reads.")
    if args.json:
        print(json.dumps({"path": args.path, "detectors": []}, indent=2))
    else:
        print(message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
