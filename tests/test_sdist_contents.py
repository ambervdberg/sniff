#!/usr/bin/env python3
"""The published sdist ships project source only, never local tool state.

Hatchling's default is to sweep in every tracked file. That silently published
8.5 MB of .beads issue-tracker state to PyPI, so pyproject.toml declares an
explicit allowlist instead of blocking known-bad directories: a new tool folder
landing in the repo must not leak into a release by default.

Every pattern needs a leading "/" to anchor it to the project root. Unanchored,
hatchling matches at any depth, so a bare "hooks" also matched .beads/hooks/ and
a bare "README.md" matched .beads/README.md and evals/smoke/README.md.

Run: python -m pytest tests/test_sdist_contents.py
"""

from __future__ import annotations

import os
import unittest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.normpath(os.path.join(HERE, ".."))
PYPROJECT = os.path.join(PLUGIN_ROOT, "pyproject.toml")

# Directories that exist to serve local tooling, not users of the package.
NEVER_PUBLISH = (".beads", ".claude", ".superpowers", ".vscode", ".github", "evals")


def _build_targets() -> dict:
    """The [tool.hatch.build.targets] table, keyed by target name."""
    with open(PYPROJECT, "rb") as fh:
        return tomllib.load(fh)["tool"]["hatch"]["build"]["targets"]


class SdistAllowlistTest(unittest.TestCase):
    def setUp(self):
        self.include = _build_targets()["sdist"]["include"]

    def test_allowlist_is_declared(self):
        self.assertTrue(self.include)

    def test_every_pattern_is_anchored_to_the_project_root(self):
        for pattern in self.include:
            self.assertTrue(pattern.startswith("/"), pattern)

    def test_no_local_tool_directory_is_allowlisted(self):
        for pattern in self.include:
            self.assertNotIn(pattern.lstrip("/").split("/")[0], NEVER_PUBLISH)


class RuleTestExclusionTest(unittest.TestCase):
    """The pattern rule-tests are catalog fixtures, not shipped code.

    The wheel already drops them, but the sdist allowlist includes all of /src,
    which sweeps them back in unless the sdist excludes them explicitly.
    """

    def test_rule_tests_are_excluded_from_both_build_targets(self):
        targets = _build_targets()
        self.assertIn("/src/sniff/patterns/rule-tests", targets["sdist"].get("exclude", []))
        self.assertIn("src/sniff/patterns/rule-tests", targets["wheel"].get("exclude", []))
