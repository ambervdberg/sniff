#!/usr/bin/env python3
"""Tests for `run_detector_json`: the one path both a built-in (in-process) and
an external (subprocess) detector funnel through.

An external detector is a script the scanned repo supplies, so sniff cannot
assume it terminates. The timeout is the guard that keeps one wedged detector
from hanging a scan, and with it any CI job gating on `sniff diff`. Alongside
that, this file covers the shape `run_detector_json` must produce either way:
a built-in's stdout captured in-process, an external script's stdout captured
from its subprocess, and a non-zero exit (either path) reported as a failed
detector rather than dropped.

Run: python -m pytest tests/test_execution.py -q
"""

from __future__ import annotations

import os
import tempfile
import unittest
import unittest.mock

from sniff import discovery, execution, harness
from sniff.detectors import self_admitted_debt

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

    def test_a_timed_out_detector_has_an_empty_findings_list(self):
        # A subprocess (whether it timed out or not) has no in-process sink for
        # its structured rows to land in, so findings is always empty for it.
        self.assertEqual(self._run_with_short_timeout()["findings"], [])


def _todo_file_tree(root: str) -> str:
    """A tiny tree with one file carrying a TODO marker, for the
    self-admitted-debt detector to find. That detector needs no external
    parser (NEEDS_AST_GREP is False), which makes it the plainest built-in
    for exercising the in-process run path without an ast-grep dependency.
    Returns the file's own path, so a test can assert the scan actually
    found it by name rather than just matching a generic word like "TODO"."""
    return write_tree_file(root, "app.py", """
        # TODO: replace this stub with a real implementation
        def stub():
            pass
    """)


class _StubModule:
    """A fake detector module: only `.main` is ever read off a real one, so
    this is enough to drive `_run_module_detector` through exit-code shapes
    a real built-in would rarely hit on demand (a bare int return, a hard
    `SystemExit(int)`), without depending on any specific built-in's logic."""

    def __init__(self, main):
        self.main = main


def _main_returns_2(argv: "list[str]") -> int:
    """A stub `main()` that reports failure by returning an int, the other
    legal shape besides raising SystemExit."""
    return 2


def _main_raises_system_exit_3(argv: "list[str]") -> int:
    """A stub `main()` that reports failure by raising `SystemExit(3)`, the
    "hard exit" shape, distinct from the string-message usage-error shape
    covered separately below."""
    raise SystemExit(3)


class BuiltinDetectorInProcessTest(unittest.TestCase):
    """A built-in detector runs via `detector.module.main(...)` in-process, not
    as a subprocess, so its output has to be captured by redirecting stdout.

    `setUp` makes that "not as a subprocess" claim load-bearing: it patches
    `subprocess.run` to blow up, so any code path that routed a builtin
    through it would fail every test in this class instead of quietly
    passing on real subprocess output."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.todo_file = _todo_file_tree(self.tmp.name)

        # Patches the `subprocess` name as seen from inside execution.py only
        # (a rebind of that one module attribute), not the shared subprocess
        # module everything else imports. A blanket patch on subprocess.run
        # itself also breaks self-admitted-debt's own git ls-files call and
        # every other detector's internal subprocess use, which has nothing
        # to do with what run_detector_json chose for detector dispatch.
        no_subprocess = unittest.mock.patch.object(execution, "subprocess")
        stub_subprocess = no_subprocess.start()
        stub_subprocess.run.side_effect = AssertionError("a builtin detector must not shell out to subprocess.run")
        self.addCleanup(no_subprocess.stop)

    def _detector(self, extra_args: "list[str] | None" = None) -> discovery.Detector:
        return discovery.Detector(
            name="self-admitted-debt",
            title="Self-admitted technical debt",
            module=self_admitted_debt,
            args=extra_args or [],
        )

    def test_a_builtin_detector_runs_in_process_and_its_output_is_captured(self):
        result = execution.run_detector_json(self._detector(), self.tmp.name)

        self.assertEqual(result["exit_code"], 0)
        # "Most admitted debt" only appears when the scan found something; the
        # detector prints a different "No ... markers found" sentence on an
        # empty result, so this also proves the scan is not silently empty.
        self.assertIn("Most admitted debt", result["output"])
        self.assertIn(os.path.basename(self.todo_file), result["output"])
        self.assertIsNone(result["error"])

    def test_a_builtin_detectors_findings_are_the_same_rows_the_sink_would_record(self):
        # `findings` must be the structured (_sink_entry-shaped) rows behind the
        # markdown `output` table, not a duplicate summary of it: the file this
        # detector found the TODO in has to appear on one of the dict rows.
        result = execution.run_detector_json(self._detector(), self.tmp.name)

        self.assertEqual(len(result["findings"]), 1)
        entry = result["findings"][0]
        self.assertIn(os.path.basename(self.todo_file), entry["file"])
        self.assertEqual(entry["count"], 1)

    def test_a_builtin_detector_with_no_findings_gets_an_empty_findings_list(self):
        # A clean run (no debt markers) never calls print_table's sink-recording
        # path at all, so findings must default to empty rather than error out
        # on a sink nobody appended to.
        clean_dir = self.tmp.name
        write_tree_file(clean_dir, "clean.py", "def stub():\n    pass\n")
        # Remove the TODO-carrying file this class's setUp already created, so
        # the only file left in the tree is the clean one.
        os.remove(self.todo_file)

        result = execution.run_detector_json(self._detector(), clean_dir)

        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["findings"], [])

    def test_a_builtin_detector_that_calls_sys_exit_with_a_message_is_reported_as_failed(self):
        # An empty --markers list is a usage error the detector reports via
        # `sys.exit("error: ...")`. In-process that raises SystemExit with a
        # string `.code` instead of printing to stderr and exiting the whole
        # process, so `_run_module_detector` must fold it into exit_code 1
        # rather than letting the exception crash the rest of the scan.
        result = execution.run_detector_json(self._detector(["--markers", ""]), self.tmp.name)

        self.assertEqual(result["exit_code"], 1)
        self.assertIn("--markers needs at least one marker", result["error"])
        self.assertTrue(execution._detector_failed(result))

    def test_a_builtin_detector_whose_main_returns_a_nonzero_int_is_reported_as_failed(self):
        # main() returning an int is the non-exception way a detector reports
        # its own exit code; it must round-trip unchanged, not get coerced to
        # 0 (the "no int, no exception" default) or flattened to 1.
        stub = discovery.Detector(name="stub-int", title="Stub", module=_StubModule(_main_returns_2))
        result = execution.run_detector_json(stub, self.tmp.name)

        self.assertEqual(result["exit_code"], 2)
        self.assertTrue(execution._detector_failed(result))

    def test_a_builtin_detector_that_raises_system_exit_with_an_int_code_is_reported_as_failed(self):
        stub = discovery.Detector(name="stub-exit", title="Stub", module=_StubModule(_main_raises_system_exit_3))
        result = execution.run_detector_json(stub, self.tmp.name)

        self.assertEqual(result["exit_code"], 3)
        self.assertTrue(execution._detector_failed(result))


def _echoing_detector(script_dir: str) -> discovery.Detector:
    """An external detector whose script prints the path it was given, then exits clean."""
    script = write_tree_file(script_dir, "echo.py", """
        import sys
        print(f"scanned {sys.argv[1]}")
    """)
    return discovery.Detector(name="echoes", title="Echoes its path", script=script)


def _failing_detector(script_dir: str) -> discovery.Detector:
    """An external detector whose script prints partial findings, then exits non-zero."""
    script = write_tree_file(script_dir, "fail.py", """
        import sys
        print("partial findings")
        sys.exit(1)
    """)
    return discovery.Detector(name="fails", title="Always fails", script=script)


class ExternalDetectorSubprocessTest(unittest.TestCase):
    """An external detector has no `module`, so `run_detector_json` shells out to
    it with `subprocess.run` instead of calling it in-process."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_an_external_detector_runs_as_a_subprocess_and_its_output_is_captured(self):
        detector = _echoing_detector(self.tmp.name)
        result = execution.run_detector_json(detector, self.tmp.name)

        self.assertEqual(result["exit_code"], 0)
        self.assertIn("scanned", result["output"])
        self.assertIn(self.tmp.name, result["output"])

    def test_an_external_detectors_findings_are_always_empty(self):
        # An external detector runs in its own process; there is no in-process
        # sink `run_detector_json` could read its rows back out of, clean run
        # or not, so `findings` is always [] for it, never missing.
        detector = _echoing_detector(self.tmp.name)
        result = execution.run_detector_json(detector, self.tmp.name)
        self.assertEqual(result["findings"], [])

    def test_an_external_detector_that_exits_non_zero_is_reported_as_failed(self):
        # A crash must not vanish from the scan: its exit code has to flip
        # `_detector_failed` rather than being treated as "found nothing".
        detector = _failing_detector(self.tmp.name)
        result = execution.run_detector_json(detector, self.tmp.name)

        self.assertEqual(result["exit_code"], 1)
        self.assertIn("partial findings", result["output"])
        self.assertTrue(execution._detector_failed(result))


class ExternalDetectorLaunchFailureTest(unittest.TestCase):
    """A detector that never launches at all (bad interpreter, no permission
    to execute) is a different failure shape than one that launched and
    exited non-zero: `subprocess.run` itself raises OSError rather than
    returning a completed-process result, so there is no exit code at all."""

    def test_a_detector_that_fails_to_launch_has_no_exit_code_but_still_fails(self):
        detector = discovery.Detector(name="unlaunchable", title="Never launches", script="whatever.py")
        with unittest.mock.patch.object(execution.subprocess, "run", side_effect=OSError("no such interpreter")):
            result = execution.run_detector_json(detector, os.path.dirname(__file__))

        # No process ever ran, so there is no exit code to report...
        self.assertIsNone(result["exit_code"])
        self.assertIn("no such interpreter", result["error"])
        # ...but `_detector_failed` must still treat it as a failure: for a
        # None exit code, it falls back to "did launching leave an error
        # message behind", and that fallback is what this asserts on.
        self.assertTrue(execution._detector_failed(result))
        # A process that never launched certainly never handed anything to a
        # sink; findings stays [], the same as every other external result.
        self.assertEqual(result["findings"], [])


class ModuleDetectorFindingsSinkNestingTest(unittest.TestCase):
    """`_run_module_detector` installs its own sink around one detector call,
    but `sniff baseline`/`sniff diff` (gate._collect) already install one of
    their own around a whole run, so the two have to nest rather than one
    clobbering the other.

    Simulates that outer install directly (rather than going through gate.py)
    so this stays a unit test of execution.py's own nesting contract."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.todo_file = _todo_file_tree(self.tmp.name)
        self.addCleanup(setattr, harness, "FINDINGS_SINK", None)

    def _detector(self) -> discovery.Detector:
        return discovery.Detector(name="self-admitted-debt", title="x", module=self_admitted_debt)

    def test_an_already_installed_outer_sink_is_extended_not_replaced(self):
        outer_sink = []
        harness.FINDINGS_SINK = outer_sink

        result = execution.run_detector_json(self._detector(), self.tmp.name)

        # The gate's own list must end up holding the same rows the result's
        # `findings` carries, exactly once each: neither dropped (which would
        # break the gate's fingerprinting) nor duplicated (which would double
        # its counted violations).
        self.assertEqual(outer_sink, result["findings"])

    def test_the_outer_sinks_own_list_object_is_restored_after_the_call(self):
        # Identity, not just equality: gate._collect reads `harness.FINDINGS_SINK`
        # back out by reference after this call returns, so a same-content but
        # different list would still be a bug (the gate would see its own outer
        # variable diverge from the package attribute).
        outer_sink = []
        harness.FINDINGS_SINK = outer_sink

        execution.run_detector_json(self._detector(), self.tmp.name)

        self.assertIs(harness.FINDINGS_SINK, outer_sink)

    def test_no_outer_sink_leaves_the_package_attribute_as_none_afterward(self):
        # The standalone (non-gate) case: nothing was installed beforehand, so
        # nothing should be left behind afterward either.
        harness.FINDINGS_SINK = None

        execution.run_detector_json(self._detector(), self.tmp.name)

        self.assertIsNone(harness.FINDINGS_SINK)


if __name__ == "__main__":
    unittest.main()
