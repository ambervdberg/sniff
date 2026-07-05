import os
import subprocess
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

def _mk_fake_checkout(tmp_path):
    co = tmp_path / "sniff-co"
    (co / "skills" / "sniff-patterns" / "rules").mkdir(parents=True)
    (co / "skills" / "sniff-patterns" / "rule-tests").mkdir(parents=True)
    (co / "skills" / "sniff-patterns" / "sgconfig.yml").write_text(
        "ruleDirs:\n  - rules\ntestConfigs:\n  - testDir: rule-tests\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(co)], check=True)
    subprocess.run(["git", "-C", str(co), "-c", "user.email=test@test.com",
                    "-c", "user.name=test", "commit", "-q", "--allow-empty",
                    "-m", "init"], check=True)
    return co

def test_checkout_backend_copies_and_branches(tmp_path, monkeypatch):
    _mk_local_rule(tmp_path)
    co = _mk_fake_checkout(tmp_path)
    rc = contribute._contribute_to_checkout("no-x", str(tmp_path), str(co))
    assert rc == 0
    assert (co / "skills" / "sniff-patterns" / "rules" / "no-x.yml").is_file()
    assert (co / "skills" / "sniff-patterns" / "rule-tests" / "no-x.yml").is_file()
    branch = subprocess.run(["git", "-C", str(co), "branch", "--show-current"],
                            capture_output=True, text=True).stdout.strip()
    assert branch == "rule/no-x"
