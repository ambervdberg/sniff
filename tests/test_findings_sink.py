"""Tests for the harness findings sink used by baseline/diff."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from sniff import harness
from sniff.harness import Match


def make_match(file: str, name: str, **metrics) -> Match:
    return Match(
        file=file, start_line=9, end_line=20, byte_start=0, byte_end=1,
        name=name, text="", metrics=dict(metrics),
    )


class FindingsSinkTest(unittest.TestCase):
    def tearDown(self):
        harness.FINDINGS_SINK = None

    def _print_two_matches_top_one(self):
        matches = [
            make_match("a.py", "big", params=8),
            make_match("b.py", "small", params=2),
        ]
        with redirect_stdout(io.StringIO()):
            harness.print_table(
                matches,
                columns=[("PARAMS", lambda m: m.metrics["params"])],
                sort_key=lambda m: -m.metrics["params"],
                top=1,
                header="Most parameters: 1 of 2 functions:",
            )

    def test_sink_disabled_by_default(self):
        self._print_two_matches_top_one()  # must not raise, sink is None

    def test_sink_records_all_matches_not_just_top_n(self):
        harness.FINDINGS_SINK = []
        self._print_two_matches_top_one()
        self.assertEqual(len(harness.FINDINGS_SINK), 2)
        recorded = {f["name"] for f in harness.FINDINGS_SINK}
        self.assertEqual(recorded, {"big", "small"})

    def test_sink_entry_shape(self):
        harness.FINDINGS_SINK = []
        self._print_two_matches_top_one()
        entry = next(f for f in harness.FINDINGS_SINK if f["name"] == "big")
        self.assertEqual(entry["file"], "a.py")
        self.assertEqual(entry["line"], 10)  # 0-based start_line 9 -> 1-based 10
        self.assertEqual(entry["metrics"], {"params": 8})
        self.assertEqual(entry["lines"], 12)  # start_line 9 .. end_line 20

    def test_sink_records_rows_that_are_not_matches(self):
        """Half the detectors print their own row dataclass, not a Match.

        largest-files hands print_table a FileStat, duplicate-code a Clone, and
        so on. None of those carry a line, a name, or a metrics dict, so the
        sink has to read every field defensively or a gated scan crashes."""
        from dataclasses import dataclass

        @dataclass
        class FileStat:
            file: str
            lines: int

        harness.FINDINGS_SINK = []
        with redirect_stdout(io.StringIO()):
            harness.print_table(
                [FileStat(file="big.py", lines=500)],
                columns=[("LINES", lambda s: s.lines), ("FILE", lambda s: s.file)],
            )

        self.assertEqual(harness.FINDINGS_SINK, [{
            "file": "big.py", "line": 0, "name": "(anon)",
            "lines": 500, "count": 0, "metrics": {},
        }])


class PatternsSinkTest(unittest.TestCase):
    """Run the real sniff-patterns detector in-process over a tiny fixture
    and assert its findings reach harness.FINDINGS_SINK."""

    def tearDown(self):
        harness.FINDINGS_SINK = None

    def test_pattern_findings_reach_sink(self):
        from sniff import patterns_detector

        with tempfile.TemporaryDirectory() as tmp:
            # py-print-statement is a stock rule; a bare print() trips it.
            with open(os.path.join(tmp, "app.py"), "w", encoding="utf-8") as fh:
                fh.write("print('hi')\n")

            harness.FINDINGS_SINK = []
            with redirect_stdout(io.StringIO()):
                patterns_detector.main([tmp])

            rules = {f["metrics"]["rule"] for f in harness.FINDINGS_SINK}
            self.assertIn("py-print-statement", rules)
            hit = next(f for f in harness.FINDINGS_SINK
                       if f["metrics"]["rule"] == "py-print-statement")
            # Raw, root-prefixed, like every other detector's sink entry: the
            # gate is the single place that relativizes to the scan root (see
            # gate._relative_file), not the detector itself. ast-grep's raw
            # path uses the platform's own separators, hence normpath here.
            self.assertEqual(os.path.normpath(hit["file"]), os.path.normpath(os.path.join(tmp, "app.py")))
            self.assertEqual(hit["line"], 1)
            self.assertEqual(hit["name"], "py-print-statement")
