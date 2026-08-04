"""Tests for `sniff test-rules`: every catalog rule must have a rule-test file."""

import os

import pytest
from conftest import tool_available

from sniff import rules_testing

SGCONFIG = "ruleDirs:\n  - rules\ntestConfigs:\n  - testDir: rule-tests\n"
NO_EVAL_RULE = "id: no-eval\nlanguage: python\nseverity: warning\nrule:\n  pattern: eval($X)\n"


def _fake_catalog(root, invalid_snippet: str) -> str:
    """A minimal repo layout holding one rule and one fixture. Returns the repo root."""
    patterns = root / "src" / "sniff" / "patterns"
    rules = patterns / "rules"
    tests = patterns / "rule-tests"
    rules.mkdir(parents=True)
    tests.mkdir(parents=True)
    (patterns / "sgconfig.yml").write_text(SGCONFIG, encoding="utf-8")
    (rules / "no-eval.yml").write_text(NO_EVAL_RULE, encoding="utf-8")
    (tests / "no-eval.yml").write_text(
        f"id: no-eval\nvalid: []\ninvalid:\n  - |\n    {invalid_snippet}\n", encoding="utf-8")
    return str(root)

# rules_testing.py lives at <repo>/src/sniff/rules_testing.py; three levels up is <repo>.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(rules_testing.__file__))))

def test_all_ast_rules_have_a_test_file():
    missing = rules_testing.rules_missing_tests(REPO)
    assert missing == []

def test_run_test_rules_passes_on_this_repo():
    assert rules_testing.run_test_rules(REPO) == 0


@pytest.mark.skipif(not tool_available("ast-grep"), reason="ast-grep not on PATH")
def test_checker_fails_on_broken_rule(tmp_path):
    """A fixture claiming a match on code the rule cannot match must fail."""
    repo = _fake_catalog(tmp_path, "print(1)")
    assert rules_testing.run_test_rules(repo) != 0


@pytest.mark.skipif(not tool_available("ast-grep"), reason="ast-grep not on PATH")
def test_checker_passes_on_correct_rule(tmp_path):
    """The same catalog passes once the fixture points at code the rule matches."""
    repo = _fake_catalog(tmp_path, "eval(x)")
    assert rules_testing.run_test_rules(repo) == 0
