#!/usr/bin/env python3
"""Unit tests for sniff.harness.render: the table printer and the findings sink.

test_harness.py's PrintTableTest already covers the empty-result message, the
sort/top ordering, and trailing-whitespace hygiene. test_findings_sink.py
already covers the sink recording every match regardless of `top` and the
exact entry dict a non-Match row produces (file, line 0, "(anon)", count 0,
empty metrics). This file covers what neither of those does: the exact
markdown shape of a rendered table (headers, separator, pipe escaping), the
optional header line, and the sink helper fallback paths that only a
duck-typed non-Match row exercises (`_sink_row_file`'s occurrences union,
`_sink_row_name`'s `.string` fallback, `_sink_entry`'s `count` field).

Run: python -m pytest tests/test_harness_render.py -q
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

from sniff import harness
from sniff.harness import render


def _render(matches, columns, **kw) -> str:
    """Call print_table and capture what it printed, as a single string."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        render.print_table(matches, columns, **kw)
    return buf.getvalue()


# Columns used across the shape tests: a name and a value that can carry a
# literal "|" to exercise the escaping rule.
_NAME_VALUE_COLUMNS = [("NAME", lambda m: m.name), ("VALUE", lambda m: m.value)]


class TableShapeTest(unittest.TestCase):
    """The exact markdown produced for a non-empty result set."""

    def test_header_and_separator_rows_match_the_given_columns(self):
        row = SimpleNamespace(name="fn", value="1")
        out = _render([row], _NAME_VALUE_COLUMNS)
        lines = out.splitlines()

        # Row 0 is the header, row 1 the plain '---' separator (no ':' markers,
        # since some strict renderers reject those), row 2 the one data row.
        self.assertEqual(lines[0], "| NAME | VALUE |")
        self.assertEqual(lines[1], "| --- | --- |")
        self.assertEqual(lines[2], "| fn | 1 |")

    def test_pipe_in_a_cell_is_escaped_so_the_table_does_not_break(self):
        # An unescaped '|' inside a cell would be read as an extra column
        # boundary by any markdown renderer.
        row = SimpleNamespace(name="a|b", value="1")
        out = _render([row], _NAME_VALUE_COLUMNS)
        self.assertIn("| a\\|b | 1 |", out)

    def test_optional_header_is_printed_above_the_table_with_a_blank_line(self):
        row = SimpleNamespace(name="fn", value="1")
        out = _render([row], _NAME_VALUE_COLUMNS, header="my-detector")
        lines = out.splitlines()
        self.assertEqual(lines[0], "my-detector")
        self.assertEqual(lines[1], "")
        self.assertEqual(lines[2], "| NAME | VALUE |")

    def test_no_header_means_the_table_starts_on_the_first_line(self):
        row = SimpleNamespace(name="fn", value="1")
        out = _render([row], _NAME_VALUE_COLUMNS)
        self.assertEqual(out.splitlines()[0], "| NAME | VALUE |")


class FmtTest(unittest.TestCase):
    """_fmt is the single place a cell value becomes display text."""

    def test_formats_by_plain_str_conversion(self):
        self.assertEqual(render._fmt(42), "42")
        self.assertEqual(render._fmt(None), "None")
        self.assertEqual(render._fmt("already-a-string"), "already-a-string")


class FindingsSinkTest(unittest.TestCase):
    """`harness.FINDINGS_SINK`: None means rendering-only.

    The list-installed case (records every match, not only the printed `top`,
    read through the package attribute rather than captured at import time) is
    already covered by test_findings_sink.py."""

    def setUp(self):
        # Save/restore the package attribute so this test can't leak state into
        # whatever runs after it in the same process.
        self._saved_sink = harness.FINDINGS_SINK
        self.addCleanup(setattr, harness, "FINDINGS_SINK", self._saved_sink)

    def test_default_sink_is_none_and_the_table_still_renders_correctly(self):
        # Rendering-only mode: no sink installed, but print_table must still do
        # its normal job (proves the None-sink branch does not short-circuit
        # the whole function, only the recording step).
        harness.FINDINGS_SINK = None
        row = SimpleNamespace(name="fn", value="1")
        out = _render([row], _NAME_VALUE_COLUMNS)
        self.assertIn("| fn | 1 |", out)


class SinkEntryTest(unittest.TestCase):
    """_sink_entry: how one printed row becomes one findings-sink record."""

    def test_reads_file_line_name_lines_and_metrics_directly(self):
        row = SimpleNamespace(file="a.py", line=7, name="big_fn", lines=42,
                              metrics={"params": 6})
        entry = render._sink_entry(row)
        self.assertEqual(entry, {
            "file": "a.py", "line": 7, "name": "big_fn",
            "lines": 42, "count": 0, "metrics": {"params": 6},
        })

    def test_reads_count_when_a_row_carries_a_per_file_count_instead_of_lines(self):
        row = SimpleNamespace(file="a.py", count=5)
        self.assertEqual(render._sink_entry(row)["count"], 5)

    def test_a_present_but_none_valued_line_or_lines_defaults_to_zero(self):
        # `getattr(row, "line", 0) or 0` has to catch None, not only a missing
        # attribute: a row that carries the field but leaves it unset (None)
        # takes the same `or 0` branch as a row that never had it at all.
        row = SimpleNamespace(file="a.py", line=None, lines=None)
        entry = render._sink_entry(row)
        self.assertEqual(entry["line"], 0)
        self.assertEqual(entry["lines"], 0)


class SinkRowFileTest(unittest.TestCase):
    """_sink_row_file: direct `.file`, or the union of a clone's `.occurrences`."""

    def test_uses_file_attribute_directly_when_present(self):
        row = SimpleNamespace(file="src/a.py")
        self.assertEqual(render._sink_row_file(row), "src/a.py")

    def test_falls_back_to_the_sorted_union_of_occurrence_files(self):
        # duplicate-code's Clone has no single `.file`; its identity is the set
        # of files the clone spans, joined so it survives edits elsewhere.
        row = SimpleNamespace(occurrences=[
            SimpleNamespace(file="b.py"), SimpleNamespace(file="a.py"),
        ])
        self.assertEqual(render._sink_row_file(row), "a.py+b.py")

    def test_no_file_and_no_occurrences_is_an_empty_string(self):
        row = SimpleNamespace()
        self.assertEqual(render._sink_row_file(row), "")


class SinkRowNameTest(unittest.TestCase):
    """_sink_row_name: `.name`, else `.string` (no-duplicate-string), else '(anon)'."""

    def test_uses_name_attribute_when_present(self):
        row = SimpleNamespace(name="big_fn", string="unused")
        self.assertEqual(render._sink_row_name(row), "big_fn")

    def test_falls_back_to_string_attribute_when_name_is_absent(self):
        row = SimpleNamespace(string="a duplicated literal")
        self.assertEqual(render._sink_row_name(row), "a duplicated literal")

    def test_falls_back_to_anon_when_neither_is_present(self):
        row = SimpleNamespace(file="a.py")
        self.assertEqual(render._sink_row_name(row), "(anon)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
