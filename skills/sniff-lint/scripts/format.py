#!/usr/bin/env python3
"""Run the sniff-lint rule catalog and print a compact findings table.

One `ast-grep scan` pass loads every rule under sniff-lint/rules/ and reports its
matches. This script folds that JSON into a small RULE / SEVERITY / COUNT /
TOP LOCATIONS table so the calling agent only ever sees the
summary, never the raw per-match JSON.

Usage:
    python format.py [PATH] [--severity error|warning|info|hint] [--rule ID] [--top-locs N]

PATH defaults to the current directory. Vendored/build dirs are skipped by the
shared ignore list; test files are NOT excluded here (a lint finding in a test is
still a finding).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SGCONFIG = os.path.normpath(os.path.join(HERE, "..", "sgconfig.yml"))
RULES_DIR = os.path.normpath(os.path.join(HERE, "..", "rules"))

# Same vendored/build dirs the harness ignores; kept local so this script has no
# import dependency on _ast-harness (it speaks ast-grep's scan JSON, not Match).
IGNORE_DIRS = {
    "node_modules", "dist", "build", "out", "coverage", ".git", ".nx",
    ".angular", ".next", "vendor", "target", "__pycache__", ".venv", "venv",
}

# ast-grep severity ordering, worst first, for sorting the table.
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2, "hint": 3}


def _require_ast_grep() -> None:
    if not shutil.which("ast-grep"):
        sys.exit("error: ast-grep is not installed or not on PATH. See https://ast-grep.github.io")


def _in_ignored_dir(path: str) -> bool:
    return any(seg in IGNORE_DIRS for seg in re.split(r"[\\/]", path))


def _rel(file: str, root: str) -> str:
    """File path relative to the scan root, forward-slashed.

    Absolute paths make every table row hundreds of chars wide; stripping the
    common scan-root prefix keeps rows short so the markdown table renders, while
    the path stays unambiguous (it is relative to the scanned dir)."""
    try:
        rel = os.path.relpath(file, root)
    except ValueError:
        # Different drive on Windows: relpath raises, keep the absolute path.
        rel = file
    return rel.replace("\\", "/")


def catalog_rules() -> list[tuple[str, str]]:
    """(id, severity) for each rule in the catalog, read from rules/*.yml.

    Used so a clean result can list every rule that ran (and its severity),
    distinguishing 'no smells' from 'no rules loaded'. Severity defaults to
    'warning' to match ast-grep when a rule omits the field."""
    rules: list[tuple[str, str]] = []
    if not os.path.isdir(RULES_DIR):
        return rules

    for name in sorted(os.listdir(RULES_DIR)):
        if not name.endswith((".yml", ".yaml")):
            continue

        rule_id = ""
        severity = "warning"
        with open(os.path.join(RULES_DIR, name), "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("id:"):
                    rule_id = line.split(":", 1)[1].strip()
                elif line.startswith("severity:"):
                    severity = line.split(":", 1)[1].strip()

        if rule_id:
            rules.append((rule_id, severity))
    return rules


def print_rule_table(rows: list[tuple[str, str, int, list[str]]]) -> None:
    """Print ONE TABLE PER RULE: a heading carries the rule id, severity and count
    once, and a single-column table lists only the locations.

    Repeating the rule id and severity on every location row (the prior layout)
    wastes tokens when a rule has many hits. Hoisting them into a per-rule heading
    removes that repetition while keeping each section self-contained: the agent
    reads the heading for rule+severity, then every row underneath is a location for
    that rule. Narrow single-column rows always render (no viewport overflow).
    `rows` is already sorted; each is (rule_id, severity, count, locs)."""
    if not rows:
        return

    # Escape any pipe in a cell so it does not break the markdown column split.
    def cell(value: str) -> str:
        return value.replace("|", "\\|")

    for rule_id, severity, count, locs in rows:
        print(f"### {rule_id} ({severity}): {count}\n")
        print("| LOCATION |")
        print("| --- |")
        # A 0-finding (clean) rule has no locations: emit a single placeholder row.
        for loc in (locs or ["-"]):
            print(f"| {cell(loc)} |")
        print()


def print_rules_ran(ran: list[tuple[str, str]], cap: int = 30) -> None:
    """Print a one-line roster of every rule that ran this invocation.

    The findings table only lists rules that matched, so without this a reader
    cannot tell whether 1 of 2 rules ran or 1 of 200. Names are listed up to
    `cap`; beyond that only the count is shown to keep the line bounded as the
    catalog grows."""
    if not ran:
        return

    ids = [rid for rid, _ in sorted(ran)]
    if len(ids) <= cap:
        print(f"\nRan {len(ids)} rules: {', '.join(ids)}")
    else:
        print(f"\nRan {len(ids)} rules ({', '.join(ids[:cap])}, +{len(ids) - cap} more)")


def run_scan(path: str) -> list[dict]:
    """Run the whole catalog over `path`, return ast-grep's raw match list."""
    proc = subprocess.run(
        ["ast-grep", "scan", "-c", SGCONFIG, "--json=compact", path],
        capture_output=True, text=True,
    )
    if not proc.stdout.strip():
        # No matches, or a config error: surface stderr so a broken rule is visible.
        if proc.stderr.strip():
            sys.stderr.write(proc.stderr)
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit("error: could not parse ast-grep scan output.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the sniff-lint catalog and summarize findings.")
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--severity", help="only show this severity (error|warning|info|hint)")
    parser.add_argument("--rule", help="only show this rule id")
    parser.add_argument("--top-locs", type=int, default=0,
                        help="cap locations listed per rule (default: 0 = list every location)")
    args = parser.parse_args()

    _require_ast_grep()

    rules = catalog_rules()
    if not rules:
        print(f"No rules in the catalog ({RULES_DIR}). Add one with sniff-forge.")
        return

    matches = run_scan(args.path)
    matches = [m for m in matches if not _in_ignored_dir(m.get("file", ""))]

    # Group by rule id; track severity and sample locations.
    by_rule: dict[str, dict] = {}
    for m in matches:
        rule_id = m.get("ruleId", "(unknown)")
        if args.rule and rule_id != args.rule:
            continue
        sev = m.get("severity", "warning")
        if args.severity and sev != args.severity:
            continue

        entry = by_rule.setdefault(rule_id, {"severity": sev, "count": 0, "locs": []})
        entry["count"] += 1
        # top_locs == 0 means list every location so the agent can act on all of
        # them; a positive value caps the list.
        if args.top_locs <= 0 or len(entry["locs"]) < args.top_locs:
            line = m["range"]["start"]["line"] + 1
            entry["locs"].append(f"{_rel(m['file'], args.path)}:{line}")

    # Rules that actually ran this invocation = whole catalog minus any --rule /
    # --severity filter. Reported so the result names how many and which rules ran,
    # not just the ones that happened to match.
    ran = [
        (rid, sev)
        for rid, sev in rules
        if (not args.rule or rid == args.rule)
        and (not args.severity or sev == args.severity)
    ]

    if not by_rule:
        # Clean result: show every rule that ran as a 0-count table row so a pass
        # still reads as a real table.
        clean_rows = [(rid, sev, 0, []) for rid, sev in ran]
        clean_rows.sort(key=lambda r: (SEVERITY_ORDER.get(r[1], 9), r[0]))

        scope = ""
        if args.rule:
            scope = f" matching --rule {args.rule}"
        elif args.severity:
            scope = f" at --severity {args.severity}"
        print(f"sniff-lint: 0 findings{scope} across {len(ran)} rules in {args.path!r}\n")
        print_rule_table(clean_rows)
        print_rules_ran(ran)
        return

    sorted_rules = sorted(by_rule.items(),
                          key=lambda kv: (SEVERITY_ORDER.get(kv[1]["severity"], 9), -kv[1]["count"]))

    rows = [(rid, e["severity"], e["count"], e["locs"]) for rid, e in sorted_rules]

    total = sum(r[2] for r in rows)
    print(f"sniff-lint: {total} findings, {len(rows)} of {len(ran)} rules matched in {args.path!r}\n")

    print_rule_table(rows)
    print_rules_ran(ran)


if __name__ == "__main__":
    main()
