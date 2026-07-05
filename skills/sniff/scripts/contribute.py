#!/usr/bin/env python3
"""sniff contribute <rule-id>: move a proven local rule into the sniff plugin repo.

Backend 1 (maintainer): SNIFF_REPO env var or ~/.sniff/config.toml points at a
local sniff checkout; the rule + fixtures are copied there on a new branch and
the fixture tests run. Backend 2 (external user): gh fork + branch + PR.
Guards: the rule must exist locally, have fixtures, and not collide with a core
rule id."""

from __future__ import annotations

import os
import re
import sys

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".sniff", "config.toml")


def resolve_checkout() -> "str | None":
    env = os.environ.get("SNIFF_REPO")
    if env:
        return env
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    match = re.search(r'(?m)^repo\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else None


def local_paths(rule_id: str, project_dir: str) -> "tuple[str, str]":
    base = os.path.join(project_dir, ".sniff")
    return (os.path.join(base, "rules", rule_id + ".yml"),
            os.path.join(base, "rule-tests", rule_id + ".yml"))


def check_guards(rule_id: str, project_dir: str, core_ids: "set[str]") -> "list[str]":
    errors = []
    rule_path, fixture_path = local_paths(rule_id, project_dir)
    if not os.path.isfile(rule_path):
        errors.append(f"no local rule {rule_id!r} at {rule_path}")
    if not os.path.isfile(fixture_path):
        errors.append(f"rule {rule_id!r} has no fixture file at {fixture_path}; "
                      f"add valid/invalid snippets before contributing")
    if rule_id in core_ids:
        errors.append(f"rule id {rule_id!r} collides with a core catalog rule")
    return errors


def run_contribute(rule_id: str, project_dir: str, dry_run: bool = False) -> int:
    core_ids = _core_rule_ids()
    errors = check_guards(rule_id, project_dir, core_ids)
    if errors:
        for err in errors:
            print(f"error: {err}", file=sys.stderr)
        return 1

    checkout = resolve_checkout()
    if dry_run:
        backend = f"checkout {checkout}" if checkout else "gh fork + PR"
        print(f"dry-run: would contribute {rule_id!r} via {backend}")
        return 0
    if checkout:
        return _contribute_to_checkout(rule_id, project_dir, checkout)   # Task 8
    return _contribute_via_gh(rule_id, project_dir)                       # Task 9


def _core_rule_ids() -> "set[str]":
    """Rule ids shipped in this install's catalog."""
    here = os.path.dirname(os.path.abspath(__file__))
    rules_dir = os.path.normpath(os.path.join(here, "..", "..", "sniff-patterns", "rules"))
    return {os.path.splitext(n)[0] for n in os.listdir(rules_dir) if n.endswith((".yml", ".yaml"))}


def _contribute_to_checkout(rule_id: str, project_dir: str, checkout: str) -> int:
    print("error: checkout backend not implemented yet", file=sys.stderr)   # Task 8
    return 1


def _contribute_via_gh(rule_id: str, project_dir: str) -> int:
    print("error: gh backend not implemented yet", file=sys.stderr)         # Task 9
    return 1
