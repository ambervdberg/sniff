#!/usr/bin/env python3
"""Behavioral tests for the deepest-nesting detector.

Run: python -m pytest tests/test_deepest_nesting.py -q
Skips cleanly if ast-grep is not on PATH.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from conftest import tool_available, write_tree_file

from sniff.detectors import deepest_nesting

HAS_AST_GREP = tool_available("ast-grep")


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
class DeepestNestingTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self):
        out = io.StringIO()
        with redirect_stdout(out):
            deepest_nesting.main([self.root])
        return out.getvalue()

    def test_deepest_function_ranks_above_shallow(self):
        write_tree_file(self.root, "deep.py", """\
            def pyramid(rows):
                if rows:
                    for row in rows:
                        while row:
                            if row > 1:
                                return row
            """)
        write_tree_file(self.root, "flat.py", """\
            def straight(rows):
                if rows:
                    return rows[0]
            """)
        table = self._run()
        self.assertIn("pyramid", table)
        self.assertLess(table.index("pyramid"), table.index("straight"))


if __name__ == "__main__":
    unittest.main()
