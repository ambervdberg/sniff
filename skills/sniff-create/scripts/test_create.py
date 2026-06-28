#!/usr/bin/env python3
"""Tests for the create node-metric scaffold mode.

Run: python skills/sniff-create/scripts/test_create.py

Creates into a temp skills dir (no network, no ast-grep needed) and checks the
generated files are coherent: right engine call, no unfilled placeholders.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import create  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
