#!/usr/bin/env python3
"""Tests for the forge node-metric scaffold mode.

Run: python skills/sniff-forge/scripts/test_forge.py

Forges into a temp skills dir (no network, no ast-grep needed) and checks the
generated files are coherent: right engine call, no unfilled placeholders.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import forge  # noqa: E402


class NodeMetricForgeTest(unittest.TestCase):
    def setUp(self):
        # Redirect the forge's output dir to a throwaway tree.
        self.tmp = tempfile.mkdtemp()
        self._orig = forge.SKILLS_DIR
        forge.SKILLS_DIR = self.tmp

    def tearDown(self):
        forge.SKILLS_DIR = self._orig

    def _forge(self, metric: str, name: str):
        args = forge.build_parser().parse_args([
            "node-metric", "--metric", metric, "--name", name,
            "--title", "T", "--description", "D",
        ])
        args.func(args)
        skill = os.path.join(self.tmp, name)
        script = open(os.path.join(skill, "scripts", f"{name}.py"), encoding="utf-8").read()
        md = open(os.path.join(skill, "SKILL.md"), encoding="utf-8").read()
        return script, md

    def test_every_metric_forges_cleanly(self):
        for metric, (fn, key, *_rest) in forge.NODE_METRICS.items():
            script, md = self._forge(metric, f"smell-{metric}")
            # The script wires the right engine function and metric key.
            self.assertIn(f"nm.{fn}", script)
            self.assertIn(f'METRIC_KEY = "{key}"', script)
            # No placeholder survived in either file.
            self.assertNotIn("@@", script)
            self.assertNotIn("@@", md)

    def test_template_lines_uses_selector_column(self):
        script, _ = self._forge("template-lines", "smell-tpl")
        self.assertIn('"SELECTOR"', script)
        self.assertIn("inline_template_lines", script)

    def test_unknown_metric_is_rejected(self):
        with self.assertRaises(SystemExit):
            forge.build_parser().parse_args(
                ["node-metric", "--metric", "nope", "--name", "x",
                 "--title", "T", "--description", "D"]
            )


if __name__ == "__main__":
    unittest.main()
