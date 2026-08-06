#!/usr/bin/env python3
"""Run the sniff-patterns catalog against a scan target: one ast-grep pass plus
a small Python-only detector ast-grep cannot express.

`run_scan` expands multi-language rules into a temp dir (see `expand.py`),
points a temp sgconfig at core rules, that expansion, and any repo-local
`.sniff/rules/`, then shells out to `ast-grep scan` once. `scan_multiline_single_comments`
covers the one rule (`no-multiline-single-comment`) that needs a plain regex
over file text instead of an AST pattern; its output is shaped to match
ast-grep's own JSON so `format.py` can merge both lists without caring which
one produced a match.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from sniff.patterns.expand import RULES_DIR, local_rules_dir, _write_language_copies
from sniff.patterns.paths import IGNORE_DIRS

SGCONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sgconfig.yml")


def find_ast_grep() -> str | None:
    """Resolve the ast-grep binary, falling back to the interpreter's own bin dir.

    Mirrors harness.find_ast_grep on purpose: this script is also run standalone, so it
    keeps its no-import-dependency on the harness. `pip install ast-grep-cli` drops the
    `ast-grep` binary next to whatever interpreter ran the install (Scripts\\ on Windows,
    bin/ elsewhere), which shutil.which only sees if that directory is on PATH. It is not
    for `uv tool install sniff-smells` (only the `sniff` shim gets exposed) or for an
    agent invoking sniff by absolute path. sys.executable is reliable in both cases."""
    found = shutil.which("ast-grep")
    if found:
        return found
    exe_name = "ast-grep.exe" if os.name == "nt" else "ast-grep"
    sibling = os.path.join(os.path.dirname(sys.executable), exe_name)
    return sibling if os.path.isfile(sibling) else None


def ast_grep_exe() -> str:
    """Absolute path to ast-grep, resolving Windows .cmd/.exe shims; bare name if not found.

    Mirrors harness.ast_grep_exe on purpose: this script is also run standalone, so it
    keeps its no-import-dependency on the harness. Windows CreateProcess ignores PATHEXT
    for a bare argv[0], so the npm-installed `ast-grep.cmd` shim would raise WinError 2.
    find_ast_grep also catches the interpreter-sibling case pip installs use; the bare
    name is the last-resort fallback so a subprocess call still gets a name to fail on."""
    return find_ast_grep() or "ast-grep"


def _require_ast_grep() -> None:
    if find_ast_grep() is None:
        sys.exit("error: ast-grep is not installed or not on PATH. Install it with: pip install ast-grep-cli")


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
