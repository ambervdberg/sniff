"""Package-level checks that only need the source tree, not an installed wheel."""
import os

from sniff import patterns


def test_bundled_rules_resolve_on_disk():
    rules = patterns.rules_dir()
    assert os.path.isdir(rules)
    assert any(f.endswith(".yml") for f in os.listdir(rules))


def test_rule_tests_not_packaged_marker():
    # rule-tests must exist in the checkout (for `sniff test-rules`) even though
    # the wheel excludes them.
    assert os.path.isdir(os.path.join(os.path.dirname(patterns.rules_dir()), "rule-tests"))
