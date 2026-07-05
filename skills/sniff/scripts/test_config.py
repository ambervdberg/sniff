import config


def _write(tmp_path, text):
    (tmp_path / ".sniff.toml").write_text(text, encoding="utf-8")
    return config.load(str(tmp_path))


def test_missing_file_gives_empty_config(tmp_path):
    cfg = config.load(str(tmp_path))
    assert cfg.disabled_rules == set() and cfg.warnings == []


def test_disabled_rules_and_thresholds(tmp_path):
    cfg = _write(tmp_path, "[rules]\nno-console-log = false\n\n[detectors]\nskip = \"a,b\"\nlargest-methods.top = 15\n")
    assert cfg.disabled_rules == {"no-console-log"}
    assert cfg.skip_detectors == {"a", "b"}
    assert cfg.thresholds == {"largest-methods": {"top": "15"}}


def test_unknown_section_warns_not_raises(tmp_path):
    cfg = _write(tmp_path, "[nonsense]\nx = 1\n")
    assert any("nonsense" in w for w in cfg.warnings)
