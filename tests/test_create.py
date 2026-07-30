#!/usr/bin/env python3
"""Tests for the create node-metric scaffold mode.

Run: python -m pytest tests/test_create.py

Creates into a temp skills dir (no network, no ast-grep needed) and checks the
generated files are coherent: right engine call, no unfilled placeholders.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "skills", "sniff-create", "scripts"))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

import create
from sniff import discovery


def run_create(argv):
    """Parse argv through create's own parser and invoke the matched subcommand."""
    args = create.build_parser().parse_args(argv)
    args.func(args)


class NodeMetricCreateTest(unittest.TestCase):
    def setUp(self):
        # Redirect the create's output dir to a throwaway tree.
        self.tmp = tempfile.mkdtemp()
        self._orig = create.SKILLS_DIR
        create.SKILLS_DIR = self.tmp

    def tearDown(self):
        create.SKILLS_DIR = self._orig

    def _create(self, metric: str, name: str):
        args = create.build_parser().parse_args([
            "node-metric", "--metric", metric, "--name", name,
            "--title", "T", "--description", "D",
        ])
        args.func(args)
        skill = os.path.join(self.tmp, name)
        script = open(os.path.join(skill, "scripts", f"{name}.py"), encoding="utf-8").read()
        md = open(os.path.join(skill, "SKILL.md"), encoding="utf-8").read()
        return script, md

    def test_every_metric_creates_cleanly(self):
        for metric, (fn, key, *_rest) in create.NODE_METRICS.items():
            script, md = self._create(metric, f"smell-{metric}")
            # The script wires the right engine function and metric key.
            self.assertIn(f"nm.{fn}", script)
            self.assertIn(f'METRIC_KEY = "{key}"', script)
            # No placeholder survived in either file.
            self.assertNotIn("@@", script)
            self.assertNotIn("@@", md)

    def test_template_lines_uses_selector_column(self):
        script, _ = self._create("template-lines", "smell-tpl")
        self.assertIn('"SELECTOR"', script)
        self.assertIn("inline_template_lines", script)

    def test_unknown_metric_is_rejected(self):
        with self.assertRaises(SystemExit):
            create.build_parser().parse_args(
                ["node-metric", "--metric", "nope", "--name", "x",
                 "--title", "T", "--description", "D"]
            )


def test_rule_local_mode_writes_under_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_create(["rule", "--local", "--name", "no-x", "--language", "typescript",
                "--title", "t", "--message", "m", "--pattern", "x()",
                "--test-invalid", "x()", "--test-valid", "y()"])
    assert (tmp_path / ".sniff" / "rules" / "no-x.yml").is_file()
    tests = (tmp_path / ".sniff" / "rule-tests" / "no-x.yml").read_text(encoding="utf-8")
    assert "invalid:" in tests and "valid:" in tests


def test_core_rule_dirs_point_at_the_package_catalog():
    """Core rules and fixtures live in the installed package, not under skills/.

    The scan reads rules from src/sniff/patterns/rules, so scaffolding anywhere
    else produces a rule that never runs."""
    assert create.RULES_DIR == os.path.join(create.REPO_ROOT, "src", "sniff", "patterns", "rules")
    assert create.RULE_TESTS_DIR == os.path.join(
        create.REPO_ROOT, "src", "sniff", "patterns", "rule-tests")
    assert os.path.isdir(create.RULES_DIR)
    assert os.path.isdir(create.RULE_TESTS_DIR)


def test_rule_repo_mode_writes_rule_and_fixture_into_catalog(tmp_path, monkeypatch):
    """Repo mode writes the rule to RULES_DIR and its fixture to RULE_TESTS_DIR."""
    monkeypatch.setattr(create, "RULES_DIR", str(tmp_path / "rules"))
    monkeypatch.setattr(create, "RULE_TESTS_DIR", str(tmp_path / "rule-tests"))
    run_create(["rule", "--name", "no-z", "--language", "typescript",
                "--title", "t", "--message", "m", "--pattern", "z()",
                "--test-invalid", "z()", "--test-valid", "y()"])

    assert (tmp_path / "rules" / "no-z.yml").is_file()
    assert (tmp_path / "rule-tests" / "no-z.yml").is_file()


def test_rule_repo_mode_requires_test_invalid(tmp_path, monkeypatch):
    monkeypatch.setattr(create, "RULES_DIR", str(tmp_path / "rules"))
    with pytest.raises(SystemExit):
        run_create(["rule", "--name", "no-y", "--language", "typescript",
                    "--title", "t", "--message", "m", "--pattern", "y()"])


def test_create_external_detector_is_discoverable(tmp_path):
    """--target external (the default) scaffolds a manifest + standalone script
    under <dest>/.sniff/detectors/<name>/ that sniff.discovery.discover() picks
    up with no further registration step."""
    run_create(["detector", "--name", "my-smell", "--target", "external",
                "--dest", str(tmp_path)])

    detector_dir = tmp_path / ".sniff" / "detectors" / "my-smell"
    assert (detector_dir / "detector.yml").is_file()
    assert (detector_dir / "my-smell.py").is_file()

    detectors, errors = discovery.discover(str(tmp_path))
    assert errors == []
    assert any(d.name == "my-smell" for d in detectors)


def test_create_external_detector_script_runs_standalone():
    """The external script must not import sniff: it has to keep working in a
    consuming repo whose sniff version has drifted from the one that scaffolded
    it."""
    templates_dir = os.path.join(os.path.dirname(create.__file__), "..", "templates")
    template_path = os.path.join(templates_dir, "detector_external_script.py.tmpl")
    with open(template_path, encoding="utf-8") as fh:
        lines = fh.readlines()
    import_lines = [ln for ln in lines if ln.startswith("import ") or ln.startswith("from ")]
    assert not any("sniff" in ln for ln in import_lines)
    assert "SNIFF_EXTRA_IGNORE" in "".join(lines)


class CoreDetectorCreateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig = create.SRC_DETECTORS_DIR
        create.SRC_DETECTORS_DIR = self.tmp

    def tearDown(self):
        create.SRC_DETECTORS_DIR = self._orig

    def test_core_target_writes_registry_shaped_module(self):
        run_create(["detector", "--name", "my-smell", "--target", "core"])

        module_path = os.path.join(self.tmp, "my_smell.py")
        self.assertTrue(os.path.isfile(module_path))
        content = open(module_path, encoding="utf-8").read()

        self.assertIn('NAME = "my-smell"', content)
        self.assertIn("TITLE =", content)
        self.assertIn("DEFAULT_ARGS", content)
        self.assertIn("def main(", content)
        self.assertIn("from sniff import harness as h", content)
        self.assertNotIn("@@", content)


if __name__ == "__main__":
    unittest.main()
