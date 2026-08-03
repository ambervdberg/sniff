#!/usr/bin/env python3
"""Tests for the self-admitted-debt detector (TODO/FIXME/HACK/XXX in comments).

Run: python -m pytest tests/test_self_admitted_debt.py -q
No ast-grep needed: this detector scans comments, it does not parse.
"""

from __future__ import annotations

import io
import os
import contextlib
import shutil
import tempfile
import unittest

from sniff.detectors import self_admitted_debt as sad


class MarkerCountingTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name: str, source: str) -> str:
        path = os.path.join(self.root, name).replace("\\", "/")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)
        return path

    def _count(self, name: str, source: str, markers=sad.DEFAULT_MARKERS):
        return sad.count_markers(self._write(name, source), markers)

    def test_counts_each_marker_kind(self):
        counted = self._count("a.py", "# TODO: cache misses\n# FIXME broken\n# TODO again\n")

        self.assertEqual(counted["TODO"], 2)
        self.assertEqual(counted["FIXME"], 1)

    def test_markers_outside_comments_are_ignored(self):
        # A marker in a string is a UI label or a fixture, not admitted debt.
        counted = self._count("a.py", 'label = "TODO: buy milk"\nstatus = "FIXME"\n')

        self.assertEqual(sum(counted.values()), 0)

    def test_block_and_line_comment_styles_both_count(self):
        counted = self._count(
            "a.ts",
            "// TODO: rewrite\n/* FIXME: leaks */\n/**\n * HACK: works for now\n */\n",
        )

        self.assertEqual(sum(counted.values()), 3)

    def test_marker_must_be_a_whole_word(self):
        counted = self._count("a.py", "# TODOS are tracked elsewhere\n# xxx lowercase\n")

        self.assertEqual(sum(counted.values()), 0)

    def test_custom_markers_replace_the_defaults(self):
        counted = self._count("a.py", "# TODO: one\n# REVIEW: two\n", markers=("REVIEW",))

        self.assertEqual(counted["REVIEW"], 1)
        self.assertEqual(counted["TODO"], 0)


class ReportingTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name: str, source: str) -> None:
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)

    def _run(self, *argv: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            sad.main([self.root, *argv])
        return out.getvalue()

    def test_files_are_ranked_by_marker_count(self):
        self._write("few.py", "# TODO: one\n")
        self._write("many.py", "# TODO: one\n# FIXME: two\n# HACK: three\n")

        report = self._run()

        self.assertLess(report.index("many.py"), report.index("few.py"))

    def test_test_files_are_excluded_by_default(self):
        self._write("app.py", "# TODO: real code\n")
        self._write("test_app.py", "# TODO: in a test\n")

        self.assertNotIn("test_app.py", self._run())
        self.assertIn("test_app.py", self._run("--include-tests"))

    def test_clean_repo_says_so(self):
        self._write("app.py", "value = 1\n")

        self.assertIn("No TODO/FIXME/HACK/XXX markers found", self._run())


if __name__ == "__main__":
    unittest.main()
