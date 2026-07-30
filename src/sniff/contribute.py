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
import shutil
import subprocess
import sys
import tempfile

from sniff import test_rules

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".sniff", "config.toml")
UPSTREAM = "ambervdberg/sniff"


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
    rules_dir = os.path.normpath(os.path.join(here, "..", "..", "skills", "sniff-patterns", "rules"))
    return {os.path.splitext(n)[0] for n in os.listdir(rules_dir) if n.endswith((".yml", ".yaml"))}


def _contribute_to_checkout(rule_id: str, project_dir: str, checkout: str) -> int:
    patterns = os.path.join(checkout, "skills", "sniff-patterns")
    if not os.path.isdir(patterns):
        print(f"error: {checkout!r} does not look like a sniff checkout", file=sys.stderr)
        return 1

    branch = f"rule/{rule_id}"
    if subprocess.run(["git", "-C", checkout, "checkout", "-b", branch]).returncode != 0:
        print(f"error: could not create branch {branch} (dirty checkout?)", file=sys.stderr)
        return 1

    rule_src, fixture_src = local_paths(rule_id, project_dir)
    shutil.copy2(rule_src, os.path.join(patterns, "rules", rule_id + ".yml"))
    shutil.copy2(fixture_src, os.path.join(patterns, "rule-tests", rule_id + ".yml"))
    subprocess.run(["git", "-C", checkout, "add", "skills/sniff-patterns"], check=False)

    if test_rules.run_test_rules(checkout) != 0:
        print("error: fixture tests failed in the checkout; fix before PR", file=sys.stderr)
        return 1

    print(f"sniff: {rule_id} staged on branch {branch!r} in {checkout}")
    print("next: review, commit, and open a PR from that branch")
    return 0


def _pr_body(rule_id: str, rule_path: str, fixture_path: str) -> str:
    with open(rule_path, "r", encoding="utf-8") as fh:
        rule_text = fh.read()
    with open(fixture_path, "r", encoding="utf-8") as fh:
        fixture_text = fh.read()
    return (f"New pattern rule `{rule_id}` promoted from a consumer repo.\n\n"
            f"Rule:\n```yaml\n{rule_text}```\n\nFixtures:\n```yaml\n{fixture_text}```\n")


def _contribute_via_gh(rule_id: str, project_dir: str) -> int:
    if not shutil.which("gh"):
        print("error: no local checkout configured (SNIFF_REPO or ~/.sniff/config.toml) "
              "and gh CLI not found; install gh or configure a checkout", file=sys.stderr)
        return 1

    rule_src, fixture_src = local_paths(rule_id, project_dir)
    workdir = tempfile.mkdtemp(prefix="sniff-contribute-")
    clone = os.path.join(workdir, "sniff")
    steps = [
        ["gh", "repo", "fork", UPSTREAM, "--clone", "--", clone],
        ["git", "-C", clone, "checkout", "-b", f"rule/{rule_id}"],
    ]
    for cmd in steps:
        if subprocess.run(cmd).returncode != 0:
            print(f"error: step failed: {' '.join(cmd)}", file=sys.stderr)
            return 1

    patterns = os.path.join(clone, "skills", "sniff-patterns")
    os.makedirs(os.path.join(patterns, "rule-tests"), exist_ok=True)
    shutil.copy2(rule_src, os.path.join(patterns, "rules", rule_id + ".yml"))
    shutil.copy2(fixture_src, os.path.join(patterns, "rule-tests", rule_id + ".yml"))

    body = _pr_body(rule_id, rule_src, fixture_src)
    steps = [
        ["git", "-C", clone, "add", "skills/sniff-patterns"],
        ["git", "-C", clone, "commit", "-m", f"feat: add {rule_id} pattern rule"],
        ["git", "-C", clone, "push", "-u", "origin", f"rule/{rule_id}"],
        ["gh", "pr", "create", "--repo", UPSTREAM, "--title", f"feat: add {rule_id} pattern rule",
         "--body", body],
    ]
    for cmd in steps:
        if subprocess.run(cmd, cwd=clone).returncode != 0:
            print(f"error: step failed: {' '.join(cmd[:4])} ...", file=sys.stderr)
            return 1
    print(f"sniff: PR opened for {rule_id}")
    return 0
