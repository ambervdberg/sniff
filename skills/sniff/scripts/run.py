#!/usr/bin/env python3
"""sniff: run every smell detector over a repo in one pass.

The umbrella entry point. Discovers detectors via their detector.yml manifests
(see discovery.py), runs each one's script over the scan DIR, and prints one
markdown section per detector. Default runs all detectors with no flag; narrow with --only / --skip,
or just list what is available with --list.

Each detector returns only its own compact table (ranked top-N or location list),
never source, so the aggregate stays token-cheap: this runner just concatenates
those sections under per-detector headings. It never reimplements a detector; it
shells out to the detector's existing script, so the standalone skill and the
aggregate run always agree.

Usage:
    python run.py [DIR] [--only a,b] [--skip a,b] [--list]
    python run.py version
    python run.py doctor
    python run.py prime
    python run.py baseline write [DIR]
    python run.py diff [DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

try:
    import discovery  # direct run: python run.py
except ModuleNotFoundError:
    from skills.sniff.scripts import discovery  # installed via uv tool install


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


def run_detector_json(detector: discovery.Detector, path: str) -> dict:
    """Run one detector's script over `path`, return a JSON-serializable result.

    Mirrors run_detector's subprocess handling but keeps stdout/stderr/exit_code
    structured instead of folding them into a markdown string, so `--json`
    output stays machine-parseable (e.g. by evals/scorer.py)."""
    cmd = [sys.executable, detector.script, path, *detector.args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        return {
            "detector": detector.name,
            "title": detector.title,
            "exit_code": None,
            "output": None,
            "error": str(exc),
        }
    return {
        "detector": detector.name,
        "title": detector.title,
        "exit_code": proc.returncode,
        "output": proc.stdout.strip(),
        "error": proc.stderr.strip() or None,
    }


# Repo root, two levels above skills/ (discovery.SKILLS_ROOT is skills/).
# Only present in a source checkout; an installed package has neither file,
# so version/consistency checks fall back to package metadata or skip.
_REPO_ROOT = os.path.dirname(discovery.SKILLS_ROOT)


def _pyproject_version() -> str | None:
    """Read [project] version from pyproject.toml, or None if not a source checkout."""
    path = os.path.join(_REPO_ROOT, "pyproject.toml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else None


def _plugin_version() -> str | None:
    """Read version from .claude-plugin/plugin.json, or None if not present."""
    path = os.path.join(_REPO_ROOT, ".claude-plugin", "plugin.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("version")


def _installed_package_version() -> str | None:
    """Version reported by importlib.metadata for an installed `sniff`, or None."""
    try:
        from importlib.metadata import PackageNotFoundError, version as pkg_version
        try:
            return pkg_version("sniff")
        except PackageNotFoundError:
            return None
    except ImportError:
        return None


def get_version() -> str:
    """Installed package version if `sniff` is installed, else the source checkout's
    pyproject.toml version. Falls back to 'unknown' rather than crashing."""
    return _installed_package_version() or _pyproject_version() or "unknown"


def run_doctor() -> int:
    """Check prerequisites and consistency, print a PASS/FAIL line per check.

    Returns 0 if every check passed, 1 if any failed, so callers (and CI) can
    gate on the exit code instead of parsing output."""
    ok = True
    lines: list[str] = []

    py_ok = sys.version_info >= (3, 9)
    py_str = ".".join(str(part) for part in sys.version_info[:3])
    lines.append(f"{'PASS' if py_ok else 'FAIL'} python {py_str} (>=3.9 required)")
    ok &= py_ok

    has_ast_grep = shutil.which("ast-grep") is not None
    lines.append(
        f"{'PASS' if has_ast_grep else 'FAIL'} ast-grep "
        + ("found on PATH" if has_ast_grep else "not found on PATH (see https://ast-grep.github.io)")
    )
    ok &= has_ast_grep

    detectors, errors = discovery.discover()
    if errors:
        ok = False
        for err in errors:
            lines.append(f"FAIL manifest: {err}")
    else:
        lines.append(f"PASS {len(detectors)} detector manifest(s) valid")

    names = [d.name for d in detectors]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        ok = False
        lines.append(f"FAIL duplicate detector name(s): {', '.join(dupes)}")
    else:
        lines.append("PASS no duplicate detector names")

    pkg_ver, plugin_ver = _pyproject_version(), _plugin_version()
    if pkg_ver is None or plugin_ver is None:
        lines.append("SKIP version consistency (not a source checkout)")
    elif pkg_ver == plugin_ver:
        lines.append(f"PASS package and plugin versions match ({pkg_ver})")
    else:
        ok = False
        lines.append(f"FAIL version drift: pyproject.toml={pkg_ver} plugin.json={plugin_ver}")

    print("\n".join(lines))
    return 0 if ok else 1


def run_prime() -> None:
    """Print agent-optimized context: version, detectors, prereqs, usage hints,
    caveats. Never runs a scan, so it stays cheap to call at session start."""
    detectors, errors = discovery.discover()
    lines: list[str] = [f"sniff {get_version()}", ""]

    lines.append("PREREQUISITES")
    has_ast_grep = shutil.which("ast-grep") is not None
    lines.append(f"  python {'.'.join(str(p) for p in sys.version_info[:3])}")
    lines.append(f"  ast-grep: {'found on PATH' if has_ast_grep else 'MISSING (see https://ast-grep.github.io)'}")
    lines.append("")

    lines.append(f"DETECTORS ({len(detectors)})")
    for d in detectors:
        lines.append(f"  {d.name}: {d.title}")
    lines.append("")

    lines.append("COMMON COMMANDS")
    lines.append("  sniff [DIR]                       run all detectors")
    lines.append("  sniff --only <name>[,<name>] [DIR] run specific detectors (see DETECTORS above)")
    lines.append("  sniff --list                      list detectors as a markdown table")
    lines.append("  sniff --list-patterns              list sniff-patterns rule catalog")
    lines.append("  sniff --json [DIR]                 machine-readable scan output")
    lines.append("  sniff doctor                       check prerequisites, exit 0/1")
    lines.append("  sniff version                      print installed version")
    lines.append("")

    caveats: list[str] = []
    if not has_ast_grep:
        caveats.append("ast-grep is not on PATH; every detector except sniff-patterns will fail to run.")
    if errors:
        caveats.append(f"{len(errors)} detector manifest error(s); run `sniff doctor` for details.")
    pkg_ver, plugin_ver = _pyproject_version(), _plugin_version()
    if pkg_ver and plugin_ver and pkg_ver != plugin_ver:
        caveats.append(f"version drift: pyproject.toml={pkg_ver} vs plugin.json={plugin_ver}; installed CLI may be stale.")
    installed_ver = _installed_package_version()
    if installed_ver and pkg_ver and installed_ver != pkg_ver:
        caveats.append(
            f"stale install: pip-installed sniff is {installed_ver}, source checkout is {pkg_ver}; "
            "reinstall (pip install -e .) to pick up local changes."
        )

    lines.append("CAVEATS")
    if caveats:
        lines.extend(f"  - {c}" for c in caveats)
    else:
        lines.append("  none")

    print("\n".join(lines))


# Patterns detectors use to report a true total in their summary line, tried in
# order. Falls back to _count_table_rows() when none match (e.g. "No X found").
# Catches the common totals so a capped table (e.g. "Largest 20 of 262 methods")
# doesn't mask a regression that grew the true count but not the displayed rows.
_TOTAL_COUNT_PATTERNS = [
    re.compile(r"\b\d+\s+of\s+(\d+)\b"),     # "Largest 20 of 262 methods"
    re.compile(r"\((\d+)\s+found\b"),         # "(71 found; tests excluded)"
    re.compile(r"\b(\d+)\s+findings?\b"),     # "0 findings across 9 rules"
]


def _count_table_rows(output: str) -> int:
    """Count markdown table data rows in a detector's output.

    A header row is a non-separator pipe row immediately followed by a
    `| --- |` separator row; both are skipped. Tracking this per-table (instead
    of a single global "first row is the header" flag) keeps multi-table output
    correct: sniff-patterns prints one table per matched rule, and a global flag
    would count every table-after-the-first's own header as a finding."""
    lines = [line.strip() for line in output.splitlines()]
    is_separator = lambda line: bool(re.fullmatch(r"[\s|:-]+", line))

    rows = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("|") or not line.endswith("|"):
            i += 1
            continue
        if is_separator(line):
            i += 1
            continue
        if i + 1 < len(lines) and is_separator(lines[i + 1]):
            i += 2  # header followed by its separator: skip both
            continue
        rows += 1
        i += 1
    return rows


def _count_findings(output: str) -> int:
    """Best-effort true finding count for one detector's output.

    Tries to read the total straight out of the detector's own summary line
    (most detectors report it even when their table is capped at top-N);
    falls back to _count_table_rows() when no recognized pattern matches."""
    first_line = output.splitlines()[0] if output else ""
    for pattern in _TOTAL_COUNT_PATTERNS:
        match = pattern.search(first_line)
        if match:
            return int(match.group(1))
    return _count_table_rows(output)


def _scan_counts(detectors: list[discovery.Detector], path: str) -> dict[str, int]:
    """Run every detector over `path`, return {detector_name: finding_count}."""
    counts: dict[str, int] = {}
    for d in detectors:
        result = run_detector_json(d, path)
        counts[d.name] = _count_findings(result.get("output") or "")
    return counts


def run_baseline(argv: list[str]) -> int:
    """`sniff baseline write [DIR]`: scan DIR, save per-detector counts as JSON.

    Saved to <DIR>/.sniff/baseline.json so a later `sniff diff` can compare
    against it. Returns 0 on success, 1 on a usage or path error."""
    if not argv or argv[0] != "write":
        print("usage: sniff baseline write [DIR]", file=sys.stderr)
        return 1

    path = argv[1] if len(argv) > 1 else "."
    if not os.path.isdir(path):
        print(f"error: {path!r} is not a directory. Check the path and try again.", file=sys.stderr)
        return 1

    detectors, errors = discovery.discover()
    for err in errors:
        print(f"warning: {err}", file=sys.stderr)

    counts = _scan_counts(detectors, path)

    baseline_dir = os.path.join(path, ".sniff")
    os.makedirs(baseline_dir, exist_ok=True)
    baseline_path = os.path.join(baseline_dir, "baseline.json")
    with open(baseline_path, "w", encoding="utf-8") as fh:
        json.dump({"path": path, "counts": counts}, fh, indent=2)

    print(f"sniff: baseline written to {baseline_path} ({len(counts)} detectors)")
    return 0


def run_diff(argv: list[str]) -> int:
    """`sniff diff [DIR]`: compare a fresh scan of DIR against its saved baseline.

    Prints a per-detector count delta table. Returns 0 if no detector's count
    increased (same or better), 1 if any detector regressed (or no baseline
    exists yet), so the exit code alone answers "did this get worse?"."""
    path = argv[0] if argv else "."
    if not os.path.isdir(path):
        print(f"error: {path!r} is not a directory. Check the path and try again.", file=sys.stderr)
        return 1

    baseline_path = os.path.join(path, ".sniff", "baseline.json")
    if not os.path.isfile(baseline_path):
        print(f"error: no baseline at {baseline_path!r}. Run `sniff baseline write {path}` first.", file=sys.stderr)
        return 1

    with open(baseline_path, "r", encoding="utf-8") as fh:
        baseline_counts: dict[str, int] = json.load(fh).get("counts", {})

    detectors, errors = discovery.discover()
    for err in errors:
        print(f"warning: {err}", file=sys.stderr)

    current_counts = _scan_counts(detectors, path)

    names = sorted(set(baseline_counts) | set(current_counts))
    lines = [f"{'DETECTOR':<24} {'BASELINE':>8} {'CURRENT':>8} {'DELTA':>8}"]
    worse = False
    for name in names:
        before, after = baseline_counts.get(name, 0), current_counts.get(name, 0)
        delta = after - before
        worse = worse or delta > 0
        lines.append(f"{name:<24} {before:>8} {after:>8} {(f'+{delta}' if delta > 0 else str(delta)):>8}")
    print("\n".join(lines))
    print()
    print("worse" if worse else "same or better")
    return 1 if worse else 0


def main() -> None:
    # version/doctor are subcommands, not detector flags, so they're handled before
    # the DIR-positional parser below would otherwise treat "doctor" as a path.
    if sys.argv[1:2] == ["version"]:
        print(f"sniff {get_version()}")
        return
    if sys.argv[1:2] == ["doctor"]:
        sys.exit(run_doctor())
    if sys.argv[1:2] == ["prime"]:
        run_prime()
        return
    if sys.argv[1:2] == ["baseline"]:
        sys.exit(run_baseline(sys.argv[2:]))
    if sys.argv[1:2] == ["diff"]:
        sys.exit(run_diff(sys.argv[2:]))

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
            "  sniff --skip sniff-patterns  # skip pattern rules\n"
            "  sniff version                # print installed version\n"
            "  sniff doctor                 # check prerequisites and exit 0/1\n"
            "  sniff prime                  # agent-optimized context (no scan)\n"
            "  sniff baseline write [DIR]   # save per-detector counts to .sniff/baseline.json\n"
            "  sniff diff [DIR]             # compare current scan to the saved baseline\n"
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
    parser.add_argument("--list-patterns", action="store_true", help="list pattern rules catalog (RULE / SEVERITY / MESSAGE) and exit")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown (works with scan and --list)")

    warn_hallucinated_flags(sys.argv[1:])
    args = parser.parse_args()

    detectors, errors = discovery.discover()
    for err in errors:
        print(f"warning: {err}", file=sys.stderr)

    if args.list:
        if args.json:
            print(json.dumps([
                {"name": d.name, "title": d.title, "script": d.script, "args": d.args}
                for d in detectors
            ], indent=2))
        else:
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

    if not os.path.isdir(args.path):
        print(f"error: {args.path!r} is not a directory. Check the path and try again.", file=sys.stderr)
        sys.exit(1)

    selected, unknown = select(detectors, _split_csv(args.only), _split_csv(args.skip))
    for name in unknown:
        import difflib
        known = [d.name for d in detectors]
        close = difflib.get_close_matches(name, known, n=3, cutoff=0.4)
        hint = f" Did you mean: {', '.join(close)}?" if close else f" Run `sniff --list` to see all detectors."
        print(f"warning: unknown detector {name!r}.{hint}", file=sys.stderr)

    if not selected:
        if args.json:
            print(json.dumps({"path": args.path, "detectors": []}, indent=2))
        else:
            print("No detectors selected after --only/--skip.")
        return

    if args.json:
        results = [run_detector_json(d, args.path) for d in selected]
        print(json.dumps({"path": args.path, "detectors": results}, indent=2))
        return

    names = ", ".join(d.name for d in selected)
    print(f"sniff: {len(selected)} detectors over {args.path!r}: {names}\n")

    for detector in selected:
        print(f"## {detector.name}\n")
        print(run_detector(detector, args.path))
        print()


if __name__ == "__main__":
    main()
