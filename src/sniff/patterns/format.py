#!/usr/bin/env python3
"""Run the sniff-patterns rule catalog and print a compact findings table.

One `ast-grep scan` pass loads every rule under sniff-patterns/rules/ and reports its
matches. This script folds that JSON into a small RULE / SEVERITY / COUNT /
TOP LOCATIONS table so the calling agent only ever sees the
summary, never the raw per-match JSON.

Usage:
    python format.py [DIR] [--severity error|warning|info|hint] [--rule ID] [--top-locs N]

DIR defaults to the current directory. Vendored/build dirs are skipped by the
shared ignore list; test files are NOT excluded here (a lint finding in a test is
still a finding).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SGCONFIG = os.path.join(HERE, "sgconfig.yml")
RULES_DIR = os.path.join(HERE, "rules")

# Same vendored/build dirs the harness ignores; kept local so this script has no
# import dependency on _ast-harness (it speaks ast-grep's scan JSON, not Match).
IGNORE_DIRS = {
    "node_modules", "dist", "build", "out", "coverage", ".git", ".nx",
    ".angular", ".next", "vendor", "target", "__pycache__", ".venv", "venv", ".claude",
}

# ast-grep severity ordering, worst first, for sorting the table.
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2, "hint": 3}


def _require_ast_grep() -> None:
    if not shutil.which("ast-grep"):
        sys.exit("error: ast-grep is not installed or not on PATH. See https://ast-grep.github.io")


def _in_ignored_dir(path: str) -> bool:
    return any(seg in IGNORE_DIRS for seg in re.split(r"[\\/]", path))


def _extra_ignore_patterns() -> list[str]:
    """Glob patterns from SNIFF_EXTRA_IGNORE (set by run.py from .sniff.toml's
    `[ignore] globs = "..."`), comma-separated. Empty when unset."""
    raw = os.environ.get("SNIFF_EXTRA_IGNORE", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _matches_extra_ignore(path: str, root: str, patterns: list[str]) -> bool:
    """True if `path` (relative to `root`) matches any SNIFF_EXTRA_IGNORE glob.

    Extends _in_ignored_dir's hardcoded vendored-dir list rather than replacing
    it, so both the fixed ignore list and a consumer's own .sniff.toml globs
    apply together."""
    if not patterns:
        return False
    rel = _rel(path, root)
    return any(fnmatch.fnmatch(rel, pat) for pat in patterns)


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


def local_rules_dir(scan_path: str) -> str:
    """Where consumer-local rules live for a given scan target: <scan_path>/.sniff/rules."""
    return os.path.join(scan_path, ".sniff", "rules")


def _read_rule_meta(path: str) -> tuple[str, str, str, str]:
    """(id, severity, message, language) from one rule yml, hand-parsed (no PyYAML dependency).

    Severity defaults to 'warning' to match ast-grep when a rule omits the field."""
    rule_id, severity, message, language = "", "warning", "", ""
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("id:"):
                rule_id = line.split(":", 1)[1].strip()
            elif line.startswith("severity:"):
                severity = line.split(":", 1)[1].strip()
            elif line.startswith("message:"):
                message = line.split(":", 1)[1].strip()
            elif line.startswith("language:"):
                language = line.split(":", 1)[1].strip()
    return rule_id, severity, message, language


def catalog_rules(scan_path: str | None = None) -> list[tuple[str, str, str, str, str]]:
    """(id, severity, message, origin, language) for every rule that would run on `scan_path`.

    origin is 'core' for this package's rules/*.yml, or 'local' for
    <scan_path>/.sniff/rules/*.yml. Local rules let a consumer repo add its own
    checks without touching the shared catalog. Used so a clean result can list
    every rule that ran (and its severity), distinguishing 'no smells' from 'no
    rules loaded'."""
    rules: list[tuple[str, str, str, str, str]] = []
    core_ids: set[str] = set()

    if os.path.isdir(RULES_DIR):
        for name in sorted(os.listdir(RULES_DIR)):
            if not name.endswith((".yml", ".yaml")):
                continue
            rule_id, severity, message, language = _read_rule_meta(os.path.join(RULES_DIR, name))
            if rule_id:
                rules.append((rule_id, severity, message, "core", language))
                core_ids.add(rule_id)

    if scan_path is not None:
        local_dir = local_rules_dir(scan_path)
        if os.path.isdir(local_dir):
            for name in sorted(os.listdir(local_dir)):
                if not name.endswith((".yml", ".yaml")):
                    continue
                rule_id, severity, message, language = _read_rule_meta(os.path.join(local_dir, name))
                if not rule_id:
                    print(f"warning: local rule {name} has no id:, skipped", file=sys.stderr)
                    continue
                if rule_id in core_ids:
                    print(f"warning: local rule {rule_id} shadows a core rule, local copy ignored",
                          file=sys.stderr)
                    continue
                rules.append((rule_id, severity, message, "local", language))

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
        if not locs:
            print("| (none) |")
        for loc in locs:
            print(f"| {cell(loc)} |")
        print()


def print_rules_ran(ran: list[tuple[str, str, str, str, str]], cap: int = 30) -> None:
    """Print a one-line roster of every rule that ran this invocation.

    The findings table only lists rules that matched, so without this a reader
    cannot tell whether 1 of 2 rules ran or 1 of 200. Names are listed up to
    `cap`; beyond that only the count is shown to keep the line bounded as the
    catalog grows."""
    if not ran:
        return

    ids = [rid for rid, *_rest in sorted(ran)]
    if len(ids) <= cap:
        print(f"\nRan {len(ids)} rules: {', '.join(ids)}")
    else:
        print(f"\nRan {len(ids)} rules ({', '.join(ids[:cap])}, +{len(ids) - cap} more)")


def print_list_rules(rules: list[tuple[str, str, str, str, str]]) -> None:
    """Print a catalog table grouped by language, one ### heading + RULE/SEVERITY/
    ORIGIN/MESSAGE table per language.

    Used by --list-rules so an agent can discover rule IDs and their intent
    without running a scan. ORIGIN ('core' vs 'local') tells the agent whether a
    rule comes from the shared catalog or a consumer-local .sniff/rules override.
    Grouping by language keeps a multi-language catalog (e.g. typescript + python)
    scannable instead of one long mixed table."""
    languages = sorted({language for *_rest, language in rules})
    for language in languages:
        print(f"### {language}\n")
        print("| RULE | SEVERITY | ORIGIN | MESSAGE |")
        print("| --- | --- | --- | --- |")
        group = [r for r in rules if r[4] == language]
        for rule_id, severity, message, origin, _language in sorted(
                group, key=lambda r: (SEVERITY_ORDER.get(r[1], 9), r[0])):
            # Escape pipes so the markdown table stays valid.
            safe_msg = message.replace("|", "\\|")
            print(f"| {rule_id} | {severity} | {origin} | {safe_msg} |")
        print()


def _yaml_single_quoted(path: str) -> str:
    """Format an absolute path as a single-quoted YAML scalar.

    YAML single-quoted strings do not interpret backslash as an escape (only
    a doubled quote escapes), so Windows paths must NOT be run through
    Python's repr(): repr() backslash-escapes each `\\`, which a YAML parser
    then reads back literally, corrupting the path. Forward-slashing sidesteps
    the whole issue since Windows accepts `/` as a path separator too."""
    return path.replace("\\", "/").replace("'", "''")


def run_scan(path: str) -> list[dict]:
    """Run the whole catalog over `path`, return ast-grep's raw match list.

    When `path` has a .sniff/rules/ dir, a temp sgconfig is built whose ruleDirs
    covers both the core catalog and the local dir, so one ast-grep pass reports
    core + local findings together."""
    config = SGCONFIG
    tmp = None
    local_dir = local_rules_dir(path)
    if os.path.isdir(local_dir):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8")
        tmp.write("ruleDirs:\n")
        tmp.write(f"  - '{_yaml_single_quoted(os.path.abspath(RULES_DIR))}'\n")
        tmp.write(f"  - '{_yaml_single_quoted(os.path.abspath(local_dir))}'\n")
        tmp.close()
        config = tmp.name

    try:
        proc = subprocess.run(
            ["ast-grep", "scan", "-c", config, "--json=compact", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    finally:
        if tmp:
            os.unlink(tmp.name)

    if not proc.stdout.strip():
        # No matches, or a config error: surface stderr so a broken rule is visible.
        if proc.stderr.strip():
            sys.stderr.write(proc.stderr)
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit("error: could not parse ast-grep scan output.")


def scan_multiline_single_comments(path: str) -> list[dict]:
    """Scan for block comments spanning multiple lines with only one content line.

    Pattern: `/** or /* followed by newline, one content line with `*`, then closing */
    Returns matches in ast-grep JSON format for integration with other findings."""
    matches = []
    # Regex: /\*\*? followed by newline, then content line, then newline, then */
    pattern = re.compile(
        r'/\*\*?\s*\n\s*\*\s*\S[^\n]*\n\s*\*/',
        re.MULTILINE
    )

    # Handle both direct file paths and directory paths
    paths_to_scan = []
    if os.path.isfile(path):
        paths_to_scan = [path]
    else:
        # Find .ts and .js files recursively
        for root, dirs, files in os.walk(path):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for fname in files:
                if fname.endswith(('.ts', '.js', '.tsx', '.jsx')):
                    paths_to_scan.append(os.path.join(root, fname))

    for fpath in paths_to_scan:
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except (IOError, OSError):
            continue

        for match in pattern.finditer(content):
            # Calculate line number from match position
            line_num = content[:match.start()].count('\n')
            matches.append({
                'file': fpath,
                'ruleId': 'no-multiline-single-comment',
                'severity': 'warning',
                'message': 'Block comment spans multiple lines with only one content line; use single-line syntax instead.',
                'range': {
                    'start': {'line': line_num, 'column': 0},
                    'end': {'line': line_num + 2, 'column': 0}
                }
            })

    return matches


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description="Run the sniff-patterns catalog and summarize findings.")
    parser.add_argument("path", nargs="?", default=".", metavar="DIR", help="directory to scan (default: .)")
    parser.add_argument("--severity", help="only show this severity (error|warning|info|hint)")
    parser.add_argument("--rule", help="only show this rule id")
    parser.add_argument("--top-locs", type=int, default=0,
                        help="cap locations listed per rule (default: 0 = list every location)")
    parser.add_argument("--list-rules", action="store_true",
                        help="print catalog of available rule IDs and exit")
    parser.add_argument("--disable", help="comma-separated rule ids to skip (e.g. from .sniff.toml [rules])")
    parser.add_argument("--severity-override", action="append", default=[], metavar="ID=LEVEL",
                        help="override a rule's severity (repeatable), e.g. no-console-log=error "
                             "(from .sniff.toml [rules])")
    args = parser.parse_args(argv)

    disabled = {r.strip() for r in (args.disable or "").split(",") if r.strip()}

    # rule id -> severity, from .sniff.toml [rules] via run.py. Rewrites a rule's
    # reported severity (and its --severity filtering) without touching the rule yml.
    severity_overrides: dict[str, str] = {}
    for item in args.severity_override:
        if "=" in item:
            rid, level = item.split("=", 1)
            severity_overrides[rid.strip()] = level.strip()

    if args.list_rules:
        rules = catalog_rules(args.path)
        if not rules:
            print(f"No rules in the catalog ({RULES_DIR}). Add one with sniff-create.")
        else:
            print_list_rules(rules)
        return 0

    _require_ast_grep()

    rules = catalog_rules(args.path)
    if not rules:
        print(f"No rules in the catalog ({RULES_DIR}). Add one with sniff-create.")
        return 0

    extra_ignores = _extra_ignore_patterns()

    def _ignored(file: str) -> bool:
        return _in_ignored_dir(file) or _matches_extra_ignore(file, args.path, extra_ignores)

    matches = run_scan(args.path)
    matches = [m for m in matches if not _ignored(m.get("file", ""))]

    # Add custom Python-based detectors (for rules that can't be expressed in ast-grep)
    custom_matches = scan_multiline_single_comments(args.path)
    custom_matches = [m for m in custom_matches if not _ignored(m.get("file", ""))]
    matches.extend(custom_matches)

    # Group by rule id; track severity and sample locations.
    by_rule: dict[str, dict] = {}
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
        (r[0], severity_overrides.get(r[0], r[1]), *r[2:])
        for r in rules
        if r[0] not in disabled
        and (not args.rule or r[0] == args.rule)
        and (not args.severity or severity_overrides.get(r[0], r[1]) == args.severity)
    ]

    if not by_rule:
        scope = ""
        if args.rule:
            scope = f" matching --rule {args.rule}"
        elif args.severity:
            scope = f" at --severity {args.severity}"
        print(f"sniff-patterns: 0 findings{scope} across {len(ran)} rules in {args.path!r}")
        print_rules_ran(ran)
        return 0

    sorted_rules = sorted(by_rule.items(),
                          key=lambda kv: (SEVERITY_ORDER.get(kv[1]["severity"], 9), -kv[1]["count"]))

    rows = [(rid, e["severity"], e["count"], e["locs"]) for rid, e in sorted_rules]

    total = sum(r[2] for r in rows)
    print(f"sniff-patterns: {total} findings, {len(rows)} of {len(ran)} rules matched in {args.path!r}\n")

    print_rule_table(rows)
    print_rules_ran(ran)
    return 0


if __name__ == "__main__":
    sys.exit(main())
