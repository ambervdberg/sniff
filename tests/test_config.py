"""Tests for .sniff.toml config loading (detector thresholds, rule overrides)."""

from sniff import config


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


def test_bare_top_sets_the_global_top(tmp_path):
    cfg = _write(tmp_path, "[detectors]\ntop = 5\n")
    assert cfg.global_top == "5"


def test_bare_top_does_not_warn_as_an_unknown_key(tmp_path):
    cfg = _write(tmp_path, "[detectors]\ntop = 5\n")
    assert cfg.warnings == []


def _repo(tmp_path, config_text):
    """A git repo whose root carries `.sniff.toml`, with a `src/` subdirectory."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".sniff.toml").write_text(config_text, encoding="utf-8")
    (tmp_path / "src").mkdir()
    return tmp_path


def test_scanning_a_subdirectory_finds_the_repo_root_config(tmp_path):
    """`sniff src` must honour the config the repo committed at its root. It used to
    look only in the scanned directory, so every subdirectory scan silently ran with
    no ignores, no skips and no rule overrides at all."""
    repo = _repo(tmp_path, "[rules]\nno-console-log = false\n")
    cfg = config.load(str(repo / "src"))
    assert cfg.disabled_rules == {"no-console-log"}


def test_the_nearest_config_wins(tmp_path):
    """A subdirectory that carries its own file is not merged with the root's."""
    repo = _repo(tmp_path, "[rules]\nno-console-log = false\n")
    (repo / "src" / ".sniff.toml").write_text("[rules]\nno-explicit-any = false\n", encoding="utf-8")
    cfg = config.load(str(repo / "src"))
    assert cfg.disabled_rules == {"no-explicit-any"}


def test_the_search_stops_at_the_repo_root(tmp_path):
    """Config above the repo is not this project's business. Without this bound, a
    stray file in a home directory would rewrite unrelated scans."""
    (tmp_path / ".sniff.toml").write_text("[rules]\nno-console-log = false\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    assert config.load(str(repo)).disabled_rules == set()


def test_no_walk_outside_a_repo(tmp_path):
    """Outside a repo there is no project boundary to trust, so only the scanned
    directory itself is read."""
    (tmp_path / ".sniff.toml").write_text("[rules]\nno-console-log = false\n", encoding="utf-8")
    loose = tmp_path / "loose"
    loose.mkdir()
    assert config.load(str(loose)).disabled_rules == set()
