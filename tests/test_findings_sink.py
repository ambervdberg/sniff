"""Tests for the harness findings sink used by baseline/diff."""

import io
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
