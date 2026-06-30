#!/usr/bin/env python3
"""Tests for LLM-facing sniff CLI help and detector list output."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.join(HERE, "run.py")


class SniffCliHelpTest(unittest.TestCase):
    """Verify LLM-facing sniff CLI help stays explicit."""

    def _run(self, *args: str) -> str:
        """Run the sniff CLI script and return stdout."""
        proc = subprocess.run([sys.executable, RUN, *args], capture_output=True, text=True, check=True)
        return proc.stdout

    def test_help_names_default_and_has_no_all_flag(self):
        """Help states the no-flag default and rejects a fictional --all flag."""
        out = self._run("--help")
        self.assertIn("Default: `sniff [DIR]` runs all detectors; there is no `--all` flag.", out)
        self.assertIn("Pattern rules only:  sniff --only sniff-patterns [DIR]", out)

    def test_list_shows_run_command_for_each_detector(self):
        """Detector list includes copyable run commands for routing."""
        out = self._run("--list")
        self.assertIn("| DETECTOR | TITLE | RUN |", out)
        self.assertIn("| sniff-patterns |", out)
        self.assertIn("`sniff --only sniff-patterns [DIR]`", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)