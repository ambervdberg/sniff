#!/usr/bin/env python3
"""Run the sniff-patterns rule catalog and print a compact findings table.

One `ast-grep scan` pass loads every rule under src/sniff/patterns/rules/ and reports its
matches. This script folds that JSON into a small RULE / SEVERITY / COUNT /
TOP LOCATIONS table so the calling agent only ever sees the
summary, never the raw per-match JSON.

Rules print worst severity first (error, warning, info, hint), each heading carries
the full hit count, and only the first `--top-locs` locations are listed.

Usage:
    python format.py [DIR] [--severity error|warning|info|hint] [--rule ID] [--top-locs N]
                     [--extra-ignore GLOB ...]

DIR defaults to the current directory. Vendored/build dirs are skipped by the
shared ignore list, and so is test code, as in every other detector: an `as any`
in a mock or a `!` in a spec is not work anyone is going to do. `--include-tests`
brings them back.

This module is the CLI entry point only. The catalog/expansion logic lives in
`expand.py`, the ast-grep + custom-regex scanning in `scan.py`, path/ignore
helpers in `paths.py`, and table rendering in `render.py`; this file wires them
together into `main()` and re-exports the pieces so `from sniff.patterns import
format as fmt; fmt.whatever(...)` keeps working for every existing caller
(patterns_detector.py, scripts/update_docs.py, the test suite) without needing
to know the module got split.
"""

from __future__ import annotations

import argparse
import shutil      # re-exported only: tests patch format_mod.shutil.which (see test_ast_grep_exe.py)
import subprocess  # re-exported only: tests patch format_mod.subprocess.run (see test_ast_grep_exe.py)
import sys

from sniff import harness as h
from sniff.patterns.expand import RULES_DIR, catalog_rules, rule_languages
from sniff.patterns.paths import IGNORE_DIRS, _extra_ignore_patterns, _in_ignored_dir, _matches_extra_ignore, _rel
from sniff.patterns.render import (
    SEVERITY_ORDER, print_list_rules, print_rule_table, print_rules_ran, render_catalog_table,
)
from sniff.patterns.scan import _require_ast_grep, ast_grep_exe, run_scan, scan_multiline_single_comments

# How many locations one rule may list before the rest collapse into a "+N more"
# row. A single noisy rule used to print every hit (118 rows for py-print-statement
# on this repo), which swamps the caller's context and defeats the point of a
# summary table. The heading still carries the true total, and `--top-locs 0`
# restores the full list when an agent really wants to act on every hit.
DEFAULT_TOP_LOCS = 10


def main(argv: "list[str] | None" = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.list_rules:
        return _run_list_rules(args)

    _require_ast_grep()

    rules = catalog_rules(args.path)
    if not rules:
        _print_no_rules_in_catalog()
        return 0

    disabled = _parse_disabled(args.disable)
    severity_overrides = _parse_severity_overrides(args.severity_override)

    matches = _collect_matches(args)
    by_rule, ran = _group_matches(matches, rules, args, disabled, severity_overrides)

    if not by_rule:
        _print_no_findings_summary(ran, args)
        return 0

    _print_findings_table(by_rule, ran, args)
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    """Every CLI flag, unchanged from the original single-file version."""
    parser = argparse.ArgumentParser(description="Run the sniff-patterns catalog and summarize findings.")
    parser.add_argument("path", nargs="?", default=".", metavar="DIR", help="directory to scan (default: .)")
    parser.add_argument("--severity", help="only show this severity (error|warning|info|hint)")
    parser.add_argument("--rule", help="only show this rule id")
    parser.add_argument("--top-locs", type=int, default=DEFAULT_TOP_LOCS,
                        help=f"cap locations listed per rule (default: {DEFAULT_TOP_LOCS}; "
                             "0 = list every location)")
    # Accepted so `--top` works uniformly across detectors, but ignored: every
    # match is a finding, so there is no ranking to cut off. Without this
    # argument, argparse prefix-matching would silently treat --top as
    # --top-locs and truncate the location lists.
    parser.add_argument("--top", type=int,
                        help="accepted for consistency with the ranking detectors; ignored, "
                             "every match is always reported")
    parser.add_argument("--list-rules", action="store_true",
                        help="print catalog of available rule IDs and exit")
    parser.add_argument("--disable", help="comma-separated rule ids to skip (e.g. from .sniff.toml [rules])")
    parser.add_argument("--severity-override", action="append", default=[], metavar="ID=LEVEL",
                        help="override a rule's severity (repeatable), e.g. no-console-log=error "
                             "(from .sniff.toml [rules])")
    parser.add_argument("--extra-ignore", action="append", metavar="GLOB",
                        help="extra glob to exclude, relative to DIR (repeatable); "
                             "from .sniff.toml [ignore] globs. Overrides SNIFF_EXTRA_IGNORE.")
    parser.add_argument("--include-tests", action="store_true",
                        help="also report findings in test files (excluded by default, "
                             "as in every other detector)")
    return parser


def _print_no_rules_in_catalog() -> None:
    print(f"No rules in the catalog ({RULES_DIR}). Add one with sniff-create.")


def _run_list_rules(args: argparse.Namespace) -> int:
    """Handle `--list-rules`: print the catalog table, or the empty-catalog message."""
    rules = catalog_rules(args.path)
    if not rules:
        _print_no_rules_in_catalog()
    else:
        print_list_rules(rules, args.path)
    return 0


def _parse_disabled(disable_arg: "str | None") -> set[str]:
    """Rule ids to skip, from `--disable a,b,c`."""
    return {r.strip() for r in (disable_arg or "").split(",") if r.strip()}


def _parse_severity_overrides(items: "list[str]") -> "dict[str, str]":
    """rule id -> severity, from repeated `--severity-override ID=LEVEL`.

    Rewrites a rule's reported severity (and its --severity filtering) without
    touching the rule yml. Values from .sniff.toml [rules] arrive here via cli.py."""
    overrides: "dict[str, str]" = {}
    for item in items:
        if "=" in item:
            rid, level = item.split("=", 1)
            overrides[rid.strip()] = level.strip()
    return overrides


def _build_ignore_predicate(args: argparse.Namespace):
    """A `file -> bool` closure combining test-file, vendored-dir and extra-ignore skips."""
    extra_ignores = _extra_ignore_patterns(args.extra_ignore)

    def _ignored(file: str) -> bool:
        # Test code is skipped by default, matching every other detector. A `!`
        # in a spec or an `as any` in a mock is not work anyone is going to do:
        # on excalidraw that was 57% of no-non-null-assertion's findings.
        if not args.include_tests and h.is_test_file(file):
            return True
        return _in_ignored_dir(file, args.path) or _matches_extra_ignore(file, args.path, extra_ignores)

    return _ignored


def _collect_matches(args: argparse.Namespace) -> "list[dict]":
    """ast-grep's findings plus the Python-only comment-shape rule, both ignore-filtered."""
    is_ignored = _build_ignore_predicate(args)

    matches = run_scan(args.path)
    matches = [m for m in matches if not is_ignored(m.get("file", ""))]

    # Add custom Python-based detectors (for rules that can't be expressed in ast-grep)
    custom_matches = scan_multiline_single_comments(args.path)
    custom_matches = [m for m in custom_matches if not is_ignored(m.get("file", ""))]
    matches.extend(custom_matches)

    return matches


def _group_matches(matches: "list[dict]", rules: "list[tuple[str, str, str, str, str]]",
                   args: argparse.Namespace, disabled: "set[str]",
                   severity_overrides: "dict[str, str]"):
    """Fold raw matches into per-rule severity/count/locations, plus the roster of
    rules that actually ran this invocation (whole catalog minus --disable/--rule/--severity)."""
    by_rule: "dict[str, dict]" = {}
    for m in matches:
        rule_id = m.get("ruleId", "(unknown)")
        if rule_id in disabled:
            continue
        if args.rule and rule_id != args.rule:
            continue
        sev = severity_overrides.get(rule_id, m.get("severity", "warning"))
        if args.severity and sev != args.severity:
            continue

        entry = by_rule.setdefault(rule_id, {"severity": sev, "count": 0, "locs": []})
        # `count` tracks every hit even once the location list stops growing, so
        # the heading and the "+N more" row always report the true total.
        entry["count"] += 1
        # top_locs == 0 means list every location so the agent can act on all of
        # them; a positive value caps the list.
        line = m["range"]["start"]["line"] + 1
        if args.top_locs <= 0 or len(entry["locs"]) < args.top_locs:
            entry["locs"].append(f"{_rel(m['file'], args.path)}:{line}")
        if h.FINDINGS_SINK is not None:
            # Raw `m['file']`, not the display-relativized path above: the
            # gate fingerprints on the raw file field for every detector, and
            # is itself responsible for making that portable across scan-root
            # spellings (see gate._relative_file). Pre-relativizing here would
            # double-normalize it against a base (args.path) that gate.py
            # cannot see.
            h.FINDINGS_SINK.append({
                "file": m["file"],
                "line": line,
                "name": rule_id,
                "metrics": {"rule": rule_id, "severity": sev},
            })

    ran = [
        (r[0], severity_overrides.get(r[0], r[1]), *r[2:])
        for r in rules
        if r[0] not in disabled
        and (not args.rule or r[0] == args.rule)
        and (not args.severity or severity_overrides.get(r[0], r[1]) == args.severity)
    ]

    return by_rule, ran


def _print_no_findings_summary(ran: "list[tuple[str, str, str, str, str]]", args: argparse.Namespace) -> None:
    scope = ""
    if args.rule:
        scope = f" matching --rule {args.rule}"
    elif args.severity:
        scope = f" at --severity {args.severity}"
    print(f"sniff-patterns: 0 findings{scope} across {len(ran)} rules in {args.path!r}")
    print_rules_ran(ran)


def _print_findings_table(by_rule: "dict[str, dict]", ran: "list[tuple[str, str, str, str, str]]",
                          args: argparse.Namespace) -> None:
    sorted_rules = sorted(by_rule.items(),
                          key=lambda kv: (SEVERITY_ORDER.get(kv[1]["severity"], 9), -kv[1]["count"]))

    rows = [(rid, e["severity"], e["count"], e["locs"]) for rid, e in sorted_rules]

    total = sum(r[2] for r in rows)
    tests = "tests included" if args.include_tests else "tests excluded"
    print(f"sniff-patterns: {total} findings, {len(rows)} of {len(ran)} rules matched "
          f"in {args.path!r} ({tests})\n")

    print_rule_table(rows)
    print_rules_ran(ran)


if __name__ == "__main__":
    sys.exit(main())
