import os
import contribute

def _mk_local_rule(tmp_path, rule_id="no-x", with_fixture=True):
    rules = tmp_path / ".sniff" / "rules"; rules.mkdir(parents=True)
    (rules / f"{rule_id}.yml").write_text(f"id: {rule_id}\nlanguage: typescript\nmessage: m\nrule:\n  pattern: \"x()\"\n", encoding="utf-8")
    if with_fixture:
        tests = tmp_path / ".sniff" / "rule-tests"; tests.mkdir(parents=True)
        (tests / f"{rule_id}.yml").write_text(f"id: {rule_id}\ninvalid:\n  - |\n    x()\n", encoding="utf-8")

def test_guards_pass_for_complete_rule(tmp_path):
    _mk_local_rule(tmp_path)
    assert contribute.check_guards("no-x", str(tmp_path), core_ids={"no-empty-catch"}) == []

def test_guard_blocks_missing_fixture(tmp_path):
    _mk_local_rule(tmp_path, with_fixture=False)
    errs = contribute.check_guards("no-x", str(tmp_path), core_ids=set())
    assert any("fixture" in e for e in errs)

def test_guard_blocks_core_collision(tmp_path):
    _mk_local_rule(tmp_path)
    errs = contribute.check_guards("no-x", str(tmp_path), core_ids={"no-x"})
    assert any("collides" in e for e in errs)

def test_resolve_checkout_prefers_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SNIFF_REPO", str(tmp_path))
    assert contribute.resolve_checkout() == str(tmp_path)
