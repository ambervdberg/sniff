import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import bump_version


def _fake_repo(tmp_path):
    """Minimal checkout carrying every file that declares a version."""
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.9.5"\n', encoding="utf-8")
    for d in (".claude-plugin", ".codex-plugin"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "plugin.json").write_text('{"version": "0.9.5"}', encoding="utf-8")
    (tmp_path / ".claude-plugin" / "marketplace.json").write_text(
        '{"name": "sniff", "plugins": [{"name": "sniff", "version": "0.9.5"}]}', encoding="utf-8"
    )
    return tmp_path


def test_bump_rewrites_every_manifest(tmp_path):
    _fake_repo(tmp_path)
    bump_version.bump(str(tmp_path), "1.0.0")
    assert '"version": "1.0.0"' in (tmp_path / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    assert '"version": "1.0.0"' in (tmp_path / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
    assert 'version = "1.0.0"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")


def test_bump_rewrites_marketplace_entry(tmp_path):
    """Regression guard: the marketplace entry drifted to 0.1.1 while plugin.json
    was at 0.10.0, because the bump script did not know about this file."""
    _fake_repo(tmp_path)
    bump_version.bump(str(tmp_path), "1.0.0")
    marketplace = json.loads((tmp_path / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    assert marketplace["plugins"][0]["version"] == "1.0.0"
    assert marketplace["name"] == "sniff"  # untouched keys survive the rewrite
