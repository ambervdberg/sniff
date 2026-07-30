"""Tests for `sniff test-rules`: every catalog rule must have a rule-test file."""

import os

from sniff import test_rules

# test_rules.py lives at <repo>/src/sniff/test_rules.py; three levels up is <repo>.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(test_rules.__file__))))

def test_all_ast_rules_have_a_test_file():
    missing = test_rules.rules_missing_tests(REPO)
    assert missing == []

def test_run_test_rules_passes_on_this_repo():
    assert test_rules.run_test_rules(REPO) == 0
