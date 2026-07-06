#!/usr/bin/env python3
"""Unit tests for the shared ast-search engine.

Run: python -m unittest discover -s skills/_ast-harness -p 'test_*.py'
(or just `python skills/_ast-harness/test_harness.py`).

Tests that exercise scanning need the `ast-grep` binary on PATH; they skip
themselves cleanly if it is missing, so the pure-Python tests still run.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(__file__))
import harness as h

HAS_AST_GREP = shutil.which("ast-grep") is not None


def _match(file, start, end, b_start, b_end, name="(anon)"):
    """Construct a Match without touching disk."""
    return h.Match(file=file, start_line=start, end_line=end,
                   byte_start=b_start, byte_end=b_end, name=name)


class MatchTest(unittest.TestCase):
    def test_line_span_is_inclusive(self):
        m = _match("a.py", 10, 12, 0, 0)
        self.assertEqual(m.lines, 3)

    def test_display_line_is_one_based(self):
        m = _match("a.py", 0, 0, 0, 0)
        self.assertEqual(m.line, 1)

    def test_location_uses_one_based_line(self):
        m = _match("src/a.py", 41, 41, 0, 0)
        self.assertEqual(m.location, "src/a.py:42")


class InIgnoredDirTest(unittest.TestCase):
    """_in_ignored_dir matches SNIFF_EXTRA_IGNORE globs against the path relative
    to the scan root, the same base sniff-patterns' format.py uses, so an
    ignore glob behaves identically across every detector."""

    def setUp(self):
        self._saved = os.environ.get("SNIFF_EXTRA_IGNORE")
        os.environ["SNIFF_EXTRA_IGNORE"] = "generated/**"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SNIFF_EXTRA_IGNORE", None)
        else:
            os.environ["SNIFF_EXTRA_IGNORE"] = self._saved

    def test_glob_matches_root_relative_for_scan_arg_prefixed_path(self):
        # ast-grep emits "<scan-arg>/generated/big.ts" for a relative scan path;
        # only the root-relative base ("generated/big.ts") matches "generated/**".
        self.assertTrue(h._in_ignored_dir("proj/generated/big.ts", "proj"))

    def test_glob_matches_root_relative_for_absolute_path(self):
        root = os.path.join("C:", os.sep, "work", "proj")
        abs_file = os.path.join(root, "generated", "big.ts")
        self.assertTrue(h._in_ignored_dir(abs_file, root))

    def test_glob_does_not_match_outside_ignored_dir(self):
        self.assertFalse(h._in_ignored_dir("proj/src/big.ts", "proj"))


class FoldNestedTest(unittest.TestCase):
    def test_inner_match_folded_into_outer(self):
        outer = _match("a.ts", 0, 20, 0, 200, "outer")
        inner = _match("a.ts", 5, 15, 50, 150, "inner")
        kept = h.fold_nested([inner, outer])  # order should not matter
        self.assertEqual([m.name for m in kept], ["outer"])

    def test_siblings_both_kept(self):
        a = _match("a.ts", 0, 5, 0, 50, "a")
        b = _match("a.ts", 6, 10, 60, 100, "b")
        kept = h.fold_nested([a, b])
        self.assertEqual({m.name for m in kept}, {"a", "b"})

    def test_same_region_in_different_files_both_kept(self):
        a = _match("a.ts", 0, 5, 0, 50, "a")
        b = _match("b.ts", 0, 5, 0, 50, "b")
        kept = h.fold_nested([a, b])
        self.assertEqual(len(kept), 2)


class PrintTableTest(unittest.TestCase):
    def _render(self, matches, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            h.print_table(matches, [("LINES", lambda m: m.lines),
                                    ("NAME", lambda m: m.name),
                                    ("LOCATION", lambda m: m.location)], **kw)
        return buf.getvalue()

    def test_empty_prints_no_matches(self):
        self.assertIn("No matches.", self._render([]))

    def test_sort_and_top(self):
        rows = [_match("a.ts", 0, 4, 0, 0, "small"),
                _match("b.ts", 0, 99, 0, 0, "big")]
        out = self._render(rows, sort_key=lambda m: m.lines, top=1)
        self.assertIn("big", out)
        self.assertNotIn("small", out)

    def test_no_trailing_whitespace(self):
        rows = [_match("a.ts", 0, 4, 0, 0, "f")]
        for line in self._render(rows).splitlines():
            self.assertEqual(line, line.rstrip(), f"trailing space in: {line!r}")


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
class ScanIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._write("src/app.py", """
            def small():
                return 1

            def big():
                a = 1
                b = 2
                c = 3
                return a + b + c
        """)
        # A test file + a node_modules file that must be ignored.
        self._write("src/app.test.py", "def in_test():\n    return 1\n")
        self._write("node_modules/dep.py", "def vendored():\n    return 1\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, rel, body):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(body).lstrip("\n"))

    def test_detect_languages_skips_ignored_dirs(self):
        langs = h.detect_languages(self.root)
        self.assertIn("python", langs)

    def test_run_finds_functions_excludes_tests_and_vendor(self):
        kinds = {"python": ["function_definition"]}
        matches = h.run(kinds, self.root, lang="python")
        names = {m.name for m in matches}
        self.assertIn("small", names)
        self.assertIn("big", names)
        self.assertNotIn("in_test", names)    # *.test.* excluded
        self.assertNotIn("vendored", names)   # node_modules ignored

    def test_include_tests_flag(self):
        kinds = {"python": ["function_definition"]}
        matches = h.run(kinds, self.root, lang="python", include_tests=True)
        self.assertIn("in_test", {m.name for m in matches})

    def test_biggest_function_ranks_first(self):
        kinds = {"python": ["function_definition"]}
        matches = h.fold_nested(h.run(kinds, self.root, lang="python"))
        matches.sort(key=lambda m: m.lines, reverse=True)
        self.assertEqual(matches[0].name, "big")


class FileMetricTest(unittest.TestCase):
    """The file-metric engine helpers: iter_source_files + count_code_lines."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._write("src/app.ts", "const a = 1;\n\n\nconst b = 2;\n")   # 2 non-blank
        self._write("src/app.test.ts", "test('x', () => {});\n")
        self._write("node_modules/dep.ts", "export const x = 1;\n")
        self._write(".astro/content.d.ts", "declare module {}\n")        # generated, ignored
        self._write("README.md", "# not source\n")                       # unknown ext, ignored

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, rel, body):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)

    def test_iter_excludes_vendor_generated_and_unknown(self):
        files = h.iter_source_files(self.root, include_tests=True)
        names = {os.path.basename(f) for f in files}
        self.assertIn("app.ts", names)
        self.assertIn("app.test.ts", names)        # tests included when asked
        self.assertNotIn("dep.ts", names)          # node_modules pruned
        self.assertNotIn("content.d.ts", names)    # .astro pruned
        self.assertNotIn("README.md", names)       # unknown extension

    def test_iter_excludes_tests_by_flag(self):
        files = h.iter_source_files(self.root, include_tests=False)
        names = {os.path.basename(f) for f in files}
        self.assertIn("app.ts", names)
        self.assertNotIn("app.test.ts", names)

    def test_count_code_lines_skips_blanks(self):
        path = next(f for f in h.iter_source_files(self.root) if f.endswith("app.ts"))
        self.assertEqual(h.count_code_lines(path), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
