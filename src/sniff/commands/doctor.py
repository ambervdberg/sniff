"""`sniff doctor` and `sniff prime`: environment and prerequisite reporting.

Both commands answer "is this machine set up correctly", just for different
audiences: `doctor` is a human-readable PASS/FAIL checklist with a gate-able
exit code, `prime` is the agent-facing context dump printed once at session
start. `_gather_environment_facts` is the one place that inspects the
environment, so the two commands can't drift on how they detect the same
thing.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass

from sniff import config, discovery, patterns
from sniff.versioning import _installed_package_version, _upgrade_available_caveat, get_version


@dataclass
class EnvironmentFacts:
    """Everything `doctor` and `prime` both need to know about the environment,
    gathered once so the two commands can't drift on how they detect it."""

    detectors: list[discovery.Detector]
    errors: list[str]
    has_ast_grep: bool
    installed_version: str | None


def _gather_environment_facts() -> EnvironmentFacts:
    detectors, errors = discovery.discover()
    return EnvironmentFacts(
        detectors=detectors,
        errors=errors,
        has_ast_grep=shutil.which("ast-grep") is not None,
        installed_version=_installed_package_version(),
    )


def run_doctor() -> int:
    """Check prerequisites and consistency, print a PASS/FAIL line per check.

    Returns 0 if every check passed, 1 if any failed, so callers (and CI) can
    gate on the exit code instead of parsing output."""
    facts = _gather_environment_facts()
    ok = True
    lines: list[str] = []

    # Must match `requires-python` in pyproject.toml: reporting a lower floor here would
    # PASS an interpreter that pip already refused to install sniff on.
    py_ok = sys.version_info >= (3, 10)
    py_str = ".".join(str(part) for part in sys.version_info[:3])
    lines.append(f"{'PASS' if py_ok else 'FAIL'} python {py_str} (>=3.10 required)")
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
    lines: list[str] = [f"sniff {get_version()}", ""]

    lines.append("PREREQUISITES")
    lines.append(f"  python {'.'.join(str(p) for p in sys.version_info[:3])}")
    lines.append(f"  ast-grep: {'found on PATH' if facts.has_ast_grep else 'MISSING (see https://ast-grep.github.io)'}")
    lines.append("")

    lines.append(f"DETECTORS ({len(facts.detectors)})")
    for d in facts.detectors:
        lines.append(f"  {d.name}: {d.title} [{discovery.language_cell(d)}]")
    lines.append("")
    lines.append("  [languages] is what that detector can read; sniff skips the rest.")
    lines.append("")

    # Every user-facing subcommand belongs here, gate included: an agent that
    # never sees `baseline`/`diff` in this block never learns sniff can gate a
    # build. tests/test_cli.py holds the two lists together.
    lines.append("COMMON COMMANDS")
    lines.append("  sniff [DIR]                        run all detectors")
    lines.append("  sniff --only <name>[,<name>] [DIR] run specific detectors (see DETECTORS above)")
    lines.append("  sniff --skip <name>[,<name>] [DIR] run every detector except those")
    lines.append("  sniff --all [DIR]                  explicit alias for the default full run")
    lines.append("  sniff --list                       list detectors as a markdown table")
    lines.append("  sniff --list-patterns              list sniff-patterns rule catalog")
    lines.append("  sniff --json [DIR]                 machine-readable scan output")
    lines.append("  sniff --ignore <glob> [DIR]        exclude paths (repeatable; adds to .sniff.toml)")
    lines.append("  sniff baseline write [DIR]         save finding fingerprints to .sniff/baseline.json")
    lines.append("  sniff diff [DIR]                   re-scan against that baseline; exit 1 on regression")
    lines.append("    agent loop: `sniff baseline write` before editing, `sniff diff` after; exit 1 means the repo got worse")
    lines.append("  sniff contribute <rule-id>         send a local pattern rule upstream")
    lines.append("  sniff doctor                       check prerequisites, exit 0/1")
    lines.append("  sniff prime                        print this context block; never scans")
    lines.append("  sniff version                      print installed version")
    lines.append("")

    caveats: list[str] = []
    if not facts.has_ast_grep:
        # Named from what the detectors declare, never written out here: a
        # hardcoded list goes stale the next time a parser-free detector lands,
        # and telling an agent a working detector will fail is worse than silence.
        parser_free = ", ".join(d.name for d in facts.detectors if not d.needs_ast_grep)
        caveats.append(
            f"ast-grep is not on PATH; only {parser_free} will run. "
            "Every other detector, sniff-patterns included, parses with it and will fail."
        )
    if facts.errors:
        caveats.append(f"{len(facts.errors)} detector manifest error(s); run `sniff doctor` for details.")
    upgrade_caveat = _upgrade_available_caveat(facts.installed_version)
    if upgrade_caveat:
        caveats.append(upgrade_caveat)

    lines.append("CAVEATS")
    if caveats:
        lines.extend(f"  - {c}" for c in caveats)
    else:
        lines.append("  none")

    print("\n".join(lines))
