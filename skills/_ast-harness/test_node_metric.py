#!/usr/bin/env python3
"""Tests for the node-metric engine (nesting depth).

Run: python skills/_ast-harness/test_node_metric.py
Skips cleanly if ast-grep is not on PATH.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import node_metric as nm  # noqa: E402

HAS_AST_GREP = shutil.which("ast-grep") is not None


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
class NestingDepthTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name: str, src: str) -> None:
        with open(os.path.join(self.root, name), "w", encoding="utf-8") as fh:
            fh.write(src)

    def _depths(self) -> dict[str, int]:
        return {m.name: m.metrics["depth"] for m in nm.nesting_depth(self.root)}

    def test_python_depths(self):
        self._write("a.py",
            "def flat(a):\n"
            "    return a\n"
            "\n"
            "def shallow(a):\n"
            "    if a:\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
            "def deep(a, b):\n"
            "    if a:\n"
            "        for x in b:\n"
            "            while x:\n"
            "                if x > 1:\n"
            "                    return x\n"
            "    return 0\n"
        )
        d = self._depths()
        self.assertEqual(d["flat"], 0)
        self.assertEqual(d["shallow"], 1)
        self.assertEqual(d["deep"], 4)  # if > for > while > if

    def test_sequential_blocks_do_not_stack(self):
        # Two sibling if-blocks are depth 1, not 2: nesting is containment, not count.
        self._write("b.py",
            "def two(a):\n"
            "    if a:\n"
            "        return 1\n"
            "    if not a:\n"
            "        return 2\n"
        )
        self.assertEqual(self._depths()["two"], 1)

    def test_typescript_depth(self):
        self._write("c.ts",
            "function g(xs: number[]) {\n"
            "  for (const x of xs) {\n"
            "    if (x > 0) {\n"
            "      while (x) { x--; }\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        self.assertEqual(self._depths()["g"], 3)  # for > if > while

    def test_unsupported_language_yields_nothing(self):
        # A language with no nesting kinds is skipped, not crashed on.
        self._write("d.txt", "if (x) { if (y) {} }\n")
        self.assertEqual(nm.nesting_depth(self.root), [])


if __name__ == "__main__":
    unittest.main()
