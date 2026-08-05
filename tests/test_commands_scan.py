#!/usr/bin/env python3
"""Tests for sniff.commands.scan: detector selection and the default scan run.

Each helper here is a pure step in the pipeline `cli.main()` wires together:
select the detector list from --only/--skip/.sniff.toml, drop the ones that
can't read this repo's languages, gate a per-detector flag that can't be
forwarded, then run whatever survives. `run_selected` is exercised with
`run_detector_json` mocked out, so these tests are about the *plumbing*
(selection, filtering, exit codes), not about any real detector's output.

Run: python -m pytest tests/test_commands_scan.py -q
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import types
import unittest
from unittest import mock

from sniff import config, discovery
from sniff.commands import scan


def make_detector(name: str, languages: "list[str] | None" = None) -> discovery.Detector:
    """A minimal Detector for selection/filtering tests: only name and
    languages matter to the code under test here, so every other field keeps
    its dataclass default."""
    return discovery.Detector(name=name, title=name, languages=languages or [])


class SelectTest(unittest.TestCase):
    """select(): --only / --skip narrow the detector list and flag typos."""

    def setUp(self):
        self.detectors = [make_detector("alpha"), make_detector("beta"), make_detector("gamma")]

    def test_only_keeps_named_detectors(self):
        selected, unknown = scan.select(self.detectors, {"alpha"}, set())
        self.assertEqual([d.name for d in selected], ["alpha"])
        self.assertEqual(unknown, [])

    def test_skip_removes_named_detectors(self):
        selected, unknown = scan.select(self.detectors, set(), {"beta"})
        self.assertEqual([d.name for d in selected], ["alpha", "gamma"])
        self.assertEqual(unknown, [])

    def test_no_only_or_skip_keeps_everything(self):
        selected, _unknown = scan.select(self.detectors, set(), set())
        self.assertEqual([d.name for d in selected], ["alpha", "beta", "gamma"])

    def test_unknown_only_name_is_reported_not_silently_dropped(self):
        # A typo'd --only must surface, not just resolve to an empty run.
        _selected, unknown = scan.select(self.detectors, {"alphaa"}, set())
        self.assertEqual(unknown, ["alphaa"])

    def test_unknown_skip_name_is_reported_too(self):
        _selected, unknown = scan.select(self.detectors, set(), {"nope"})
        self.assertEqual(unknown, ["nope"])


class SelectWithConfigTest(unittest.TestCase):
    """select_with_config(): .sniff.toml's [detectors] skip behaves like --skip."""

    def setUp(self):
        self.detectors = [make_detector("alpha"), make_detector("beta")]

    def test_config_skip_list_is_merged_into_the_cli_skip_set(self):
        cfg = config.Config(skip_detectors={"beta"})
        selected, _unknown = scan.select_with_config(self.detectors, set(), set(), cfg)
        self.assertEqual([d.name for d in selected], ["alpha"])

    def test_config_skip_and_cli_skip_combine_rather_than_override(self):
        cfg = config.Config(skip_detectors={"alpha"})
        selected, _unknown = scan.select_with_config(self.detectors, set(), {"beta"}, cfg)
        self.assertEqual(selected, [])

    def test_typo_in_config_skip_list_is_reported_as_unknown(self):
        # A typo in .sniff.toml must surface the same as a CLI --skip typo.
        cfg = config.Config(skip_detectors={"gone"})
        _selected, unknown = scan.select_with_config(self.detectors, set(), set(), cfg)
        self.assertEqual(unknown, ["gone"])


class ReadableHereTest(unittest.TestCase):
    """readable_here(): drop detectors with no rules for this repo's languages."""

    def test_drops_a_detector_with_no_matching_language(self):
        python_only = make_detector("py-thing", languages=["python"])
        selected = scan.readable_here([python_only], present={"typescript"}, only=set())
        self.assertEqual(selected, [])

    def test_keeps_a_detector_that_covers_a_present_language(self):
        python_only = make_detector("py-thing", languages=["python"])
        selected = scan.readable_here([python_only], present={"python", "typescript"}, only=set())
        self.assertEqual(selected, [python_only])

    def test_only_flag_keeps_a_detector_even_without_a_language_match(self):
        # Named explicitly by --only: it runs and explains itself rather than
        # vanishing as if it were never selected at all.
        python_only = make_detector("py-thing", languages=["python"])
        selected = scan.readable_here([python_only], present={"typescript"}, only={"py-thing"})
        self.assertEqual(selected, [python_only])

    def test_no_present_languages_keeps_everything(self):
        # A repo with no supported source files at all: detectors stay so they
        # can print their own "nothing to scan" message instead of vanishing.
        detectors = [make_detector("py-thing", languages=["python"])]
        selected = scan.readable_here(detectors, present=set(), only=set())
        self.assertEqual(selected, detectors)

    def test_a_detector_with_no_declared_languages_always_survives(self):
        # An external detector declares nothing, so its coverage is unknown;
        # skipping it on a guess would hide findings.
        unknown_coverage = make_detector("external-thing", languages=[])
        selected = scan.readable_here([unknown_coverage], present={"typescript"}, only=set())
        self.assertEqual(selected, [unknown_coverage])


class OverrideArgsTest(unittest.TestCase):
    """_override_args(): fold .sniff.toml's detector.arg=value overrides into a
    detector's own CLI args. This is the one real algorithm in scan.py, so its
    edges (an existing flag, an absent one, a flag with nothing after it, a
    flag repeated) each get their own case rather than one happy-path test."""

    def test_replaces_an_existing_flags_value_in_place(self):
        result = scan._override_args(["--top", "20", "--other", "1"], {"top": "15"})
        self.assertEqual(result, ["--top", "15", "--other", "1"])

    def test_appends_a_flag_the_manifest_never_set(self):
        result = scan._override_args(["--top", "20"], {"new": "value"})
        self.assertEqual(result, ["--top", "20", "--new", "value"])

    def test_trailing_flag_with_no_following_value_gets_the_value_appended(self):
        # The flag is the very last token, so there is no "next" element to
        # overwrite; the loop must append the override value instead of
        # indexing past the end of the list.
        result = scan._override_args(["--top"], {"top": "15"})
        self.assertEqual(result, ["--top", "15"])

    def test_a_flag_repeated_in_args_has_every_occurrence_replaced(self):
        result = scan._override_args(["--top", "20", "--top", "30"], {"top": "15"})
        self.assertEqual(result, ["--top", "15", "--top", "15"])

    def test_the_original_args_list_is_not_mutated(self):
        original = ["--top", "20"]
        scan._override_args(original, {"top": "15"})
        self.assertEqual(original, ["--top", "20"])


class ApplyConfigToDetectorTest(unittest.TestCase):
    """apply_config_to_detector(): the .sniff.toml effects that reach a
    detector's own args, one config section at a time."""

    def test_returns_the_same_object_when_no_config_applies(self):
        # apply_config_to_detector documents this as letting callers skip work
        # for the common no-config case, so identity (not just equality) is
        # the contract being tested.
        detector = discovery.Detector(name="alpha", title="alpha", args=["--top", "20"])
        result = scan.apply_config_to_detector(detector, config.Config())
        self.assertIs(result, detector)

    def test_a_detector_specific_threshold_overrides_its_args(self):
        detector = discovery.Detector(name="largest-methods", title="x", args=["--top", "20"])
        cfg = config.Config(thresholds={"largest-methods": {"top": "15"}})
        result = scan.apply_config_to_detector(detector, cfg)
        self.assertEqual(result.args, ["--top", "15"])

    def test_extra_ignores_become_extra_ignore_flags_for_a_builtin_detector(self):
        # A built-in (module) detector's module.main(argv) parses --extra-ignore
        # itself; an external (script) detector instead relies on the
        # SNIFF_EXTRA_IGNORE env var (see ExportedExtraIgnoreTest), so this
        # branch must not fire for it.
        builtin = discovery.Detector(name="alpha", title="alpha", module=types.ModuleType("fake"), args=[])
        cfg = config.Config(extra_ignores=["docs/**", "*.min.js"])
        result = scan.apply_config_to_detector(builtin, cfg)
        self.assertEqual(result.args, ["--extra-ignore", "docs/**", "--extra-ignore", "*.min.js"])

    def test_extra_ignores_are_left_off_an_external_script_detector(self):
        external = discovery.Detector(name="alpha", title="alpha", module=None, script="/some/script.py", args=[])
        cfg = config.Config(extra_ignores=["docs/**"])
        result = scan.apply_config_to_detector(external, cfg)
        self.assertIs(result, external)


class DiscoverWithWarningsTest(unittest.TestCase):
    """discover_with_warnings(): discovery.discover() plus a stderr warning per error."""

    def test_returns_the_discovered_detectors_unchanged(self):
        detectors = [make_detector("alpha")]
        with mock.patch.object(discovery, "discover", return_value=(detectors, [])):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                result = scan.discover_with_warnings()
        self.assertEqual(result, detectors)
        self.assertEqual(err.getvalue(), "")

    def test_prints_one_warning_line_per_manifest_error(self):
        errors = ["bad-detector: missing required 'script' field"]
        with mock.patch.object(discovery, "discover", return_value=([], errors)):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                scan.discover_with_warnings()
        self.assertIn("warning: bad-detector: missing required 'script' field", err.getvalue())


class RejectExtrasTest(unittest.TestCase):
    """reject_extras(): the per-detector-flag-on-a-full-scan rejection path."""

    def _parser(self) -> argparse.ArgumentParser:
        # A stand-in for cli._build_parser(): just enough shape (a positional
        # path, no --top/--whatever) that an unrecognized flag still fails
        # argparse's own strict parse, the same way the real scan parser does.
        parser = argparse.ArgumentParser(prog="sniff")
        parser.add_argument("path", nargs="?", default=".")
        parser.add_argument("--only")
        return parser

    def test_exits_with_code_2(self):
        parser = self._parser()
        argv = ["--top", "5"]
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                scan.reject_extras(parser, argv, ["--top", "5"])
        self.assertEqual(ctx.exception.code, 2)

    def test_prints_the_reason_before_argparses_own_error(self):
        # Named for the ordering it asserts: the specific reason must appear
        # ahead of argparse's own "unrecognized arguments" message, which only
        # fires because reject_extras re-runs the strict parse (scan.py's
        # `parser.parse_args(argv)` before the safety-net `raise SystemExit`).
        # Deleting that re-parse call would still exit 2 and still print the
        # reason, so both messages, and their order, must be checked.
        parser = self._parser()
        argv = ["--top", "5"]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit):
                scan.reject_extras(parser, argv, ["--top", "5"])
        message = err.getvalue()
        reason_index = message.index("extra detector flags require --only with exactly one detector")
        self.assertIn("--top 5", message)
        argparse_index = message.index("unrecognized arguments")
        self.assertLess(reason_index, argparse_index)


class ForwardExtrasTest(unittest.TestCase):
    """forward_extras(): trailing CLI flags only ever target a single detector."""

    def test_no_extras_returns_detectors_unchanged(self):
        detectors = [make_detector("alpha")]
        self.assertEqual(scan.forward_extras(detectors, []), detectors)

    def test_more_than_one_selected_detector_ignores_extras(self):
        # sniff cannot know which of several detectors a stray flag was meant
        # for, so extras are dropped rather than guessed at.
        detectors = [make_detector("alpha"), make_detector("beta")]
        self.assertEqual(scan.forward_extras(detectors, ["--top", "5"]), detectors)

    def test_single_detector_gets_extras_appended_after_its_own_args(self):
        detector = discovery.Detector(name="alpha", title="alpha", args=["--existing"])
        result = scan.forward_extras([detector], ["--top", "5"])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].args, ["--existing", "--top", "5"])
        # forward_extras must not mutate the detector it was handed.
        self.assertEqual(detector.args, ["--existing"])


class ExportedExtraIgnoreTest(unittest.TestCase):
    """exported_extra_ignore(): SNIFF_EXTRA_IGNORE is exported and always restored."""

    def setUp(self):
        # Snapshot whatever the ambient environment had, and restore it after
        # every test regardless of outcome, so no test can leak state into
        # the next one.
        self.previous = os.environ.get("SNIFF_EXTRA_IGNORE")
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self.previous is None:
            os.environ.pop("SNIFF_EXTRA_IGNORE", None)
        else:
            os.environ["SNIFF_EXTRA_IGNORE"] = self.previous

    def test_none_globs_leaves_the_environment_untouched(self):
        # Set to a value first, not just absent: a mutation that unconditionally
        # pops the var on the None branch would look identical to "did nothing"
        # if the test started from an already-empty environment.
        os.environ["SNIFF_EXTRA_IGNORE"] = "old/**"
        with scan.exported_extra_ignore(None):
            self.assertEqual(os.environ["SNIFF_EXTRA_IGNORE"], "old/**")
        self.assertEqual(os.environ["SNIFF_EXTRA_IGNORE"], "old/**")

    def test_globs_are_exported_as_a_comma_joined_string(self):
        with scan.exported_extra_ignore(["docs/**", "*.min.js"]):
            self.assertEqual(os.environ["SNIFF_EXTRA_IGNORE"], "docs/**,*.min.js")

    def test_previously_unset_var_is_removed_again_after_the_block(self):
        os.environ.pop("SNIFF_EXTRA_IGNORE", None)
        with scan.exported_extra_ignore(["a/**"]):
            pass
        self.assertNotIn("SNIFF_EXTRA_IGNORE", os.environ)

    def test_previous_value_is_restored_after_the_block(self):
        # main() may run in-process more than once (tests, embedding); a run
        # must not leak its ignore globs into whatever ran before it.
        os.environ["SNIFF_EXTRA_IGNORE"] = "old/**"
        with scan.exported_extra_ignore(["new/**"]):
            self.assertEqual(os.environ["SNIFF_EXTRA_IGNORE"], "new/**")
        self.assertEqual(os.environ["SNIFF_EXTRA_IGNORE"], "old/**")


class RunSelectedTest(unittest.TestCase):
    """run_selected(): renders results and its exit code follows detector failure."""

    def _args(self, json_mode: bool) -> argparse.Namespace:
        return argparse.Namespace(path="/some/repo", json=json_mode)

    def _clean_result(self, name: str) -> dict:
        return {"detector": name, "title": name, "exit_code": 0, "output": "no findings", "error": None}

    def _failing_result(self, name: str) -> dict:
        return {"detector": name, "title": name, "exit_code": 1, "output": "", "error": "boom"}

    def test_markdown_mode_prints_a_section_per_detector(self):
        detectors = [make_detector("alpha"), make_detector("beta")]
        with mock.patch.object(scan, "run_detector_json", side_effect=[
            self._clean_result("alpha"), self._clean_result("beta"),
        ]):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = scan.run_selected(detectors, self._args(json_mode=False))

        self.assertEqual(code, 0)
        printed = out.getvalue()
        self.assertIn("## alpha", printed)
        self.assertIn("## beta", printed)

    def test_markdown_mode_exit_code_is_1_when_any_detector_failed(self):
        detectors = [make_detector("alpha"), make_detector("beta")]
        with mock.patch.object(scan, "run_detector_json", side_effect=[
            self._clean_result("alpha"), self._failing_result("beta"),
        ]):
            with contextlib.redirect_stdout(io.StringIO()):
                code = scan.run_selected(detectors, self._args(json_mode=False))
        self.assertEqual(code, 1)

    def test_json_mode_prints_one_json_object_with_every_result(self):
        detectors = [make_detector("alpha")]
        with mock.patch.object(scan, "run_detector_json", return_value=self._clean_result("alpha")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = scan.run_selected(detectors, self._args(json_mode=True))

        self.assertEqual(code, 0)
        payload = out.getvalue()
        self.assertIn('"path": "/some/repo"', payload)
        self.assertIn('"detector": "alpha"', payload)

    def test_json_mode_exit_code_is_1_when_any_detector_failed(self):
        detectors = [make_detector("alpha")]
        with mock.patch.object(scan, "run_detector_json", return_value=self._failing_result("alpha")):
            with contextlib.redirect_stdout(io.StringIO()):
                code = scan.run_selected(detectors, self._args(json_mode=True))
        self.assertEqual(code, 1)

    def test_findings_alone_are_not_a_failure(self):
        # A detector that ran cleanly and reported smells is exit 0, not 1:
        # only a detector that failed to run flips the exit code.
        detectors = [make_detector("alpha")]
        reported_findings = {"detector": "alpha", "title": "alpha", "exit_code": 0,
                              "output": "3 smells found", "error": None}
        with mock.patch.object(scan, "run_detector_json", return_value=reported_findings):
            with contextlib.redirect_stdout(io.StringIO()):
                code = scan.run_selected(detectors, self._args(json_mode=False))
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
