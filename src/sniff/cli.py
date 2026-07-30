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
    sniff [DIR] [--only a,b] [--skip a,b] [--list]
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
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace

from sniff import config, contribute, discovery, patterns, test_rules


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
    (a subprocess/external detector still gets it via SNIFF_EXTRA_IGNORE, set
    once in main() around the subprocess batch, not here). Returns `detector`
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


def _run_module_detector(detector: discovery.Detector, path: str) -> "tuple[str, int, str | None]":
    """Run a built-in detector's module.main() in-process, capturing its stdout.

    Mirrors what the subprocess path gets from a script: (stdout text, exit code,
    error message). Detectors call `sys.exit("some message")` on a usage error
    (e.g. no supported source files); in-process that raises SystemExit with a
    string `.code` instead of printing to stderr and exiting, so it is caught
    here and folded into the same shape run_detector/_json already expect."""
    buf = io.StringIO()
    error: "str | None" = None
    try:
        with contextlib.redirect_stdout(buf):
            result = detector.module.main([path, *detector.args])
        code = result if isinstance(result, int) else 0
    except SystemExit as exc:
        if isinstance(exc.code, int):
            code = exc.code
        elif exc.code is None:
            code = 0
        else:
            code = 1
            error = str(exc.code)
    return buf.getvalue(), code, error


def run_detector(detector: discovery.Detector, path: str) -> str:
    """Run one detector over `path`, return its stdout (or an error note).

    Built-ins (`detector.module` set) run in-process; external detectors still
    shell out to their script. A detector that fails (non-zero exit, crash)
    yields an error section instead of aborting the whole run, so one broken
    detector cannot suppress the others."""
    if detector.module is not None:
        out, code, error = _run_module_detector(detector, path)
        out = out.strip()
        if code != 0:
            err = error or f"exit code {code}"
            return f"{out}\n\n_detector exited non-zero: {err}_".strip()
        return out or "_no output_"

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
    """Run one detector over `path`, return a JSON-serializable result.

    Mirrors run_detector's handling (in-process for built-ins, subprocess for
    external) but keeps stdout/stderr/exit_code structured instead of folding
    them into a markdown string, so `--json` output stays machine-parseable
    (e.g. by evals/scorer.py)."""
    if detector.module is not None:
        out, code, error = _run_module_detector(detector, path)
        return {
            "detector": detector.name,
            "title": detector.title,
            "exit_code": code,
            "output": out.strip(),
            "error": error,
        }

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


# Repo root, one level above skills/ (discovery.SKILLS_ROOT is skills/).
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
    """Version reported by importlib.metadata for the installed distribution
    (`sniff-smells`, or the legacy `sniff` name), or None."""
    try:
        from importlib.metadata import PackageNotFoundError, version as pkg_version
        for dist in ("sniff-smells", "sniff"):
            try:
                return pkg_version(dist)
            except PackageNotFoundError:
                continue
        return None
    except ImportError:
        return None


def get_version() -> str:
    """Installed package version if `sniff` is installed, else the source checkout's
    pyproject.toml version. Falls back to 'unknown' rather than crashing."""
    return _installed_package_version() or _pyproject_version() or "unknown"


@dataclass
class EnvironmentFacts:
    """Everything `doctor` and `prime` both need to know about the environment,
    gathered once so the two commands can't drift on how they detect it."""

    detectors: list[discovery.Detector]
    errors: list[str]
    has_ast_grep: bool
    pkg_version: str | None
    plugin_version: str | None
    installed_version: str | None


def _gather_environment_facts() -> EnvironmentFacts:
    detectors, errors = discovery.discover()
    return EnvironmentFacts(
        detectors=detectors,
        errors=errors,
        has_ast_grep=shutil.which("ast-grep") is not None,
        pkg_version=_pyproject_version(),
        plugin_version=_plugin_version(),
        installed_version=_installed_package_version(),
    )


def run_doctor() -> int:
    """Check prerequisites and consistency, print a PASS/FAIL line per check.

    Returns 0 if every check passed, 1 if any failed, so callers (and CI) can
    gate on the exit code instead of parsing output."""
    facts = _gather_environment_facts()
    ok = True
    lines: list[str] = []

    py_ok = sys.version_info >= (3, 9)
    py_str = ".".join(str(part) for part in sys.version_info[:3])
    lines.append(f"{'PASS' if py_ok else 'FAIL'} python {py_str} (>=3.9 required)")
    ok &= py_ok

    lines.append(
        f"{'PASS' if facts.has_ast_grep else 'FAIL'} ast-grep "
        + ("found on PATH" if facts.has_ast_grep else "not found on PATH (see https://ast-grep.github.io)")
    )
    ok &= facts.has_ast_grep

    if facts.errors:
        ok = False
        for err in facts.errors:
            lines.append(f"FAIL manifest: {err}")
    else:
        lines.append(f"PASS {len(facts.detectors)} detector manifest(s) valid")

    names = [d.name for d in facts.detectors]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        ok = False
        lines.append(f"FAIL duplicate detector name(s): {', '.join(dupes)}")
    else:
        lines.append("PASS no duplicate detector names")

    if facts.pkg_version is None or facts.plugin_version is None:
        lines.append("SKIP version consistency (not a source checkout)")
    elif facts.pkg_version == facts.plugin_version:
        lines.append(f"PASS package and plugin versions match ({facts.pkg_version})")
    else:
        ok = False
        lines.append(f"FAIL version drift: pyproject.toml={facts.pkg_version} plugin.json={facts.plugin_version}")

    local_rules_dir = os.path.join(".sniff", "rules")
    if os.path.isdir(local_rules_dir):
        core_rules_dir = patterns.rules_dir()
        core_ids = {os.path.splitext(n)[0] for n in os.listdir(core_rules_dir) if n.endswith((".yml", ".yaml"))}
        local_ids = {os.path.splitext(n)[0] for n in os.listdir(local_rules_dir) if n.endswith((".yml", ".yaml"))}
        for rule_id in sorted(local_ids & core_ids):
            lines.append(f"WARN local rule {rule_id!r} shadows core rule; contributed already? delete the local copy")

    sniff_toml = os.path.join(os.getcwd(), ".sniff.toml")
    if os.path.isfile(sniff_toml):
        cfg = config.load(os.getcwd())
        for warning in cfg.warnings:
            lines.append(f"WARN {warning}")
        if not cfg.warnings:
            lines.append("PASS .sniff.toml valid")

    print("\n".join(lines))
    return 0 if ok else 1


def run_prime() -> None:
    """Print agent-optimized context: version, detectors, prereqs, usage hints,
    caveats. Never runs a scan, so it stays cheap to call at session start."""
    facts = _gather_environment_facts()
    version = facts.installed_version or facts.pkg_version or "unknown"
    lines: list[str] = [f"sniff {version}", ""]

    lines.append("PREREQUISITES")
    lines.append(f"  python {'.'.join(str(p) for p in sys.version_info[:3])}")
    lines.append(f"  ast-grep: {'found on PATH' if facts.has_ast_grep else 'MISSING (see https://ast-grep.github.io)'}")
    lines.append("")

    lines.append(f"DETECTORS ({len(facts.detectors)})")
    for d in facts.detectors:
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
    if not facts.has_ast_grep:
        caveats.append("ast-grep is not on PATH; every detector except sniff-patterns will fail to run.")
    if facts.errors:
        caveats.append(f"{len(facts.errors)} detector manifest error(s); run `sniff doctor` for details.")
    if facts.pkg_version and facts.plugin_version and facts.pkg_version != facts.plugin_version:
        caveats.append(
            f"version drift: pyproject.toml={facts.pkg_version} vs plugin.json={facts.plugin_version}; "
            "installed CLI may be stale."
        )
    if facts.installed_version and facts.pkg_version and facts.installed_version != facts.pkg_version:
        caveats.append(
            f"stale install: pip-installed sniff is {facts.installed_version}, source checkout is {facts.pkg_version}; "
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

    counts = _scan_counts(_discover_with_warnings(path), path)

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
    exists yet), so the exit code alone answers "did this get worse?".

    --comment switches the table to markdown (| DETECTOR | BASELINE | CURRENT |
    DELTA |) with a bold verdict line, suitable to paste as a PR comment."""
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
        baseline_counts: dict[str, int] = json.load(fh).get("counts", {})

    current_counts = _scan_counts(_discover_with_warnings(path), path)

    names = sorted(set(baseline_counts) | set(current_counts))
    worse = False

    if comment:
        lines = ["| DETECTOR | BASELINE | CURRENT | DELTA |", "| --- | --- | --- | --- |"]
        for name in names:
            before, after = baseline_counts.get(name, 0), current_counts.get(name, 0)
            delta = after - before
            worse = worse or delta > 0
            lines.append(f"| {name} | {before} | {after} | {f'+{delta}' if delta > 0 else delta} |")
        print("\n".join(lines))
        print()
        print("**worse**" if worse else "**same or better**")
        return 1 if worse else 0

    lines = [f"{'DETECTOR':<24} {'BASELINE':>8} {'CURRENT':>8} {'DELTA':>8}"]
    for name in names:
        before, after = baseline_counts.get(name, 0), current_counts.get(name, 0)
        delta = after - before
        worse = worse or delta > 0
        lines.append(f"{name:<24} {before:>8} {after:>8} {(f'+{delta}' if delta > 0 else str(delta)):>8}")
    print("\n".join(lines))
    print()
    print("worse" if worse else "same or better")
    return 1 if worse else 0


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
        return test_rules.run_test_rules(_REPO_ROOT)
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
            "  sniff --skip sniff-patterns  # skip pattern rules\n"
            "  sniff version                # print installed version\n"
            "  sniff doctor                 # check prerequisites and exit 0/1\n"
            "  sniff prime                  # agent-optimized context (no scan)\n"
            "  sniff baseline write [DIR]   # save per-detector counts to .sniff/baseline.json\n"
            "  sniff diff [DIR]             # compare current scan to the saved baseline\n"
            "  sniff test-rules             # run rule fixture tests, exit 0/1\n"
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
    parser.add_argument("--list-patterns", action="store_true", help="list pattern rules catalog (RULE / SEVERITY / MESSAGE) and exit")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown (works with scan and --list)")

    warn_hallucinated_flags(argv)
    args = parser.parse_args(argv)

    # --list/--list-patterns describe detectors in general, not a scan of `path`,
    # so they omit the scan path (matching doctor/prime, handled earlier above).
    detectors = _discover_with_warnings(None if (args.list or args.list_patterns) else args.path)

    if args.list:
        if args.json:
            print(json.dumps([
                {"name": d.name, "title": d.title, "script": d.script, "args": d.args}
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
        print("No detectors found (no skills/*/detector.yml manifests).")
        return 0

    if not os.path.isdir(args.path):
        print(f"error: {args.path!r} is not a directory. Check the path and try again.", file=sys.stderr)
        return 1

    cfg = config.load(args.path)
    selected, unknown = select_with_config(detectors, _split_csv(args.only), _split_csv(args.skip), cfg)
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
        return 0

    selected = [apply_config_to_detector(d, cfg) for d in selected]
    if cfg.extra_ignores and any(d.module is None for d in selected):
        # Built-ins get extra-ignore globs as --extra-ignore args (folded in by
        # apply_config_to_detector above); this env var is only needed for the
        # remaining subprocess/external detectors (sniff-patterns' format.py),
        # inherited by their subprocess.run calls (no explicit env= restricts them).
        os.environ["SNIFF_EXTRA_IGNORE"] = ",".join(cfg.extra_ignores)

    if args.json:
        results = [run_detector_json(d, args.path) for d in selected]
        print(json.dumps({"path": args.path, "detectors": results}, indent=2))
        return 0

    names = ", ".join(d.name for d in selected)
    print(f"sniff: {len(selected)} detectors over {args.path!r}: {names}\n")

    for detector in selected:
        print(f"## {detector.name}\n")
        print(run_detector(detector, args.path))
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
