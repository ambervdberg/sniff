#!/usr/bin/env python3
"""sniff test-rules: run the catalog's ast-grep fixture tests and enforce coverage.

Two checks: (1) every ast-grep rule in src/sniff/patterns/rules/ has a
rule-tests/<id>.yml fixture file, (2) `ast-grep test` passes. Python-implemented
rules (no ast-grep yml semantics, see PYTHON_RULES) are exempt from (1)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from sniff.harness import ast_grep_exe

# Rules implemented in Python inside format.py, not as ast-grep rules.
PYTHON_RULES = {"no-multiline-single-comment"}


def _patterns_dir(repo_root: str) -> str:
    """Directory holding this repo_root's rules/, rule-tests/, and sgconfig.yml."""
    return os.path.join(repo_root, "src", "sniff", "patterns")


def _rules_dir(repo_root: str) -> str:
    """Directory holding this repo_root's core rule ymls."""
    return os.path.join(_patterns_dir(repo_root), "rules")


def rules_missing_tests(repo_root: str) -> list[str]:
    """Rule ids in rules/ that lack a rule-tests/<id>.yml, excluding PYTHON_RULES."""
    base = _patterns_dir(repo_root)
    rules_dir = _rules_dir(repo_root)
    tests_dir = os.path.join(base, "rule-tests")
    missing = []
    for name in sorted(os.listdir(rules_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        rule_id = os.path.splitext(name)[0]
        if rule_id in PYTHON_RULES:
            continue
        if not os.path.isfile(os.path.join(tests_dir, rule_id + ".yml")):
            missing.append(rule_id)
    return missing


def run_test_rules(repo_root: str) -> int:
    """Coverage check + `ast-grep test`. Prints results, returns 0/1."""
    if not shutil.which("ast-grep"):
        print("FAIL ast-grep not on PATH", file=sys.stderr)
        return 1

    # test-rules reads the catalog sources, which an installed wheel does not
    # ship; without this guard os.listdir below raises FileNotFoundError at the
    # user instead of explaining what is wrong.
    rules_path = _rules_dir(repo_root)
    if not os.path.isdir(rules_path):
        print(f"FAIL test-rules runs from a sniff repo checkout; "
              f"rules directory not found at {rules_path}", file=sys.stderr)
        return 1

    missing = rules_missing_tests(repo_root)
    for rule_id in missing:
        print(f"FAIL rule without fixtures: {rule_id} (add rule-tests/{rule_id}.yml)")

    sgconfig = os.path.join(_patterns_dir(repo_root), "sgconfig.yml")
    proc = subprocess.run(
        [ast_grep_exe(), "test", "-c", sgconfig, "--skip-snapshot-tests"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print(proc.stdout.strip() or proc.stderr.strip())
    ok = not missing and proc.returncode == 0
    print("PASS all rule fixtures" if ok else "FAIL rule fixtures")
    return 0 if ok else 1
