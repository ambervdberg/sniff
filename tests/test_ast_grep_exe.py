#!/usr/bin/env python3
"""Regression tests: every ast-grep subprocess call must use the resolved executable.

On Windows the npm-installed binary is an `ast-grep.cmd` shim, which CreateProcess
does not find from a bare argv[0] (WinError 2). shutil.which does apply PATHEXT, so
every call site must pass its result instead of the literal "ast-grep".

Run: python tests/test_ast_grep_exe.py
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

FORMAT = os.path.join(REPO_ROOT, "src", "sniff", "patterns", "format.py")

from sniff import harness, rules_testing  # pylint: disable=wrong-import-position

# format.py is also run standalone, so it is loaded by path like the catalog test does.
_spec = importlib.util.spec_from_file_location("format_mod", FORMAT)
format_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(format_mod)

SENTINEL = r"C:\fake\path\ast-grep.cmd"


def _completed(args) -> subprocess.CompletedProcess:
    """A successful, empty-output result so callers proceed without a real binary."""
    return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


class AstGrepExeTest(unittest.TestCase):
    def test_harness_resolves_via_which(self):
        with mock.patch.object(harness.shutil, "which", return_value=SENTINEL):
            self.assertEqual(harness.ast_grep_exe(), SENTINEL)

    def test_harness_falls_back_to_bare_name(self):
        with mock.patch.object(harness.shutil, "which", return_value=None):
            self.assertEqual(harness.ast_grep_exe(), "ast-grep")

    def test_format_resolves_via_which(self):
        with mock.patch.object(format_mod.shutil, "which", return_value=SENTINEL):
            self.assertEqual(format_mod.ast_grep_exe(), SENTINEL)


class CallSiteTest(unittest.TestCase):
    """Each subprocess call site must put the resolved path in argv[0]."""

    def _argv0_of(self, module, run_call) -> str:
        captured = {}

        def fake_run(cmd, **kwargs):  # pylint: disable=unused-argument
            captured["cmd"] = cmd
            return _completed(cmd)

        with mock.patch.object(harness.shutil, "which", return_value=SENTINEL), \
             mock.patch.object(module.shutil, "which", return_value=SENTINEL), \
             mock.patch.object(module.subprocess, "run", fake_run):
            run_call()

        return captured["cmd"][0]

    def test_rules_testing_uses_resolved_path(self):
        argv0 = self._argv0_of(rules_testing, lambda: rules_testing.run_test_rules(REPO_ROOT))
        self.assertEqual(argv0, SENTINEL)

    def test_harness_scan_uses_resolved_path(self):
        argv0 = self._argv0_of(
            harness,
            lambda: harness._scan(REPO_ROOT, "python", "id: x\nlanguage: python\nrule:\n  kind: module\n"),
        )
        self.assertEqual(argv0, SENTINEL)

    def test_format_scan_uses_resolved_path(self):
        argv0 = self._argv0_of(format_mod, lambda: format_mod.run_scan(REPO_ROOT))
        self.assertEqual(argv0, SENTINEL)


if __name__ == "__main__":
    unittest.main()
