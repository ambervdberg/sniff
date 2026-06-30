#!/usr/bin/env python3
"""Tests for LLM-facing sniff CLI help and detector list output."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "run.py")


class SniffCliHelpTest(unittest.TestCase):
    """Verify LLM-facing sniff CLI help stays explicit."""

    def _run(self, *args: str) -> str:
        """Run the sniff CLI script and return stdout."""
        proc = subprocess.run([sys.executable, RUN, *args], capture_output=True, text=True, check=True)
        return proc.stdout

    def test_help_names_default_and_all_flag(self):
        """Help states the no-flag default and the --all alias."""
        out = self._run("--help")
        self.assertIn("Default: `sniff [DIR]` runs all detectors; `--all` is accepted as an explicit alias.", out)
        self.assertIn("Pattern rules only:  sniff --only sniff-patterns [DIR]", out)

    def test_list_shows_run_command_for_each_detector(self):
        """Detector list includes copyable run commands for routing."""
        out = self._run("--list")
        self.assertIn("| DETECTOR | TITLE | RUN |", out)
        self.assertIn("| sniff-patterns |", out)
        self.assertIn("`sniff --only sniff-patterns [DIR]`", out)


class SniffHallucinatedFlagHintTest(unittest.TestCase):
    """A known-hallucinated flag prints a corrective hint before argparse errors out."""

    def _run_stderr(self, *args: str) -> str:
        proc = subprocess.run([sys.executable, RUN, *args], capture_output=True, text=True)
        return proc.stderr

    def test_unknown_flag_prints_hint(self):
        err = self._run_stderr("--detectors", "largest-methods")
        self.assertIn("hint: '--detectors' is not a sniff flag.", err)
        self.assertIn("--only <names>", err)

    def test_unrecognized_flag_without_hint_still_errors_normally(self):
        err = self._run_stderr("--bogus-flag")
        self.assertNotIn("hint:", err)
        self.assertIn("unrecognized arguments", err)


class SniffVersionCommandTest(unittest.TestCase):
    """`sniff version` prints a version string and exits 0."""

    def test_version_prints_version_string(self):
        proc = subprocess.run([sys.executable, RUN, "version"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertRegex(proc.stdout.strip(), r"^sniff \S+$")


class SniffDoctorCommandTest(unittest.TestCase):
    """`sniff doctor` checks prerequisites and exits 0/1 based on the result."""

    def test_doctor_reports_python_and_manifest_checks(self):
        proc = subprocess.run([sys.executable, RUN, "doctor"], capture_output=True, text=True)
        self.assertIn(proc.returncode, (0, 1))
        self.assertIn("python", proc.stdout)
        self.assertIn("detector manifest(s) valid", proc.stdout)
        self.assertIn("duplicate detector name", proc.stdout)


class SniffJsonOutputTest(unittest.TestCase):
    """--json emits parseable JSON for both --list and a scan, markdown stays default."""

    def test_list_json_is_parseable_detector_array(self):
        proc = subprocess.run([sys.executable, RUN, "--list", "--json"], capture_output=True, text=True, check=True)
        data = json.loads(proc.stdout)
        self.assertIsInstance(data, list)
        names = {d["name"] for d in data}
        self.assertIn("sniff-patterns", names)
        self.assertIn("script", data[0])

    def test_scan_json_is_parseable_per_detector(self):
        proc = subprocess.run(
            [sys.executable, RUN, "--json", "--only", "sniff-patterns", "."],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(proc.stdout)
        self.assertEqual(data["path"], ".")
        self.assertEqual(len(data["detectors"]), 1)
        self.assertEqual(data["detectors"][0]["detector"], "sniff-patterns")
        self.assertIn("exit_code", data["detectors"][0])

    def test_default_markdown_output_unchanged_without_json_flag(self):
        proc = subprocess.run(
            [sys.executable, RUN, "--only", "sniff-patterns", "."],
            capture_output=True, text=True, check=True,
        )
        self.assertTrue(proc.stdout.startswith("sniff: 1 detectors over"))
        self.assertIn("## sniff-patterns", proc.stdout)


class SniffPrimeCommandTest(unittest.TestCase):
    """`sniff prime` prints agent context without running a scan."""

    def test_prime_includes_version_detectors_commands_caveats_no_scan(self):
        proc = subprocess.run([sys.executable, RUN, "prime"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.startswith("sniff "))
        self.assertIn("PREREQUISITES", proc.stdout)
        self.assertIn("DETECTORS (", proc.stdout)
        self.assertIn("sniff-patterns:", proc.stdout)
        self.assertIn("COMMON COMMANDS", proc.stdout)
        self.assertIn("CAVEATS", proc.stdout)
        # No scan output (per-detector "## name" markdown sections) should appear.
        self.assertNotIn("## sniff-patterns", proc.stdout)


class SniffBaselineDiffTest(unittest.TestCase):
    """`sniff baseline write` saves counts; `sniff diff` compares against them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "a.py"), "w", encoding="utf-8") as fh:
            fh.write("def foo(a, b, c, d, e, f, g):\n    pass\n")

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, RUN, *args], capture_output=True, text=True)

    def test_baseline_write_saves_json_file(self):
        proc = self._run("baseline", "write", self.tmp)
        self.assertEqual(proc.returncode, 0)
        baseline_path = os.path.join(self.tmp, ".sniff", "baseline.json")
        self.assertTrue(os.path.isfile(baseline_path))
        with open(baseline_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("most-parameters", data["counts"])

    def test_diff_without_baseline_errors(self):
        proc = self._run("diff", self.tmp)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no baseline", proc.stderr)

    def test_diff_reports_same_or_better_when_unchanged(self):
        self._run("baseline", "write", self.tmp)
        proc = self._run("diff", self.tmp)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("same or better", proc.stdout)

    def test_diff_detects_regression(self):
        self._run("baseline", "write", self.tmp)
        with open(os.path.join(self.tmp, "a.py"), "a", encoding="utf-8") as fh:
            fh.write("\ndef bar(a, b, c, d, e, f, g, h):\n    pass\n")
        proc = self._run("diff", self.tmp)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("worse", proc.stdout)
        self.assertIn("+1", proc.stdout)


class SniffMissingDirTest(unittest.TestCase):
    """A nonexistent DIR fails fast with a hint instead of running every detector."""

    def test_nonexistent_dir_errors_without_running_detectors(self):
        proc = subprocess.run([sys.executable, RUN, "/no/such/dir"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("is not a directory", proc.stderr)
        self.assertNotIn("## ", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
