#!/usr/bin/env python3
"""Unit tests for hooks/prime.py, the SessionStart wrapper around `sniff prime`.

The wrapper exists because plugin users may not have the PyPI CLI installed and
neither host offers an install-time hook. Tier order is the contract under test:

1. `sniff` on PATH runs directly.
2. Otherwise `uvx` runs the package pinned to the plugin's own version — pinned,
   never `@latest`, so the CLI always matches the skills that shipped with it
   and cached runs stay offline-safe.
3. Otherwise a one-line install hint, and always exit 0: a missing optional tool
   must never fail the hook and block the session.

Run: python -m pytest tests/test_prime_hook.py
"""

from __future__ import annotations

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(PLUGIN_ROOT, "hooks"))

import prime


def _which(available: set[str]):
    """A shutil.which stand-in that knows only the given commands."""
    return lambda name: f"/fake/bin/{name}" if name in available else None


class PrimeHookTierTest(unittest.TestCase):
    def test_installed_cli_is_preferred(self):
        with mock.patch.object(prime.shutil, "which", _which({"sniff", "uvx"})), \
                mock.patch.object(prime.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.assertEqual(prime.main(), 0)
        run.assert_called_once_with(["sniff", "prime"])

    def test_uvx_fallback_pins_the_plugin_version(self):
        with mock.patch.object(prime.shutil, "which", _which({"uvx"})), \
                mock.patch.object(prime.subprocess, "run") as run, \
                redirect_stdout(io.StringIO()):
            run.return_value = mock.Mock(returncode=0)
            self.assertEqual(prime.main(), 0)

        command = run.call_args[0][0]
        pinned = f"sniff-smells=={prime.plugin_version()}"
        self.assertEqual(command, ["uvx", "--from", pinned, "sniff", "prime"])
        self.assertNotIn("latest", " ".join(command))

    def test_uvx_failure_degrades_to_the_hint_and_exit_zero(self):
        """Offline, or the pinned version is not on PyPI yet: hint, never an error."""
        out = io.StringIO()
        with mock.patch.object(prime.shutil, "which", _which({"uvx"})), \
                mock.patch.object(prime.subprocess, "run") as run, \
                redirect_stdout(out):
            run.return_value = mock.Mock(returncode=1)
            self.assertEqual(prime.main(), 0)
        self.assertIn("uv tool install sniff-smells", out.getvalue())

    def test_nothing_installed_prints_hint_and_exit_zero(self):
        out = io.StringIO()
        with mock.patch.object(prime.shutil, "which", _which(set())), redirect_stdout(out):
            self.assertEqual(prime.main(), 0)
        self.assertIn("uv tool install sniff-smells", out.getvalue())
        self.assertIn("pip install sniff-smells", out.getvalue())

    def test_pin_source_is_the_plugin_manifest(self):
        """The pin must come from the plugin's own plugin.json, nowhere else."""
        import json

        with open(os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            self.assertEqual(prime.plugin_version(), json.load(fh)["version"])


if __name__ == "__main__":
    unittest.main()
