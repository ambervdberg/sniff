#!/usr/bin/env python3
"""Catalog test: a fixture with known smells must yield the expected counts.

Run: python skills/sniff-lint/scripts/test_format.py
Skips cleanly if ast-grep is not on PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FORMAT = os.path.join(HERE, "format.py")
HAS_AST_GREP = shutil.which("ast-grep") is not None


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        # 3 explicit anys; 1 nested ternary.
        self._write("bad.ts", "let a: any = 1;\nfunction f(b: any) { return b; }\nconst c: any = [];\n")
        self._write("ternary.ts", "const t = x ? 1 : y ? 2 : 3;\n")
        self._write("clean.ts", "const n: number = 1;\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, rel, body):
        with open(os.path.join(self.root, rel), "w", encoding="utf-8") as fh:
            fh.write(body)

    def _run(self, *extra):
        proc = subprocess.run([sys.executable, FORMAT, self.root, *extra],
                              capture_output=True, text=True)
        return proc.stdout

    def test_explicit_any_counted(self):
        out = self._run("--rule", "no-explicit-any")
        self.assertIn("no-explicit-any", out)
        # The count column should read 3 for this rule.
        line = next(l for l in out.splitlines() if l.startswith("no-explicit-any"))
        self.assertIn("3", line.split())

    def test_nested_ternary_found(self):
        out = self._run("--rule", "no-nested-ternary")
        self.assertIn("no-nested-ternary", out)

    def test_severity_filter_excludes_others(self):
        out = self._run("--severity", "error")
        self.assertIn("0 findings", out)  # all seeded rules are warnings
        self.assertIn("Ran", out)         # still reports rules ran, so clean != broken

    def test_clean_only_reports_nothing(self):
        empty = tempfile.mkdtemp()
        try:
            with open(os.path.join(empty, "ok.ts"), "w", encoding="utf-8") as fh:
                fh.write("const n: number = 1;\n")
            proc = subprocess.run([sys.executable, FORMAT, empty],
                                  capture_output=True, text=True)
            self.assertIn("0 findings", proc.stdout)
            self.assertIn("Ran", proc.stdout)  # clean repo still names the rules that ran
        finally:
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
