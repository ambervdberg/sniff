#!/usr/bin/env python3
"""Run the sniff-lint rule catalog and print a compact findings table.

One `ast-grep scan` pass loads every rule under sniff-lint/rules/ and reports its
matches. This script folds that JSON into a small RULE / SEVERITY / COUNT /
TOP LOCATIONS table so the calling agent (ideally a subagent) only ever sees the
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


def catalog_rule_ids() -> list[str]:
    """Rule ids in the catalog, read from the `id:` line of each rules/*.yml.

    Used so a clean result can say how many rules ran, distinguishing 'no smells'
    from 'no rules loaded'."""
    ids: list[str] = []
    if not os.path.isdir(RULES_DIR):
        return ids

    for name in sorted(os.listdir(RULES_DIR)):
        if not name.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(RULES_DIR, name), "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("id:"):
                    ids.append(line.split(":", 1)[1].strip())
                    break
    return ids


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
    parser.add_argument("--top-locs", type=int, default=3, help="locations to list per rule (default: 3)")
    args = parser.parse_args()

    _require_ast_grep()

    rule_ids = catalog_rule_ids()
    if not rule_ids:
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
        if len(entry["locs"]) < args.top_locs:
            line = m["range"]["start"]["line"] + 1
            entry["locs"].append(f"{m['file'].replace(chr(92), '/')}:{line}")

    if not by_rule:
        scope = ""
        if args.rule:
            scope = f" matching --rule {args.rule}"
        elif args.severity:
            scope = f" at --severity {args.severity}"
        print(f"Clean: 0 findings{scope}. Ran {len(rule_ids)} rules "
              f"({', '.join(rule_ids)}) over {args.path!r}.")
        return

    rows = sorted(by_rule.items(),
                  key=lambda kv: (SEVERITY_ORDER.get(kv[1]["severity"], 9), -kv[1]["count"]))

    total = sum(e["count"] for _, e in rows)
    print(f"sniff-lint: {total} findings across {len(rows)} rules in {args.path!r}\n")

    rule_w = max(len("RULE"), *(len(r) for r, _ in rows))
    sev_w = max(len("SEVERITY"), *(len(e["severity"]) for _, e in rows))

    print(f"{'RULE':<{rule_w}}  {'SEVERITY':<{sev_w}}  {'COUNT':>5}  TOP LOCATIONS")
    for rule_id, e in rows:
        locs = ", ".join(e["locs"])
        print(f"{rule_id:<{rule_w}}  {e['severity']:<{sev_w}}  {e['count']:>5}  {locs}")


if __name__ == "__main__":
    main()
