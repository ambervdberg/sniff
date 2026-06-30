#!/usr/bin/env python3
"""sniff: run every smell detector over a repo in one pass.

The umbrella entry point. Discovers detectors via their detector.yml manifests
(see discovery.py), runs each one's script over the scan PATH, and prints one
markdown section per detector. Default is `--all`; narrow with --only / --skip,
or just list what is available with --list.

Each detector returns only its own compact table (ranked top-N or location list),
never source, so the aggregate stays token-cheap: this runner just concatenates
those sections under per-detector headings. It never reimplements a detector; it
shells out to the detector's existing script, so the standalone skill and the
aggregate run always agree.

Usage:
    python run.py [PATH] [--only a,b] [--skip a,b] [--list]
"""

from __future__ import annotations

import argparse
import subprocess
import sys

try:
    import discovery  # direct run: python run.py
except ModuleNotFoundError:
    from skills.sniff.scripts import discovery  # installed via uv tool install


def _split_csv(value: str | None) -> set[str]:
    """Parse a comma-separated --only/--skip value into a set of detector names."""
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


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


def run_detector(detector: discovery.Detector, path: str) -> str:
    """Run one detector's script over `path`, return its stdout (or an error note).

    A detector that fails (non-zero exit, crash) yields an error section instead of
    aborting the whole run, so one broken detector cannot suppress the others."""
    cmd = [sys.executable, detector.script, path, *detector.args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        return f"_detector failed to launch: {exc}_"

    out = proc.stdout.strip()
    if proc.returncode != 0:
        err = proc.stderr.strip() or f"exit code {proc.returncode}"
        return f"{out}\n\n_detector exited non-zero: {err}_".strip()
    return out or "_no output_"


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sniff",
        description="Run every code-smell detector over a repo in one pass.",
        epilog=(
            "Examples:\n"
            "  sniff                        # scan current directory, all detectors\n"
            "  sniff <dir>                  # scan any directory\n"
            "  sniff --list                 # show available detectors\n"
            "  sniff --only largest-methods,cyclomatic-complexity\n"
            "  sniff --skip sniff-patterns  # skip pattern rules\n"
            "\n"
            "Pattern rules only:  sniff --only sniff-patterns [DIR]\n"
            "List pattern rules:  sniff --list-patterns\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", nargs="?", default=".", metavar="DIR", help="directory to scan (default: current directory)")
    parser.add_argument("--only", help="comma-separated detector names to run (default: all)")
    parser.add_argument("--skip", help="comma-separated detector names to skip")
    parser.add_argument("--list", action="store_true", help="list discovered detectors and exit")
    parser.add_argument("--list-patterns", action="store_true", help="list pattern rules catalog (RULE / SEVERITY / MESSAGE) and exit")
    args = parser.parse_args()

    detectors, errors = discovery.discover()
    for err in errors:
        print(f"warning: {err}", file=sys.stderr)

    if args.list:
        print(discovery.render_list(detectors))
        return

    if args.list_patterns:
        patterns = next((d for d in detectors if d.name == "sniff-patterns"), None)
        if not patterns:
            print("error: sniff-patterns detector not found (run --list to see available detectors)", file=sys.stderr)
            sys.exit(1)
        proc = subprocess.run([sys.executable, patterns.script, "--list-rules"], capture_output=True, text=True)
        print(proc.stdout.strip())
        if proc.returncode != 0:
            sys.exit(proc.returncode)
        return

    if not detectors:
        print("No detectors found (no skills/*/detector.yml manifests).")
        return

    selected, unknown = select(detectors, _split_csv(args.only), _split_csv(args.skip))
    for name in unknown:
        print(f"warning: unknown detector {name!r} (see --list)", file=sys.stderr)

    if not selected:
        print("No detectors selected after --only/--skip.")
        return

    names = ", ".join(d.name for d in selected)
    print(f"sniff: {len(selected)} detectors over {args.path!r}: {names}\n")

    for detector in selected:
        print(f"## {detector.name}\n")
        print(run_detector(detector, args.path))
        print()


if __name__ == "__main__":
    main()
