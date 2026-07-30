"""Tests for `sniff test-rules`: every catalog rule must have a rule-test file."""

import os

from sniff import rules_testing

# rules_testing.py lives at <repo>/src/sniff/rules_testing.py; three levels up is <repo>.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(rules_testing.__file__))))

def test_all_ast_rules_have_a_test_file():
    missing = rules_testing.rules_missing_tests(REPO)
    assert missing == []

def test_run_test_rules_passes_on_this_repo():
    assert rules_testing.run_test_rules(REPO) == 0
