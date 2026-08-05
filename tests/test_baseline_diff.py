#!/usr/bin/env python3
"""Tests for `sniff baseline write` and `sniff diff`: the regression gate.

These drive `run_baseline` and `run_diff` directly with a stubbed fingerprint
scan, so every case is about the *comparison*: which fingerprint counts as a
regression, which as an improvement, and what the exit code says. The
end-to-end coverage in test_cli.py runs the real detectors instead.

The gate is the one command whose silent failure turns a red PR green, so the
fail-closed cases below matter as much as the arithmetic ones.

Run: python -m pytest tests/test_baseline_diff.py -q
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from sniff import gate
from sniff.commands import baseline_diff


def write_baseline(root: str, fingerprints: dict, version: int = 3) -> str:
    """Write a baseline.json under `root` and return its path."""
    baseline_dir = os.path.join(root, ".sniff")
    os.makedirs(baseline_dir, exist_ok=True)
    path = os.path.join(baseline_dir, "baseline.json")
    payload = {"version": version, "path": root, "fingerprints": fingerprints}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


@contextlib.contextmanager
def scanning(current: dict = None, failure: str = None):
    """Stub the fingerprint scan: either it returns `current`, or it fails.

    Detector discovery is stubbed out with it, since what the gate compares is
    the fingerprints, not how the detector list was assembled."""
    scan = mock.patch(
        "sniff.gate.scan_fingerprints",
        side_effect=gate.DetectorFailure(failure) if failure else None,
        return_value=current or {},
    )
    detectors = mock.patch.object(baseline_diff, "_configured_detectors", return_value=[])
    with scan, detectors:
        yield


def run(command, *argv) -> tuple[int, str, str]:
    """Call a command with argv -> (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = command(list(argv))
    return code, out.getvalue(), err.getvalue()


class BaselineWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_missing_write_subcommand_is_a_usage_error(self):
        code, _out, err = run(baseline_diff.run_baseline)
        self.assertEqual(code, 1)
        self.assertIn("usage: sniff baseline write", err)

    def test_unknown_subcommand_is_a_usage_error(self):
        code, _out, err = run(baseline_diff.run_baseline, "read", self.repo)
        self.assertEqual(code, 1)
        self.assertIn("usage: sniff baseline write", err)

    def test_non_directory_path_errors(self):
        missing = os.path.join(self.repo, "nope")
        code, _out, err = run(baseline_diff.run_baseline, "write", missing)
        self.assertEqual(code, 1)
        self.assertIn("is not a directory", err)

    def test_write_saves_current_fingerprints_as_version_3(self):
        current = {"largest-methods": {"a.py|big": 90}}
        with scanning(current):
            code, out, _err = run(baseline_diff.run_baseline, "write", self.repo)

        self.assertEqual(code, 0)
        with open(os.path.join(self.repo, ".sniff", "baseline.json"), encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["version"], 3)
        self.assertEqual(saved["fingerprints"], current)
        self.assertIn("baseline written", out)

    def test_a_failing_detector_writes_no_baseline(self):
        # A baseline saved from a partial scan would bake the missing detector's
        # violations in as "already fine" for every later diff.
        with scanning(failure="detector 'largest-methods' failed: boom"):
            code, _out, err = run(baseline_diff.run_baseline, "write", self.repo)

        self.assertEqual(code, 1)
        self.assertIn("boom", err)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".sniff", "baseline.json")))


class DiffComparisonTest(unittest.TestCase):
    """What counts as a regression, an improvement, and neither."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def diff(self, baseline: dict, current: dict) -> tuple[int, str, str]:
        write_baseline(self.repo, baseline)
        with scanning(current):
            return run(baseline_diff.run_diff, self.repo)

    def test_unchanged_fingerprint_is_not_a_regression(self):
        same = {"cyclomatic-complexity": {"a.py|fn": 12}}
        code, out, _err = self.diff(same, same)
        self.assertEqual(code, 0)
        self.assertIn("same or better", out)

    def test_new_fingerprint_is_a_regression(self):
        code, out, _err = self.diff(
            {"cyclomatic-complexity": {"a.py|fn": 12}},
            {"cyclomatic-complexity": {"a.py|fn": 12, "b.py|other": 11}},
        )
        self.assertEqual(code, 1)
        self.assertIn("cyclomatic-complexity", out)
        self.assertIn("b.py|other", out)
        self.assertIn("1 new violation(s)", out)

    def test_worsened_value_on_an_existing_fingerprint_is_a_regression(self):
        # Same entity, worse number: without comparing values this would read as
        # unchanged and a function rotting in place would pass the gate forever.
        code, out, _err = self.diff(
            {"cognitive-complexity": {"a.py|fn": 15}},
            {"cognitive-complexity": {"a.py|fn": 22}},
        )
        self.assertEqual(code, 1)
        self.assertIn("a.py|fn", out)

    def test_improved_value_is_not_a_regression(self):
        code, out, _err = self.diff(
            {"cognitive-complexity": {"a.py|fn": 22}},
            {"cognitive-complexity": {"a.py|fn": 15}},
        )
        self.assertEqual(code, 0)
        self.assertIn("same or better (1 improvement(s))", out)

    def test_removed_fingerprint_counts_as_an_improvement(self):
        code, out, _err = self.diff(
            {"largest-methods": {"a.py|big": 90}},
            {"largest-methods": {}},
        )
        self.assertEqual(code, 0)
        self.assertIn("1 improvement(s)", out)

    def test_a_detector_absent_from_the_baseline_still_gates(self):
        # A detector added since the baseline was written must not get its
        # existing violations waved through as pre-existing.
        code, out, _err = self.diff({}, {"most-imports": {"a.py": 30}})
        self.assertEqual(code, 1)
        self.assertIn("most-imports", out)

    def test_improvements_and_regressions_are_counted_together(self):
        code, out, _err = self.diff(
            {"largest-methods": {"a.py|old": 90}},
            {"largest-methods": {"b.py|new": 80}},
        )
        self.assertEqual(code, 1)
        self.assertIn("1 new violation(s), 1 improvement(s)", out)

    def test_clean_growth_without_violations_is_not_a_regression(self):
        code, out, _err = self.diff(
            {"cyclomatic-complexity": {"a.py|fn": 12}},
            {"cyclomatic-complexity": {"a.py|fn": 12}, "largest-files": {}},
        )
        self.assertEqual(code, 0)
        self.assertIn("same or better", out)


class DiffFailClosedTest(unittest.TestCase):
    """Every way the gate can fail to know the answer must exit non-zero."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def test_non_directory_path_errors(self):
        code, _out, err = run(baseline_diff.run_diff, os.path.join(self.repo, "nope"))
        self.assertEqual(code, 1)
        self.assertIn("is not a directory", err)

    def test_missing_baseline_errors_with_the_write_command(self):
        code, _out, err = run(baseline_diff.run_diff, self.repo)
        self.assertEqual(code, 1)
        self.assertIn("no baseline", err)
        self.assertIn("sniff baseline write", err)

    def test_older_baseline_format_is_rejected(self):
        write_baseline(self.repo, {"largest-methods": {"a.py|big": 90}}, version=2)
        with scanning({}):
            code, _out, err = run(baseline_diff.run_diff, self.repo)
        self.assertEqual(code, 1)
        self.assertIn("old format", err)

    def test_a_failing_detector_fails_the_diff(self):
        # The whole point of the gate: a detector that could not run is not the
        # same as a clean repo, so it must never print "same or better".
        write_baseline(self.repo, {"largest-methods": {"a.py|big": 90}})
        with scanning(failure="detector 'largest-methods' failed: no ast-grep"):
            code, out, err = run(baseline_diff.run_diff, self.repo)

        self.assertEqual(code, 1)
        self.assertIn("no ast-grep", err)
        self.assertNotIn("same or better", out)


class DiffCommentTest(unittest.TestCase):
    """`--comment` renders the same verdict as markdown."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.addCleanup(self.tmp.cleanup)

    def diff(self, baseline: dict, current: dict) -> tuple[int, str, str]:
        write_baseline(self.repo, baseline)
        with scanning(current):
            return run(baseline_diff.run_diff, "--comment", self.repo)

    def test_clean_diff_renders_a_same_or_better_verdict(self):
        same = {"largest-methods": {"a.py|big": 90}}
        code, out, _err = self.diff(same, same)
        self.assertEqual(code, 0)
        self.assertIn("| largest-methods | 0 |", out)
        self.assertIn("**same or better**", out)

    def test_regression_renders_a_worse_verdict(self):
        code, out, _err = self.diff(
            {"largest-methods": {}},
            {"largest-methods": {"a.py|big": 90}},
        )
        self.assertEqual(code, 1)
        self.assertIn("| largest-methods | 1 | a.py|big |", out)
        self.assertIn("**worse**", out)

    def test_long_violation_lists_are_truncated(self):
        # An unbounded list would make a PR comment unreadable.
        current = {"largest-methods": {f"a.py|fn{i}": 90 for i in range(8)}}
        code, out, _err = self.diff({"largest-methods": {}}, current)

        self.assertEqual(code, 1)
        self.assertIn("+3 more", out)
        self.assertNotIn("a.py|fn7", out)


if __name__ == "__main__":
    unittest.main()
