#!/usr/bin/env python3
"""Tests for how sniff runs an external (subprocess) detector.

An external detector is a script the scanned repo supplies, so sniff cannot
assume it terminates. The timeout is the guard that keeps one wedged detector
from hanging a scan, and with it any CI job gating on `sniff diff`.

Run: python -m pytest tests/test_execution.py -q
"""

from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock

from sniff import discovery, execution

from conftest import write_tree_file


def _hanging_detector(script_dir: str) -> discovery.Detector:
    """An external detector whose script prints, then never returns."""
    script = write_tree_file(script_dir, "hang.py", """
        import sys, time
        print("partial output")
        sys.stdout.flush()
        time.sleep(600)
    """)
    return discovery.Detector(name="hangs", title="Hangs forever", script=script)


class ExternalDetectorTimeoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.detector = _hanging_detector(self.tmp.name)

    def _run_with_short_timeout(self) -> dict:
        # 2 seconds, not the shipped 300: the point is that the guard fires at all,
        # and the suite should not wait five minutes to learn it.
        with unittest.mock.patch.object(execution, "DETECTOR_TIMEOUT_SECONDS", 2):
            return execution.run_detector_json(self.detector, os.path.dirname(__file__))

    def test_a_wedged_detector_is_killed_rather_than_hanging_the_scan(self):
        result = self._run_with_short_timeout()
        self.assertIn("timed out", result["error"])

    def test_a_timed_out_detector_counts_as_a_failed_one(self):
        """It must flip the scan's exit code: a detector that never answered is
        not a detector that found nothing."""
        self.assertTrue(execution._detector_failed(self._run_with_short_timeout()))


if __name__ == "__main__":
    unittest.main()
