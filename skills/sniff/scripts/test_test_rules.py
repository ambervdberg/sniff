import os
import test_rules

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_all_ast_rules_have_a_test_file():
    missing = test_rules.rules_missing_tests(REPO)
    assert missing == []

def test_run_test_rules_passes_on_this_repo():
    assert test_rules.run_test_rules(REPO) == 0
