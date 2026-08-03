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
from typing import Iterator

from sniff import harness as h

HERE = os.path.dirname(os.path.abspath(__file__))
SGCONFIG = os.path.join(HERE, "sgconfig.yml")
RULES_DIR = os.path.join(HERE, "rules")

# Taken from the harness rather than copied. The copy that used to live here had
# already drifted: it never learned about .astro, .svelte-kit, .nuxt or .turbo, so
# pattern rules reported build output that every other detector skipped.
IGNORE_DIRS = h.IGNORE_DIRS

# ast-grep severity ordering, worst first, for sorting the table.
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2, "hint": 3}

# How many locations one rule may list before the rest collapse into a "+N more"
# row. A single noisy rule used to print every hit (118 rows for py-print-statement
# on this repo), which swamps the caller's context and defeats the point of a
# summary table. The heading still carries the true total, and `--top-locs 0`
# restores the full list when an agent really wants to act on every hit.
DEFAULT_TOP_LOCS = 10


def ast_grep_exe() -> str:
    """Absolute path to ast-grep, resolving Windows .cmd/.exe shims; bare name if not found.

    Mirrors harness.ast_grep_exe on purpose: this script is also run standalone, so it
    keeps its no-import-dependency on the harness. Windows CreateProcess ignores PATHEXT
    for a bare argv[0], so the npm-installed `ast-grep.cmd` shim would raise WinError 2."""
    return shutil.which("ast-grep") or "ast-grep"


def _require_ast_grep() -> None:
    if not shutil.which("ast-grep"):
        sys.exit("error: ast-grep is not installed or not on PATH. See https://ast-grep.github.io")


def _in_ignored_dir(path: str, root: "str | None" = None) -> bool:
    """True if a path segment at or below `root` is a vendored/build directory.

    Segments above the scan root do not count: a checkout can live under a parent
    named `build`, `out`, `vendor`, or `.claude` (where Claude Code puts its
    worktrees), and matching those would drop every finding in the repo. Since an
    empty result looks exactly like a clean one, that failure reports as "no
    smells" rather than as an error. Mirrors harness._in_ignored_dir."""
    scoped = _rel(path, root) if root is not None else path
    return any(seg in IGNORE_DIRS for seg in re.split(r"[\\/]", scoped))


def _extra_ignore_patterns(extra_ignores: "list[str] | None" = None) -> list[str]:
    """Glob patterns to exclude on top of the fixed vendored-dir list.

    `extra_ignores` is the parsed `--extra-ignore` args cli.py folds in from
    `.sniff.toml`'s `[ignore] globs = "..."`; when given (even empty), it wins.
    Only when it is absent (None) does this fall back to the SNIFF_EXTRA_IGNORE
    env var, which cli.py sets around subprocess/external detectors. Mirrors
    harness._extra_ignore_patterns so both engines resolve ignores identically."""
    if extra_ignores is not None:
        return [p.strip() for p in extra_ignores if p.strip()]
    raw = os.environ.get("SNIFF_EXTRA_IGNORE", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _matches_extra_ignore(path: str, root: str, patterns: list[str]) -> bool:
    """True if `path` (relative to `root`) matches any extra-ignore glob.

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


# A rule file declares one `language:`, because that is all ast-grep accepts. Rules
# whose syntax exists in more than one language name the others in ast-grep's
# `metadata:` block, which ast-grep itself ignores:
#
#     metadata:
#       languages: [tsx, javascript]
#
# The rule file therefore stays the single source of truth for both what it matches
# and where it runs, and the scan expands it into one copy per language.
def _read_extra_languages(path: str) -> list[str]:
    """The languages listed under `metadata: languages:` in one rule yml.

    Hand-parsed like the rest of the rule metadata (the package stays
    dependency-free), so it reads the one nested key it needs and ignores the
    rest of the block."""
    in_metadata = False

    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith((" ", "\t")):
                in_metadata = line.startswith("metadata:")
                continue
            if in_metadata and line.strip().startswith("languages:"):
                listed = line.split(":", 1)[1].strip().strip("[]")
                return [lang.strip().strip("'\"") for lang in listed.split(",") if lang.strip()]

    return []


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

    for path, origin in _iter_rule_files(scan_path):
        rule_id, severity, message, language = _read_rule_meta(path)

        if origin == "core":
            if rule_id:
                rules.append((rule_id, severity, message, "core", language))
                core_ids.add(rule_id)
            continue

        if not rule_id:
            print(f"warning: local rule {os.path.basename(path)} has no id:, skipped", file=sys.stderr)
            continue
        if rule_id in core_ids:
            print(f"warning: local rule {rule_id} shadows a core rule, local copy ignored",
                  file=sys.stderr)
            continue
        rules.append((rule_id, severity, message, "local", language))

    return rules


def _iter_rule_files(scan_path: "str | None" = None) -> "Iterator[tuple[str, str]]":
    """(path, origin) for every rule yml that would run on `scan_path`, core first.

    Core before local so a local rule can be spotted as shadowing one."""
    if os.path.isdir(RULES_DIR):
        for name in sorted(os.listdir(RULES_DIR)):
            if name.endswith((".yml", ".yaml")):
                yield os.path.join(RULES_DIR, name), "core"

    if scan_path is None:
        return

    local_dir = local_rules_dir(scan_path)
    if os.path.isdir(local_dir):
        for name in sorted(os.listdir(local_dir)):
            if name.endswith((".yml", ".yaml")):
                yield os.path.join(local_dir, name), "local"


def rule_languages(scan_path: "str | None" = None) -> "dict[str, list[str]]":
    """Every language each rule runs on, its declared one first.

    Separate from `catalog_rules` so the row shape callers unpack stays put."""
    languages: dict[str, list[str]] = {}
    core_ids: set[str] = set()

    for path, origin in _iter_rule_files(scan_path):
        rule_id, _severity, _message, language = _read_rule_meta(path)
        if not rule_id or (origin == "local" and rule_id in core_ids):
            continue
        if origin == "core":
            core_ids.add(rule_id)

        extra = [lang for lang in _read_extra_languages(path) if lang != language]
        languages[rule_id] = [language, *extra] if language else extra

    return languages


def print_rule_table(rows: list[tuple[str, str, int, list[str]]]) -> None:
    """Print ONE TABLE PER RULE: a heading carries the rule id, severity and count
    once, and a single-column table lists only the locations.

    Repeating the rule id and severity on every location row (the prior layout)
    wastes tokens when a rule has many hits. Hoisting them into a per-rule heading
    removes that repetition while keeping each section self-contained: the agent
    reads the heading for rule+severity, then every row underneath is a location for
    that rule. Narrow single-column rows always render (no viewport overflow).
    `rows` is already sorted worst-severity first; each is
    (rule_id, severity, count, locs), where `count` is the true total and `locs`
    may be a --top-locs-capped prefix of it."""
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

        # The list is capped by --top-locs, so say how many hits are not shown.
        # Without this row the table silently reads as the complete set even
        # though the heading count disagrees with the number of rows.
        hidden = count - len(locs)
        if hidden > 0:
            print(f"| +{hidden} more (raise --top-locs to list them) |")
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


def print_list_rules(rules: list[tuple[str, str, str, str, str]],
                     scan_path: "str | None" = None) -> None:
    """Print a catalog table grouped by language, one ### heading + RULE/SEVERITY/
    ORIGIN/MESSAGE table per language.

    Used by --list-rules so an agent can discover rule IDs and their intent
    without running a scan. ORIGIN ('core' vs 'local') tells the agent whether a
    rule comes from the shared catalog or a consumer-local .sniff/rules override.
    Grouping by language keeps a multi-language catalog (e.g. typescript + python)
    scannable instead of one long mixed table."""
    also = rule_languages(scan_path)
    languages = sorted({language for *_rest, language in rules})
    for language in languages:
        print(f"### {language}\n")
        print("| RULE | SEVERITY | ORIGIN | ALSO RUNS ON | MESSAGE |")
        print("| --- | --- | --- | --- | --- |")
        group = [r for r in rules if r[4] == language]
        for rule_id, severity, message, origin, _language in sorted(
                group, key=lambda r: (SEVERITY_ORDER.get(r[1], 9), r[0])):
            extra = ", ".join(lang for lang in also.get(rule_id, []) if lang != language) or "-"
            # Escape pipes so the markdown table stays valid.
            safe_msg = message.replace("|", "\\|")
            print(f"| {rule_id} | {severity} | {origin} | {extra} | {safe_msg} |")
        print()


def render_catalog_table(rules: list[tuple[str, str, str, str, str]]) -> str:
    """The rule catalog as one markdown table per language, worst severity first.

    Half the catalog cannot apply to any one reader, so the language is a heading
    rather than a column: it splits the list before the reader has to filter it.
    Severity leads each table so the ordering inside a block is visible instead of
    having to be inferred. The CLI's --list-rules view has the same shape and adds
    an ORIGIN column, which only matters once a repo has local rules."""
    also = rule_languages()
    lines: list[str] = []

    for language in sorted({language for *_rest, language in rules}):
        lines.append(f"### {language}\n")
        lines.append("| SEVERITY | RULE | ALSO RUNS ON | MESSAGE |")
        lines.append("| --- | --- | --- | --- |")

        group = [r for r in rules if r[4] == language]
        for rule_id, severity, message, _origin, _language in sorted(
                group, key=lambda r: (SEVERITY_ORDER.get(r[1], 9), r[0])):
            extra = ", ".join(lang for lang in also.get(rule_id, []) if lang != language) or "-"
            # Escape pipes so the markdown table stays valid.
            safe_msg = _unquoted(message).replace("|", "\\|")
            lines.append(f"| {severity} | {rule_id} | {extra} | {safe_msg} |")

        lines.append("")

    return "\n".join(lines).strip()


def _unquoted(message: str) -> str:
    """Drop the quotes a YAML `message:` scalar carries, if it has a matching pair.

    The rule files quote their messages; a docs table reading `"Bare except: ..."`
    with the quotes still on looks like the quotes are part of the message."""
    text = message.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _yaml_single_quoted(path: str) -> str:
    """Format an absolute path as a single-quoted YAML scalar.

    YAML single-quoted strings do not interpret backslash as an escape (only
    a doubled quote escapes), so Windows paths must NOT be run through
    Python's repr(): repr() backslash-escapes each `\\`, which a YAML parser
    then reads back literally, corrupting the path. Forward-slashing sidesteps
    the whole issue since Windows accepts `/` as a path separator too."""
    return path.replace("\\", "/").replace("'", "''")


# Separates a rule id from the language a generated copy runs on. Only ever seen
# inside the temp expansion dir; `run_scan` maps the id back before any finding is
# formatted, so neither the user nor `.sniff.toml` ever meets a suffixed id.
_LANG_COPY_SEPARATOR = "--lang-"


def _write_language_copies(rules_dir: str, out_dir: str) -> dict[str, str]:
    """Copy each multi-language rule in `rules_dir` once per extra language.

    ast-grep rejects two rules sharing an id, so every copy needs its own; the
    returned map translates those generated ids back to the real one."""
    generated: dict[str, str] = {}

    for name in sorted(os.listdir(rules_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue

        path = os.path.join(rules_dir, name)
        rule_id, _severity, _message, language = _read_rule_meta(path)
        if not rule_id:
            continue

        for extra in _read_extra_languages(path):
            if extra == language:
                continue

            copy_id = f"{rule_id}{_LANG_COPY_SEPARATOR}{extra}"
            with open(path, "r", encoding="utf-8") as fh:
                body = fh.read()
            body = body.replace(f"id: {rule_id}", f"id: {copy_id}", 1)
            body = body.replace(f"language: {language}", f"language: {extra}", 1)

            with open(os.path.join(out_dir, f"{copy_id}.yml"), "w", encoding="utf-8") as fh:
                fh.write(body)
            generated[copy_id] = rule_id

    return generated


def run_scan(path: str) -> list[dict]:
    """Run the whole catalog over `path`, return ast-grep's raw match list.

    Rules that declare extra languages are expanded into per-language copies in a
    temp dir first, and a temp sgconfig points ast-grep at the core catalog, that
    expansion, and `path`'s own .sniff/rules/ when it has one. One pass, so core,
    local and per-language findings arrive together."""
    rule_dirs = [os.path.abspath(RULES_DIR)]
    local_dir = local_rules_dir(path)
    if os.path.isdir(local_dir):
        rule_dirs.append(os.path.abspath(local_dir))

    expansion = tempfile.mkdtemp(prefix="sniff-rules-")
    generated: dict[str, str] = {}
    for rules_dir in list(rule_dirs):
        generated.update(_write_language_copies(rules_dir, expansion))
    if generated:
        rule_dirs.append(expansion)

    config = SGCONFIG
    tmp = None
    if rule_dirs != [os.path.abspath(RULES_DIR)]:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8")
        tmp.write("ruleDirs:\n")
        for rules_dir in rule_dirs:
            tmp.write(f"  - '{_yaml_single_quoted(rules_dir)}'\n")
        tmp.close()
        config = tmp.name

    try:
        proc = subprocess.run(
            [ast_grep_exe(), "scan", "-c", config, "--json=compact", path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    finally:
        if tmp:
            os.unlink(tmp.name)
        shutil.rmtree(expansion, ignore_errors=True)

    if not proc.stdout.strip():
        # No matches, or a config error: surface stderr so a broken rule is visible.
        if proc.stderr.strip():
            sys.stderr.write(proc.stderr)
        return []
    try:
        matches = json.loads(proc.stdout)
    except json.JSONDecodeError:
        sys.exit("error: could not parse ast-grep scan output.")

    for match in matches:
        rule_id = match.get("ruleId", "")
        if rule_id in generated:
            match["ruleId"] = generated[rule_id]

    return matches


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
    parser.add_argument("--top-locs", type=int, default=DEFAULT_TOP_LOCS,
                        help=f"cap locations listed per rule (default: {DEFAULT_TOP_LOCS}; "
                             "0 = list every location)")
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
    args = parser.parse_args(argv)

    disabled = {r.strip() for r in (args.disable or "").split(",") if r.strip()}

    # rule id -> severity, from .sniff.toml [rules] via cli.py. Rewrites a rule's
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
            print_list_rules(rules, args.path)
        return 0

    _require_ast_grep()

    rules = catalog_rules(args.path)
    if not rules:
        print(f"No rules in the catalog ({RULES_DIR}). Add one with sniff-create.")
        return 0

    extra_ignores = _extra_ignore_patterns(args.extra_ignore)

    def _ignored(file: str) -> bool:
        # Test code is skipped by default, matching every other detector. A `!`
        # in a spec or an `as any` in a mock is not work anyone is going to do:
        # on excalidraw that was 57% of no-non-null-assertion's findings.
        if not args.include_tests and h.is_test_file(file):
            return True
        return _in_ignored_dir(file, args.path) or _matches_extra_ignore(file, args.path, extra_ignores)

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
        # `count` tracks every hit even once the location list stops growing, so
        # the heading and the "+N more" row always report the true total.
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
    tests = "tests included" if args.include_tests else "tests excluded"
    print(f"sniff-patterns: {total} findings, {len(rows)} of {len(ran)} rules matched "
          f"in {args.path!r} ({tests})\n")

    print_rule_table(rows)
    print_rules_ran(ran)
    return 0


if __name__ == "__main__":
    sys.exit(main())
