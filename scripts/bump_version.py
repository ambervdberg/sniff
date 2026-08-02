#!/usr/bin/env python3
"""Bump the version in pyproject.toml, .claude-plugin/plugin.json,
.codex-plugin/plugin.json, and every plugin entry in .claude-plugin/marketplace.json
in lockstep, so `sniff doctor`'s drift check stays green.

Usage: python scripts/bump_version.py <new-version>"""

from __future__ import annotations

import json
import os
import re
import sys

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _write_json(path: str, data: dict) -> None:
    """Write JSON back with the repo's house style: 2-space indent, trailing newline."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def bump(root: str, version: str) -> list[str]:
    """Rewrite the version in every file that declares one, return the paths touched."""
    touched = []

    pyproject_path = os.path.join(root, "pyproject.toml")
    with open(pyproject_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    text = re.sub(r'(?m)^version\s*=\s*"[^"]+"', f'version = "{version}"', text)
    with open(pyproject_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    touched.append(pyproject_path)

    for plugin_dir in (".claude-plugin", ".codex-plugin"):
        plugin_path = os.path.join(root, plugin_dir, "plugin.json")
        with open(plugin_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["version"] = version
        _write_json(plugin_path, data)
        touched.append(plugin_path)

    # The marketplace entry version is ignored at install time (plugin.json wins),
    # but Claude Code warns loudly when the two disagree, so keep it in lockstep too.
    marketplace_path = os.path.join(root, ".claude-plugin", "marketplace.json")
    with open(marketplace_path, "r", encoding="utf-8") as fh:
        marketplace = json.load(fh)
    for entry in marketplace.get("plugins", []):
        entry["version"] = version
    _write_json(marketplace_path, marketplace)
    touched.append(marketplace_path)

    return touched


def main() -> None:
    if len(sys.argv) != 2 or not VERSION_RE.match(sys.argv[1]):
        print("usage: python scripts/bump_version.py <new-version>  (e.g. 1.0.0)", file=sys.stderr)
        sys.exit(1)

    version = sys.argv[1]
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    touched = bump(repo_root, version)

    for path in touched:
        print(f"bumped {path}")
    print(f"next: update CHANGELOG.md, commit, tag v{version}")


if __name__ == "__main__":
    main()
