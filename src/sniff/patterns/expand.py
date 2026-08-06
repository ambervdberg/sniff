#!/usr/bin/env python3
"""Rule catalog discovery, plus expanding one multi-language rule into per-language copies.

A rule file declares one `language:`, because that is all ast-grep accepts. Rules
whose syntax exists in more than one language name the others in ast-grep's
`metadata:` block, which ast-grep itself ignores:

    metadata:
      languages: [tsx, javascript]

The rule file therefore stays the single source of truth for both what it matches
and where it runs, and `_write_language_copies` expands it into one copy per
language for `scan.run_scan` to point ast-grep at.
"""

from __future__ import annotations

import os
import sys
from typing import Iterator

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_DIR = os.path.join(HERE, "rules")


def local_rules_dir(scan_path: str) -> str:
    """Where consumer-local rules live for a given scan target: <scan_path>/.sniff/rules."""
    return os.path.join(scan_path, ".sniff", "rules")


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


def catalog_rules(scan_path: "str | None" = None) -> list[tuple[str, str, str, str, str]]:
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


# Separates a rule id from the language a generated copy runs on. Only ever seen
# inside the temp expansion dir; `scan.run_scan` maps the id back before any
# finding is formatted, so neither the user nor `.sniff.toml` ever meets a
# suffixed id.
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
