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

    def _cyclo(self) -> dict[str, int]:
        return {m.name: m.metrics["cyclomatic"] for m in nm.cyclomatic(self.root)}

    def test_python_cyclomatic(self):
        self._write("e.py",
            "def simple(a):\n"
            "    return a\n"
            "\n"
            "def branchy(a, b):\n"
            "    if a and b:\n"          # if + and = 2
            "        return 1\n"
            "    for x in b:\n"          # for = 1
            "        if x:\n"            # if = 1
            "            return x\n"
            "    return 0\n"
        )
        c = self._cyclo()
        self.assertEqual(c["simple"], 1)      # no decisions
        self.assertEqual(c["branchy"], 5)     # 1 + (if + and + for + if)

    def test_typescript_cyclomatic_counts_boolean_ops(self):
        self._write("f.ts",
            "function g(a: boolean, b: boolean) {\n"
            "  if (a || b) { return 1; }\n"   # if + || = 2
            "  return 0;\n"
            "}\n"
        )
        self.assertEqual(self._cyclo()["g"], 3)  # 1 + if + ||

    def test_cyclomatic_skips_unsupported(self):
        self._write("g.txt", "if (x) {}\n")
        self.assertEqual(nm.cyclomatic(self.root), [])

    def _params(self) -> dict[str, int]:
        return {m.name: m.metrics["params"] for m in nm.params(self.root)}

    def test_python_param_counts(self):
        self._write("h.py",
            "def none():\n"
            "    return 1\n"
            "\n"
            "def three(a, b, c):\n"
            "    return a\n"
            "\n"
            "def splat(a, *args, **kw):\n"
            "    return a\n"
        )
        p = self._params()
        self.assertEqual(p["none"], 0)
        self.assertEqual(p["three"], 3)
        self.assertEqual(p["splat"], 3)

    def test_generic_comma_is_one_param(self):
        # The comma inside Map<string, number> must not split into two params.
        self._write("i.ts",
            "function g(a: string, b: Map<string, number>, c: number) { return a; }\n"
        )
        self.assertEqual(self._params()["g"], 3)

    def test_count_params_helper(self):
        self.assertEqual(nm.count_params("()"), 0)
        self.assertEqual(nm.count_params("(a)"), 1)
        self.assertEqual(nm.count_params("(a, b, c)"), 3)
        self.assertEqual(nm.count_params("(a, b: Map<x, y>)"), 2)
        self.assertEqual(nm.count_params("(a = {x, y}, b)"), 2)

    def _cognitive(self) -> dict[str, int]:
        return {m.name: m.metrics["cognitive"] for m in nm.cognitive(self.root)}

    def test_cognitive_weights_nesting(self):
        self._write("j.py",
            "def flat(a):\n"
            "    return a\n"
            "\n"
            "def two(a):\n"               # two sibling ifs: 1 + 1 = 2
            "    if a:\n"
            "        return 1\n"
            "    if not a:\n"
            "        return 2\n"
            "\n"
            "def deep(a, b):\n"           # if/for/while/if nested: 1+2+3+4 = 10
            "    if a:\n"
            "        for x in b:\n"
            "            while x:\n"
            "                if x > 1:\n"
            "                    return x\n"
        )
        c = self._cognitive()
        self.assertEqual(c["flat"], 0)
        self.assertEqual(c["two"], 2)
        self.assertEqual(c["deep"], 10)

    def test_cognitive_skips_unsupported(self):
        self._write("k.txt", "if (x) {}\n")
        self.assertEqual(nm.cognitive(self.root), [])


if __name__ == "__main__":
    unittest.main()
