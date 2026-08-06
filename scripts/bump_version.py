#!/usr/bin/env python3
"""Bump the version in pyproject.toml, .claude-plugin/plugin.json,
.codex-plugin/plugin.json and every plugin entry in .claude-plugin/marketplace.json, in
lockstep, so `sniff doctor`'s drift check stays green, then refresh uv.lock so the
version it records for sniff-smells matches (CI runs `uv sync --locked`, which fails on
a stale lock).

Usage: python scripts/bump_version.py <new-version>"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _write_json(path: str, data: dict) -> None:
    """Write JSON back with the repo's house style: 2-space indent, trailing newline,
    LF line endings (newline="" stops Windows from translating \\n to \\r\\n)."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def bump(root: str, version: str) -> list[str]:
    """Rewrite the version in every file that declares one, return the paths touched."""
    touched = []

    pyproject_path = os.path.join(root, "pyproject.toml")
    with open(pyproject_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    text = re.sub(r'(?m)^version\s*=\s*"[^"]+"', f'version = "{version}"', text)
    with open(pyproject_path, "w", encoding="utf-8", newline="") as fh:
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


def relock(root: str) -> bool:
    """Re-resolve uv.lock so it records the version pyproject.toml now declares.

    Never raises: the manifest files are already written, and losing them to a crash
    because `uv` is missing or unhappy would be worse than a warning the user can act
    on. Returns whether the lockfile was refreshed."""
    try:
        result = subprocess.run(["uv", "lock"], cwd=root, capture_output=True, text=True)
    except OSError as exc:
        print(f"warning: could not run `uv lock` ({exc})", file=sys.stderr)
    else:
        if result.returncode == 0:
            return True
        print(f"warning: `uv lock` failed with exit code {result.returncode}", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)

    print("warning: uv.lock still records the old version; run `uv lock` before committing", file=sys.stderr)
    return False


def main() -> None:
    if len(sys.argv) != 2 or not VERSION_RE.match(sys.argv[1]):
        print("usage: python scripts/bump_version.py <new-version>  (e.g. 1.0.0)", file=sys.stderr)
        sys.exit(1)

    version = sys.argv[1]
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    touched = bump(repo_root, version)
    relocked = relock(repo_root)

    for path in touched:
        print(f"bumped {path}")
    if relocked:
        print(f"refreshed {os.path.join(repo_root, 'uv.lock')}")
        print(f"next: update CHANGELOG.md, commit, tag v{version}")
        return

    print(f"next: run `uv lock`, then update CHANGELOG.md, commit, tag v{version}")
    sys.exit(1)


if __name__ == "__main__":
    main()
