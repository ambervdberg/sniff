#!/usr/bin/env python3
"""Ranking tests for the four detectors built on the shared node-metric CLI.

Each one scores functions differently, so each gets a fixture whose hot function
must outrank (or, where the detector's --min default hides the cold one, replace)
its quiet neighbour.

Run: python -m pytest tests/test_node_metric_detectors.py -q
Skips cleanly if ast-grep is not on PATH.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from conftest import tool_available, write_tree_file

from sniff.detectors import (
    cognitive_complexity,
    cyclomatic_complexity,
    largest_methods,
    most_parameters,
)

HAS_AST_GREP = tool_available("ast-grep")


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
class NodeMetricRankingTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _run(self, module):
        out = io.StringIO()
        with redirect_stdout(out):
            module.main([self.root])
        return out.getvalue()

    def test_largest_methods_ranks_by_line_count(self):
        write_tree_file(self.root, "big.py",
                        "def big():\n" + "    x = 1\n" * 30 + "\n\ndef tiny():\n    pass\n")
        table = self._run(largest_methods)
        self.assertLess(table.index("big"), table.index("tiny"))

    def test_most_parameters_ranks_by_param_count(self):
        write_tree_file(self.root, "params.py",
                        "def many(a, b, c, d, e, f, g):\n    pass\n\n\ndef few(a):\n    pass\n")
        table = self._run(most_parameters)
        # --min defaults to 3, so the one-parameter function is below the cut.
        self.assertIn("many", table)
        self.assertNotIn("few", table)

    def test_cyclomatic_ranks_branchy_function_first(self):
        write_tree_file(self.root, "branchy.py", """\
            def branchy(x):
                if x == 1:
                    return 1
                elif x == 2:
                    return 2
                elif x == 3:
                    return 3
                elif x == 4:
                    return 4
                elif x == 5:
                    return 5
                return 0


            def linear(x):
                return x + 1
            """)
        table = self._run(cyclomatic_complexity)
        self.assertLess(table.index("branchy"), table.index("linear"))

    def test_cognitive_ranks_nested_function_first(self):
        write_tree_file(self.root, "nested.py", """\
            def tangled(rows):
                for row in rows:
                    if row:
                        for cell in row:
                            if cell:
                                return cell


            def plain(rows):
                if rows:
                    return rows
            """)
        table = self._run(cognitive_complexity)
        self.assertLess(table.index("tangled"), table.index("plain"))


if __name__ == "__main__":
    unittest.main()
