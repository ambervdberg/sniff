"""Every file in the checkout that declares a version must declare the same one.

This is a maintainer/CI concern, not something a user of the installed CLI can act
on, so it lives here rather than in `sniff doctor`. Bump versions with
`python scripts/bump_version.py <version>`, never by hand.

The marketplace entry version is the easiest one to forget: plugin.json wins at
install time, so a stale entry is silently ignored and only shows up as a Claude
Code marketplace validation warning.
"""

import json
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_json(*parts):
    with open(os.path.join(REPO_ROOT, *parts), "r", encoding="utf-8") as fh:
        return json.load(fh)


def declared_versions():
    """Map of human-readable source -> version string, one entry per declaration."""
    with open(os.path.join(REPO_ROOT, "pyproject.toml"), "r", encoding="utf-8") as fh:
        pyproject = re.search(r'(?m)^version\s*=\s*"([^"]+)"', fh.read())

    versions = {"pyproject.toml": pyproject.group(1) if pyproject else None}

    for plugin_dir in (".claude-plugin", ".codex-plugin"):
        versions[f"{plugin_dir}/plugin.json"] = _read_json(plugin_dir, "plugin.json").get("version")

    for entry in _read_json(".claude-plugin", "marketplace.json").get("plugins", []):
        versions[f"marketplace.json[{entry.get('name', '?')}]"] = entry.get("version")

    return versions


def test_all_declared_versions_agree():
    versions = declared_versions()
    assert len(set(versions.values())) == 1, versions


def test_every_manifest_declares_a_version():
    """A missing version is drift too: it would make the mismatch test pass on None."""
    versions = declared_versions()
    assert len(versions) == 4, versions
    assert all(v is not None for v in versions.values()), versions
