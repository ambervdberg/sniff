#!/usr/bin/env python3
"""Behavioral tests for the no-duplicate-string detector.

Run: python -m pytest tests/test_no_duplicate_string.py -q
No parser involved, so this suite runs without ast-grep.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from conftest import write_tree_file

from sniff.detectors import no_duplicate_string


class NoDuplicateStringTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, rel, body):
        return write_tree_file(self.root, rel, body)

    def _run(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            no_duplicate_string.main([self.root, *argv])
        return out.getvalue()

    def test_string_in_three_files_is_reported(self):
        for name in ("a.py", "b.py", "c.py"):
            self._write(name, 'MODE = "fast-and-loose"\n')
        self.assertIn("fast-and-loose", self._run())

    def test_string_in_two_files_is_not_reported(self):
        for name in ("a.py", "b.py"):
            self._write(name, 'MODE = "only-twice"\n')
        self.assertNotIn("only-twice", self._run())

    def test_most_widespread_string_ranks_first(self):
        for name in ("a.py", "b.py", "c.py", "d.py"):
            self._write(name, 'W = "everywhere"\n')
        for name in ("a.py", "b.py", "c.py"):
            self._write("n_" + name, 'N = "narrower"\n')
        table = self._run()
        self.assertLess(table.index("everywhere"), table.index("narrower"))

    def test_idiom_strings_are_not_reported(self):
        # Dunders, encodings, argparse actions and quoted type annotations
        # repeat by convention; none of them may appear as findings.
        body = (
            'name = "__main__"\n'
            'enc = "utf-8"\n'
            'action = "store_true"\n'
            'ann: "list[str] | None" = None\n'
        )
        for name in ("a.py", "b.py", "c.py"):
            self._write(name, body)
        table = self._run()
        for idiom in ("__main__", "utf-8", "store_true", "list[str] | None"):
            with self.subTest(idiom=idiom):
                self.assertNotIn(idiom, table)

    def test_locations_include_line_numbers(self):
        for name in ("a.py", "b.py", "c.py"):
            self._write(name, '# comment\nMODE = "fast-and-loose"\n')
        table = self._run()
        self.assertIn("a.py:2", table)


if __name__ == "__main__":
    unittest.main()
