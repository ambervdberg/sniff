#!/usr/bin/env python3
"""Bump the version in pyproject.toml, .claude-plugin/plugin.json, and
.codex-plugin/plugin.json in lockstep, so `sniff doctor`'s drift check stays green.

Usage: python scripts/bump_version.py <new-version>"""

from __future__ import annotations

import json
import os
import re
import sys

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def bump(root: str, version: str) -> list[str]:
    """Rewrite the version in all three files, return the paths touched."""
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
        with open(plugin_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        touched.append(plugin_path)

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
