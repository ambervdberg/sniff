#!/usr/bin/env python3
"""Tests for sniff.commands.doctor: `sniff doctor`'s prerequisite checklist.

`run_doctor()` reads the real environment (Python version, ast-grep on PATH,
detector discovery, the cwd's `.sniff/rules` and `.sniff.toml`), so every test
here chdirs into a scratch directory first: running from the repo root would
pick up this repo's own `.sniff.toml` and make the assertions depend on
whatever that file happens to contain.

Run: python -m pytest tests/test_commands_doctor.py -q
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from sniff import discovery
from sniff.commands import doctor


class DoctorTestCase(unittest.TestCase):
    """Shared setup: an isolated cwd so doctor's cwd-relative checks are hermetic."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.original_cwd)

    def run_doctor(self) -> tuple[int, str]:
        """Call run_doctor(), returning (exit code, everything it printed)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = doctor.run_doctor()
        return code, out.getvalue()


class PrerequisitesPassTest(DoctorTestCase):
    def test_every_check_passing_returns_zero(self):
        # No .sniff/detectors manifests and no .sniff/rules in the scratch cwd,
        # so discovery finds only the built-ins with no errors or duplicates.
        with mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/ast-grep"):
            code, out = self.run_doctor()

        self.assertEqual(code, 0)
        # A regex with a nonzero count, not a bare "PASS" substring check: an
        # empty detector list ("PASS 0 detector manifest(s) valid") would also
        # contain "PASS" and pass for the wrong reason.
        self.assertRegex(out, r"PASS [1-9]\d* detector manifest\(s\) valid")
        self.assertIn("PASS ast-grep found on PATH", out)
        self.assertIn("PASS no duplicate detector names", out)


class MissingPrerequisiteTest(DoctorTestCase):
    """The acceptance case: a missing prerequisite fails the gate."""

    def test_missing_ast_grep_exits_non_zero(self):
        with mock.patch.object(doctor.shutil, "which", return_value=None):
            code, out = self.run_doctor()

        self.assertEqual(code, 1)
        self.assertIn("FAIL ast-grep not found on PATH", out)

    def test_python_below_the_floor_exits_non_zero(self):
        # Must track requires-python in pyproject.toml: PASSing an interpreter
        # pip would already have refused to install sniff on would be worse
        # than the check not existing at all.
        too_old = (3, 9, 0, "final", 0)
        with mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/ast-grep"), \
                mock.patch.object(doctor.sys, "version_info", too_old):
            code, out = self.run_doctor()

        self.assertEqual(code, 1)
        self.assertIn("FAIL python 3.9.0", out)


class ManifestAndDuplicateChecksTest(DoctorTestCase):
    """discover()'s errors and duplicate detector names both fail the gate."""

    def test_a_manifest_error_exits_non_zero(self):
        broken = ["bad-detector: script not found: /nope.py"]
        with mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/ast-grep"), \
                mock.patch.object(discovery, "discover", return_value=([], broken)):
            code, out = self.run_doctor()

        self.assertEqual(code, 1)
        self.assertIn("FAIL manifest: bad-detector: script not found: /nope.py", out)

    def test_duplicate_detector_names_exit_non_zero(self):
        dupes = [discovery.Detector(name="alpha", title="one"),
                  discovery.Detector(name="alpha", title="two")]
        with mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/ast-grep"), \
                mock.patch.object(discovery, "discover", return_value=(dupes, [])):
            code, out = self.run_doctor()

        self.assertEqual(code, 1)
        self.assertIn("FAIL duplicate detector name(s): alpha", out)


class LocalRuleShadowTest(DoctorTestCase):
    """A local .sniff/rules file with the same id as a core rule only warns."""

    def test_shadowing_rule_id_prints_a_warning_without_failing_the_gate(self):
        core_rules = os.path.join(self.tmp.name, "core-rules")
        os.makedirs(core_rules)
        with open(os.path.join(core_rules, "no-console.yml"), "w", encoding="utf-8") as fh:
            fh.write("id: no-console\n")

        local_rules = os.path.join(self.tmp.name, ".sniff", "rules")
        os.makedirs(local_rules)
        with open(os.path.join(local_rules, "no-console.yml"), "w", encoding="utf-8") as fh:
            fh.write("id: no-console\n")
        # A second local rule with no core twin: proves the warning fires on
        # the *intersection* of local and core ids, not on "any local rule
        # exists". Without this file, `sorted(local_ids)` (dropping `& core_ids`
        # entirely) would still warn about no-console and the test would miss it.
        with open(os.path.join(local_rules, "my-own-rule.yml"), "w", encoding="utf-8") as fh:
            fh.write("id: my-own-rule\n")

        with mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/ast-grep"), \
                mock.patch.object(doctor.patterns, "rules_dir", return_value=core_rules):
            code, out = self.run_doctor()

        # A shadowed rule is a nudge to contribute it upstream, not a failure:
        # every other check in the scratch cwd still passes.
        self.assertEqual(code, 0)
        self.assertIn("WARN local rule 'no-console' shadows core rule", out)
        self.assertNotIn("my-own-rule", out)


class SniffTomlCheckTest(DoctorTestCase):
    """A .sniff.toml in the cwd is validated and reported PASS or WARN."""

    def test_valid_sniff_toml_passes(self):
        with open(".sniff.toml", "w", encoding="utf-8") as fh:
            fh.write('[detectors]\nskip = "largest-files"\n')

        with mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/ast-grep"):
            code, out = self.run_doctor()

        self.assertEqual(code, 0)
        self.assertIn("PASS .sniff.toml valid", out)

    def test_unparseable_line_warns_without_failing_the_gate(self):
        with open(".sniff.toml", "w", encoding="utf-8") as fh:
            fh.write("this is not a key value line\n")

        with mock.patch.object(doctor.shutil, "which", return_value="/usr/bin/ast-grep"):
            code, out = self.run_doctor()

        self.assertEqual(code, 0)
        self.assertIn("WARN", out)
        self.assertIn("cannot parse line", out)


if __name__ == "__main__":
    unittest.main()
