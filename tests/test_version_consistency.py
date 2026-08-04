"""Every file in the checkout that declares a version must declare the same one.

This is a maintainer/CI concern, not something a user of the installed CLI can act
on, so it lives here rather than in `sniff doctor`. Bump versions with
`python scripts/bump_version.py <version>`, never by hand.

The marketplace entry version is the easiest one to forget: plugin.json wins at
install time, so a stale entry is silently ignored and only shows up as a Claude
Code marketplace validation warning.

uv.lock counts too: CI runs `uv sync --locked`, which refuses to resolve when the
lock records a different version for sniff-smells than pyproject.toml declares.

So does the README: its CI-mode snippet pins the composite action by release tag, and
readers copy that line verbatim into their own workflow. docs/ci.md carries the same
pin for the agent-facing CI-mode walkthrough.
"""

import json
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_json(*parts):
    with open(os.path.join(REPO_ROOT, *parts), "r", encoding="utf-8") as fh:
        return json.load(fh)


def _locked_version(package):
    """Version uv.lock records for `package`, or None if it declares no such package.

    Found by scanning the [[package]] blocks rather than by line offset: uv is free to
    reorder keys, and a block also holds sub-tables like [package.optional-dependencies]
    whose keys must not be mistaken for the package's own."""
    with open(os.path.join(REPO_ROOT, "uv.lock"), "r", encoding="utf-8") as fh:
        blocks = fh.read().split("[[package]]")

    for block in blocks[1:]:
        # Stop at the first sub-table header so only the block's own keys are read.
        own_keys = re.split(r"(?m)^\[", block)[0]
        name = re.search(r'(?m)^name\s*=\s*"([^"]+)"', own_keys)
        if name and name.group(1) == package:
            version = re.search(r'(?m)^version\s*=\s*"([^"]+)"', own_keys)
            return version.group(1) if version else None

    return None


def _readme_action_pin():
    """Version the README's CI-mode snippet pins the composite action to, or None.

    Returns None both when the pin is missing and when the README carries two pins that
    disagree, since either way there is no single version the README declares."""
    with open(os.path.join(REPO_ROOT, "README.md"), "r", encoding="utf-8") as fh:
        pins = set(re.findall(r"ambervdberg/sniff@v(\d+\.\d+\.\d+)", fh.read()))

    return pins.pop() if len(pins) == 1 else None


def _ci_doc_action_pin():
    """Version docs/ci.md's snippet pins the composite action to, or None.

    Same disagreement handling as `_readme_action_pin`: two differing pins in the
    file count as no single declared version, not as a pick-one."""
    with open(os.path.join(REPO_ROOT, "docs", "ci.md"), "r", encoding="utf-8") as fh:
        pins = set(re.findall(r"ambervdberg/sniff@v(\d+\.\d+\.\d+)", fh.read()))

    return pins.pop() if len(pins) == 1 else None


def declared_versions():
    """Map of human-readable source -> version string, one entry per declaration."""
    with open(os.path.join(REPO_ROOT, "pyproject.toml"), "r", encoding="utf-8") as fh:
        pyproject = re.search(r'(?m)^version\s*=\s*"([^"]+)"', fh.read())

    versions = {"pyproject.toml": pyproject.group(1) if pyproject else None}

    for plugin_dir in (".claude-plugin", ".codex-plugin"):
        versions[f"{plugin_dir}/plugin.json"] = _read_json(plugin_dir, "plugin.json").get("version")

    for entry in _read_json(".claude-plugin", "marketplace.json").get("plugins", []):
        versions[f"marketplace.json[{entry.get('name', '?')}]"] = entry.get("version")

    versions["uv.lock[sniff-smells]"] = _locked_version("sniff-smells")
    versions["README.md[action pin]"] = _readme_action_pin()
    versions["docs/ci.md[action pin]"] = _ci_doc_action_pin()

    return versions


def test_all_declared_versions_agree():
    versions = declared_versions()
    assert len(set(versions.values())) == 1, versions


def test_every_manifest_declares_a_version():
    """A missing version is drift too: it would make the mismatch test pass on None."""
    versions = declared_versions()
    assert len(versions) == 7, versions
    assert all(v is not None for v in versions.values()), versions


def test_uv_lock_matches_pyproject():
    """Called out on its own because its failure mode is the confusing one: the lock
    drifts silently until CI's `uv sync --locked` refuses to resolve. Fix with
    `uv lock`, which `scripts/bump_version.py` now runs for you."""
    versions = declared_versions()
    assert versions["uv.lock[sniff-smells]"] == versions["pyproject.toml"], versions
