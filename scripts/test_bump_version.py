import bump_version


def test_bump_rewrites_all_three(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.9.5"\n', encoding="utf-8")
    for d in (".claude-plugin", ".codex-plugin"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "plugin.json").write_text('{"version": "0.9.5"}', encoding="utf-8")
    bump_version.bump(str(tmp_path), "1.0.0")
    assert '"version": "1.0.0"' in (tmp_path / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    assert 'version = "1.0.0"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
