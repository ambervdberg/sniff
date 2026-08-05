#!/usr/bin/env python3
"""Tests for LLM-facing sniff CLI help and detector list output."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock

from sniff import cli as run_module
from sniff import discovery
from sniff import gate
from sniff import versioning

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
RUN = [sys.executable, "-m", "sniff.cli"]
# The release check in `prime` talks to PyPI. Disabled for every subprocess here so
# the suite never depends on network reachability; the check has its own unit tests.
SUBPROCESS_ENV = {**os.environ, "PYTHONPATH": SRC, "SNIFF_NO_VERSION_CHECK": "1"}


def _path_without_astgrep() -> str:
    """PATH with every directory containing an `ast-grep` executable removed.

    Shared by any test that needs an ast-grep-backed detector to fail to launch
    (rather than run and report zero findings), so the failure path itself gets
    exercised."""
    dirs = os.environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(d for d in dirs if not shutil.which("ast-grep", path=d))


class SniffCliHelpTest(unittest.TestCase):
    """Verify LLM-facing sniff CLI help stays explicit."""

    def _run(self, *args: str) -> str:
        """Run the sniff CLI script and return stdout."""
        proc = subprocess.run([*RUN, *args], capture_output=True, text=True, check=True, env=SUBPROCESS_ENV)
        return proc.stdout

    def test_help_names_default_and_all_flag(self):
        """Help states the no-flag default and the --all alias."""
        out = self._run("--help")
        self.assertIn("Default: `sniff [DIR]` runs all detectors; `--all` is accepted as an explicit alias.", out)
        self.assertIn("Pattern rules only:  sniff --only sniff-patterns [DIR]", out)

    def test_list_shows_run_command_for_each_detector(self):
        """Detector list includes copyable run commands for routing."""
        out = self._run("--list")
        self.assertIn("| DETECTOR | TITLE | LANGUAGES | RUN |", out)
        self.assertIn("| sniff-patterns |", out)
        self.assertIn("`sniff --only sniff-patterns [DIR]`", out)

    def test_list_names_the_languages_each_detector_covers(self):
        """Every detector row states its coverage, so a wrong language is visible."""
        out = self._run("--list")
        self.assertIn("| large-classes | Largest classes | javascript, python, tsx, typescript |", out)
        self.assertIn("| large-inline-templates | Large Angular inline templates | tsx, typescript |", out)


class SniffHallucinatedFlagHintTest(unittest.TestCase):
    """A known-hallucinated flag prints a corrective hint before argparse errors out."""

    def _run_stderr(self, *args: str) -> str:
        proc = subprocess.run([*RUN, *args], capture_output=True, text=True, env=SUBPROCESS_ENV)
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
        proc = subprocess.run([*RUN, "version"], capture_output=True, text=True, env=SUBPROCESS_ENV)
        self.assertEqual(proc.returncode, 0)
        self.assertRegex(proc.stdout.strip(), r"^sniff \S+$")


class SniffVersionFlagTest(unittest.TestCase):
    """`sniff --version` is a top-level alias for the `sniff version` subcommand."""

    def test_version_flag_matches_version_subcommand(self):
        flag = subprocess.run([*RUN, "--version"], capture_output=True, text=True, env=SUBPROCESS_ENV)
        subcommand = subprocess.run([*RUN, "version"], capture_output=True, text=True, env=SUBPROCESS_ENV)
        self.assertEqual(flag.returncode, 0)
        self.assertEqual(flag.stdout, subcommand.stdout)


class SniffDoctorCommandTest(unittest.TestCase):
    """`sniff doctor` checks prerequisites and exits 0/1 based on the result."""

    def test_doctor_reports_python_and_manifest_checks(self):
        proc = subprocess.run([*RUN, "doctor"], capture_output=True, text=True, env=SUBPROCESS_ENV)
        self.assertIn(proc.returncode, (0, 1))
        self.assertIn("python", proc.stdout)
        self.assertIn("detector manifest(s) valid", proc.stdout)
        self.assertIn("duplicate detector name", proc.stdout)


def test_config_skip_merges_into_selection():
    detectors, _errors = run_module.discovery.discover()
    assert any(d.name == "largest-files" for d in detectors)  # sanity: it exists to be skipped

    cfg = run_module.config.Config(skip_detectors={"largest-files"})
    selected, _unknown = run_module.select_with_config(detectors, set(), set(), cfg)
    assert all(d.name != "largest-files" for d in selected)


def test_config_severity_override_reaches_sniff_patterns_args():
    detectors, _errors = run_module.discovery.discover()
    patterns = next(d for d in detectors if d.name == "sniff-patterns")

    cfg = run_module.config.Config(severity_overrides={"no-console-log": "error"})
    applied = run_module.apply_config_to_detector(patterns, cfg)
    assert "--severity-override" in applied.args
    assert "no-console-log=error" in applied.args


def test_doctor_warns_on_shadowed_local_rule(tmp_path, monkeypatch, capsys):
    rules = tmp_path / ".sniff" / "rules"
    rules.mkdir(parents=True)
    (rules / "no-empty-catch.yml").write_text("id: no-empty-catch\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    run_module.run_doctor()
    assert "shadows core rule" in capsys.readouterr().out


class SniffJsonOutputTest(unittest.TestCase):
    """--json emits parseable JSON for both --list and a scan, markdown stays default."""

    def test_list_json_is_parseable_detector_array(self):
        proc = subprocess.run(
            [*RUN, "--list", "--json"], capture_output=True, text=True, check=True, env=SUBPROCESS_ENV,
        )
        data = json.loads(proc.stdout)
        self.assertIsInstance(data, list)
        names = {d["name"] for d in data}
        self.assertIn("sniff-patterns", names)
        self.assertIn("script", data[0])

    def test_scan_json_is_parseable_per_detector(self):
        proc = subprocess.run(
            [*RUN, "--json", "--only", "sniff-patterns", "."],
            capture_output=True, text=True, check=True, env=SUBPROCESS_ENV,
        )
        data = json.loads(proc.stdout)
        self.assertEqual(data["path"], ".")
        self.assertEqual(len(data["detectors"]), 1)
        self.assertEqual(data["detectors"][0]["detector"], "sniff-patterns")
        self.assertIn("exit_code", data["detectors"][0])

    def test_default_markdown_output_unchanged_without_json_flag(self):
        proc = subprocess.run(
            [*RUN, "--only", "sniff-patterns", "."],
            capture_output=True, text=True, check=True, env=SUBPROCESS_ENV,
        )
        self.assertTrue(proc.stdout.startswith("sniff: 1 detectors over"))
        self.assertIn("## sniff-patterns", proc.stdout)


class SniffPrimeCommandTest(unittest.TestCase):
    """`sniff prime` prints agent context without running a scan."""

    def test_prime_includes_version_detectors_commands_caveats_no_scan(self):
        proc = subprocess.run([*RUN, "prime"], capture_output=True, text=True, env=SUBPROCESS_ENV)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.startswith("sniff "))
        self.assertIn("PREREQUISITES", proc.stdout)
        self.assertIn("DETECTORS (", proc.stdout)
        self.assertIn("sniff-patterns:", proc.stdout)
        self.assertIn("COMMON COMMANDS", proc.stdout)
        self.assertIn("CAVEATS", proc.stdout)
        # No scan output (per-detector "## name" markdown sections) should appear.
        self.assertNotIn("## sniff-patterns", proc.stdout)

    def test_prime_names_every_user_facing_subcommand(self):
        """The COMMON COMMANDS block is the only place an agent learns what sniff
        can do, so a subcommand missing from it is invisible in practice. Read the
        names off the dispatcher rather than restating them, or this guard drifts
        the same way the block it guards did.

        `test-rules` is the one exception: it only ever works from a source
        checkout and is deliberately kept out of user-facing help."""
        with open(run_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        dispatched = set(re.findall(r'argv\[:1\] == \["([\w-]+)"\]', source))
        self.assertIn("diff", dispatched, "dispatcher shape changed; this guard reads nothing")

        proc = subprocess.run([*RUN, "prime"], capture_output=True, text=True, env=SUBPROCESS_ENV)
        missing = [name for name in sorted(dispatched - {"test-rules"})
                   if f"sniff {name}" not in proc.stdout]
        self.assertEqual(missing, [])


class SniffUpgradeCaveatTest(unittest.TestCase):
    """`prime` warns when PyPI has a newer release than the installed one."""

    def _caveat(self, installed: str, latest: str | None) -> str | None:
        """Resolve the upgrade caveat with the PyPI lookup stubbed to `latest`."""
        with unittest.mock.patch.object(versioning, "_latest_released_version", return_value=latest):
            return versioning._upgrade_available_caveat(installed)

    def test_newer_release_names_version_and_upgrade_command(self):
        caveat = self._caveat("0.12.1", "0.13.0")
        self.assertIsNotNone(caveat)
        self.assertIn("sniff 0.13.0 is available", caveat)
        self.assertIn("installed: 0.12.1", caveat)
        self.assertIn("uv tool upgrade sniff-smells", caveat)

    def test_same_version_is_not_a_caveat(self):
        self.assertIsNone(self._caveat("0.13.0", "0.13.0"))

    def test_older_release_is_not_a_caveat(self):
        """A local build ahead of PyPI must not be told to downgrade."""
        self.assertIsNone(self._caveat("0.14.0", "0.13.0"))

    def test_unreachable_pypi_is_silent(self):
        self.assertIsNone(self._caveat("0.12.1", None))

    def test_unknown_installed_version_is_silent(self):
        self.assertIsNone(self._caveat("unknown", "0.13.0"))
        self.assertIsNone(self._caveat("", "0.13.0"))

    def test_segments_compare_numerically_not_lexically(self):
        """0.9.0 is older than 0.13.0, which string comparison gets backwards."""
        self.assertIsNotNone(self._caveat("0.9.0", "0.13.0"))
        self.assertIsNone(self._caveat("0.13.0", "0.9.0"))

    def test_env_var_disables_the_network_call(self):
        """The opt-out short-circuits before any request, for offline and CI use."""
        with unittest.mock.patch.dict(os.environ, {"SNIFF_NO_VERSION_CHECK": "1"}), \
                unittest.mock.patch.object(versioning.urllib.request, "urlopen") as urlopen:
            self.assertIsNone(versioning._latest_released_version())
        urlopen.assert_not_called()

    def test_request_bypasses_the_cdn_cache(self):
        """PyPI's CDN can serve the previous release for a while after an upload,
        so a cached answer would keep prime silent through exactly the release it
        exists to announce."""
        with tempfile.TemporaryDirectory() as tmp:
            # A cache path that never resolves to a real file guarantees a cache
            # miss regardless of what the dev machine's own cache happens to hold.
            cache = os.path.join(tmp, "version-cache.json")
            with unittest.mock.patch.dict(os.environ, {}, clear=False), \
                    unittest.mock.patch.object(versioning, "_version_cache_path", return_value=cache):
                os.environ.pop("SNIFF_NO_VERSION_CHECK", None)
                with unittest.mock.patch.object(
                    versioning.urllib.request, "urlopen", side_effect=OSError("offline")
                ) as urlopen:
                    versioning._latest_released_version()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Cache-control"), "no-cache")

    def test_network_failure_returns_none_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "version-cache.json")
            with unittest.mock.patch.dict(os.environ, {}, clear=False), \
                    unittest.mock.patch.object(versioning, "_version_cache_path", return_value=cache):
                os.environ.pop("SNIFF_NO_VERSION_CHECK", None)
                with unittest.mock.patch.object(
                    versioning.urllib.request, "urlopen", side_effect=OSError("offline")
                ):
                    self.assertIsNone(versioning._latest_released_version())

    def test_version_check_uses_fresh_cache_without_network(self):
        """A cache written within the last 4 hours must short-circuit the network
        call entirely, not merely prefer the cached value."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "version-cache.json")
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump({"checked_at": time.time(), "latest": "9.9.9"}, fh)
            with unittest.mock.patch.object(versioning, "_version_cache_path", return_value=cache), \
                    unittest.mock.patch.object(
                        versioning.urllib.request, "urlopen",
                        side_effect=AssertionError("network hit despite fresh cache"),
                    ):
                self.assertEqual(versioning._latest_released_version(), "9.9.9")

    def test_version_check_refreshes_stale_cache(self):
        """A cache older than 4 hours must be treated as a miss: the network is
        consulted again and the on-disk cache is rewritten with the fresh answer."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "version-cache.json")
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump({"checked_at": 0, "latest": "0.0.1"}, fh)
            fake_response = io.BytesIO(json.dumps({"info": {"version": "9.9.9"}}).encode())
            with unittest.mock.patch.object(versioning, "_version_cache_path", return_value=cache), \
                    unittest.mock.patch.object(versioning.urllib.request, "urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value = fake_response
                self.assertEqual(versioning._latest_released_version(), "9.9.9")
            with open(cache, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["latest"], "9.9.9")

    def test_cache_with_non_string_latest_falls_through_to_network(self):
        """A corrupt cache (e.g. hand-edited to a non-string `latest`) must not crash
        `sniff prime`; it must be treated as a miss so the network path still runs."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "version-cache.json")
            with open(cache, "w", encoding="utf-8") as fh:
                json.dump({"checked_at": time.time(), "latest": 123}, fh)
            fake_response = io.BytesIO(json.dumps({"info": {"version": "9.9.9"}}).encode())
            with unittest.mock.patch.object(versioning, "_version_cache_path", return_value=cache), \
                    unittest.mock.patch.object(versioning.urllib.request, "urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value = fake_response
                self.assertEqual(versioning._latest_released_version(), "9.9.9")


class SniffBaselineDiffTest(unittest.TestCase):
    """`sniff baseline write` saves fingerprints; `sniff diff` compares against them."""

    def setUp(self):
        self.repo = tempfile.mkdtemp()
        with open(os.path.join(self.repo, "a.py"), "w", encoding="utf-8") as fh:
            fh.write("def foo(a, b, c, d, e, f, g):\n    pass\n")

    def _run(
        self, *args: str, env: dict | None = None, cwd: str | None = None
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*RUN, *args], capture_output=True, text=True, env=env or SUBPROCESS_ENV, cwd=cwd
        )

    def test_baseline_write_saves_v3_fingerprints(self):
        proc = self._run("baseline", "write", self.repo)
        self.assertEqual(proc.returncode, 0)
        with open(os.path.join(self.repo, ".sniff", "baseline.json")) as fh:
            data = json.load(fh)
        self.assertEqual(data["version"], 3)
        self.assertIn("most-parameters", data["fingerprints"])

    def test_diff_without_baseline_errors(self):
        proc = self._run("diff", self.repo)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no baseline", proc.stderr)

    def test_diff_clean_growth_is_not_a_regression(self):
        # THE core fix: adding a small clean function must not trip the gate.
        self._run("baseline", "write", self.repo)
        with open(os.path.join(self.repo, "extra.py"), "w") as fh:
            fh.write("def tiny(a, b):\n    return a + b\n")
        proc = self._run("diff", self.repo)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("same or better", proc.stdout)

    def test_diff_detects_new_violation(self):
        self._run("baseline", "write", self.repo)
        with open(os.path.join(self.repo, "extra.py"), "w") as fh:
            fh.write("def wide(a, b, c, d, e, f, g, h):\n    return a\n")
        proc = self._run("diff", self.repo)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("extra.py|wide", proc.stdout)

    def test_diff_rejects_v1_baseline(self):
        self._run("baseline", "write", self.repo)
        path = os.path.join(self.repo, ".sniff", "baseline.json")
        with open(path, "w") as fh:
            json.dump({"path": ".", "counts": {"most-parameters": 3}}, fh)
        proc = self._run("diff", self.repo)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("old format", proc.stderr)

    def test_diff_rejects_v2_baseline(self):
        # v2 fingerprinted the raw, command-line-spelling-dependent file path
        # (sniff-6yh); any baseline written before the v3 portability fix must
        # be refreshed, not silently trusted.
        self._run("baseline", "write", self.repo)
        path = os.path.join(self.repo, ".sniff", "baseline.json")
        with open(path) as fh:
            data = json.load(fh)
        data["version"] = 2
        with open(path, "w") as fh:
            json.dump(data, fh)
        proc = self._run("diff", self.repo)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("old format", proc.stderr)

    def test_diff_is_stable_across_path_spellings(self):
        # A baseline written with the relative spelling '.' must still match a
        # diff run with the absolute path to that same, unchanged directory.
        # Both spellings are ordinary ways to invoke it. Before the fix,
        # fingerprints embedded the command-line spelling verbatim, so this
        # reported false regressions and improvements on a clean repo.
        self._run("baseline", "write", ".", cwd=self.repo)
        proc = self._run("diff", os.path.abspath(self.repo))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("same or better", proc.stdout)

    def test_baseline_write_honours_sniff_toml_detector_skip(self):
        # sniff-ewd: `[detectors] skip` must remove that detector from the
        # gate the same way it removes it from a normal scan.
        with open(os.path.join(self.repo, ".sniff.toml"), "w", encoding="utf-8") as fh:
            fh.write("[detectors]\nskip = \"most-parameters\"\n")
        proc = self._run("baseline", "write", self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(self.repo, ".sniff", "baseline.json")) as fh:
            data = json.load(fh)
        self.assertNotIn("most-parameters", data["fingerprints"])

    def test_diff_honours_sniff_toml_disabled_rule(self):
        # sniff-ewd: `[rules] <id> = false` must silence that sniff-patterns
        # rule in the gate too, not just in a normal scan.
        with open(os.path.join(self.repo, ".sniff.toml"), "w", encoding="utf-8") as fh:
            fh.write('[rules]\nno-explicit-any = false\n')
        with open(os.path.join(self.repo, "loose.ts"), "w", encoding="utf-8") as fh:
            fh.write("let x: any = 1;\n")
        self._run("baseline", "write", self.repo)
        with open(os.path.join(self.repo, ".sniff", "baseline.json")) as fh:
            data = json.load(fh)
        rule_fps = data["fingerprints"].get("sniff-patterns", {})
        self.assertFalse(any(fp.startswith("no-explicit-any|") for fp in rule_fps), rule_fps)

    def test_diff_honours_sniff_toml_ignore_globs(self):
        # sniff-ewd: `[ignore] globs` must exclude matching files from the
        # gate's fingerprint scan, the same as it does for a normal scan.
        with open(os.path.join(self.repo, ".sniff.toml"), "w", encoding="utf-8") as fh:
            fh.write('[ignore]\nglobs = "generated/**"\n')
        generated_dir = os.path.join(self.repo, "generated")
        os.makedirs(generated_dir, exist_ok=True)
        with open(os.path.join(generated_dir, "wide.py"), "w", encoding="utf-8") as fh:
            fh.write("def wide(a, b, c, d, e, f, g, h):\n    return a\n")
        self._run("baseline", "write", self.repo)
        with open(os.path.join(self.repo, ".sniff", "baseline.json")) as fh:
            data = json.load(fh)
        params_fps = data["fingerprints"].get("most-parameters", {})
        self.assertFalse(any("generated" in fp for fp in params_fps), params_fps)

    def test_baseline_write_warns_on_bad_sniff_toml(self):
        # sniff-i9x: baseline write/diff load .sniff.toml exactly like a scan
        # does, so a bad config line must surface here too.
        with open(os.path.join(self.repo, ".sniff.toml"), "w", encoding="utf-8") as fh:
            fh.write("[detectors]\nbogus = 1\n")
        proc = self._run("baseline", "write", self.repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("warning: .sniff.toml", proc.stderr)
        self.assertIn("unknown detectors key", proc.stderr)

    def test_diff_fails_when_detector_errors(self):
        # Point the gate at a detector that cannot run: strip ast-grep from
        # PATH so ast-grep-backed detectors error. Exit must be 1, output
        # must name the failure, and must NOT say "same or better".
        self._run("baseline", "write", self.repo)
        env = {**SUBPROCESS_ENV, "PATH": _path_without_astgrep()}
        proc = self._run("diff", self.repo, env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("same or better", proc.stdout + proc.stderr)

    def test_scan_exit_code_reflects_detector_failure(self):
        # An ast-grep-backed detector that cannot launch must flip the scan's
        # exit code to 1: a broken detector is a failure, not a clean report.
        env = {**SUBPROCESS_ENV, "PATH": _path_without_astgrep()}
        proc = self._run("--only", "largest-methods", self.repo, env=env)
        self.assertEqual(proc.returncode, 1)

    def test_scan_with_findings_still_exits_zero(self):
        # A detector that runs fine and reports smells is not a failure;
        # findings alone must not flip the exit code.
        proc = self._run("--only", "most-parameters", self.repo)
        self.assertEqual(proc.returncode, 0)

    def test_baseline_help_exits_zero_without_write(self):
        # `sniff baseline --help` (no "write") used to fall through to the
        # "write" subcommand check, print the usage-error message, and exit 1.
        proc = self._run("baseline", "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage: sniff baseline write", proc.stdout)

    def test_diff_help_exits_zero_and_lists_comment_flag(self):
        # `sniff diff --help` used to try isdir("--help") and reject it as a
        # bad directory (exit 1) instead of printing usage.
        proc = self._run("diff", "--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage: sniff diff", proc.stdout)
        self.assertIn("--comment", proc.stdout)

    def test_scan_exit_stays_zero_when_external_detector_writes_stderr_but_exits_clean(self):
        # exit_code is the sole failure authority. An external (manifest,
        # subprocess) detector that exits 0 but writes incidental text to
        # stderr is not a failure: the rendered section for it is clean, so
        # the exit code must agree with what got printed.
        detector_dir = os.path.join(self.repo, ".sniff", "detectors", "noisy-clean")
        os.makedirs(detector_dir)
        with open(os.path.join(detector_dir, "detector.yml"), "w", encoding="utf-8") as fh:
            fh.write("name: noisy-clean\ntitle: Noisy but clean\nscript: noisy_clean.py\n")
        with open(os.path.join(detector_dir, "noisy_clean.py"), "w", encoding="utf-8") as fh:
            fh.write("import sys\nprint('ok')\nprint('warning: noisy', file=sys.stderr)\n")

        proc = self._run("--only", "noisy-clean", self.repo)

        self.assertEqual(proc.returncode, 0, proc.stderr)


def test_diff_comment_renders_markdown(tmp_path, capsys, monkeypatch):
    (tmp_path / ".sniff").mkdir()
    baseline = {"version": 3, "path": ".", "fingerprints": {"x": {"a.py|foo": 1}}}
    (tmp_path / ".sniff" / "baseline.json").write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(gate, "scan_fingerprints", lambda dets, path: {"x": {"a.py|foo": 1, "a.py|bar": 2}})
    rc = run_module.run_diff(["--comment", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1 and "| DETECTOR |" in out and "**worse**" in out and "a.py|bar" in out


class ConfigIgnoreGlobsTest(unittest.TestCase):
    """`.sniff.toml [ignore] globs` must reach sniff-patterns, not break it.

    cli.py folds the globs in as repeated `--extra-ignore` args for every
    built-in detector; sniff-patterns is one of them, so a parser without that
    flag exits 2 and the whole scan silently reports nothing."""

    def _scan(self, root: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*RUN, "--only", "sniff-patterns", root],
            capture_output=True, text=True, env=SUBPROCESS_ENV,
        )

    def test_ignore_globs_exclude_only_the_matching_dir(self):
        with tempfile.TemporaryDirectory() as root:
            def write(rel: str, text: str) -> None:
                path = os.path.join(root, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)

            write(".sniff.toml", '[ignore]\nglobs = ["gen/**"]\n')
            write("gen/x.ts", "console.log('generated');\n")
            write("src/app.ts", "console.log('handwritten');\n")

            proc = self._scan(root)

            self.assertNotEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("src/app.ts", proc.stdout)
            self.assertNotIn("gen/x.ts", proc.stdout)


class SniffIgnoreFlagTest(unittest.TestCase):
    """The top-level `--ignore GLOB` flag excludes files from a scan.

    It is repeatable, and it ADDS to the scanned repo's `.sniff.toml [ignore]
    globs` rather than replacing them: a one-off exclusion on the command line
    must not silently discard the exclusions that repo already committed."""

    def _scan(self, root: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*RUN, "--only", "largest-files", *args, root],
            capture_output=True, text=True, env=SUBPROCESS_ENV,
        )

    def _tree(self, root: str, files: "dict[str, str]") -> None:
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    def test_ignore_excludes_matching_file(self):
        with tempfile.TemporaryDirectory() as root:
            self._tree(root, {"src/app.py": "x = 1\n", "docs/sample.py": "y = 2\n"})

            proc = self._scan(root, "--ignore", "docs/**")

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("src/app.py", proc.stdout)
            self.assertNotIn("docs/sample.py", proc.stdout)

    def test_ignore_is_repeatable(self):
        with tempfile.TemporaryDirectory() as root:
            self._tree(root, {
                "src/app.py": "x = 1\n",
                "docs/sample.py": "y = 2\n",
                "gen/built.py": "z = 3\n",
            })

            proc = self._scan(root, "--ignore", "docs/**", "--ignore", "gen/**")

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("src/app.py", proc.stdout)
            self.assertNotIn("docs/sample.py", proc.stdout)
            self.assertNotIn("gen/built.py", proc.stdout)

    def test_ignore_adds_to_sniff_toml_globs_instead_of_replacing_them(self):
        with tempfile.TemporaryDirectory() as root:
            self._tree(root, {
                ".sniff.toml": '[ignore]\nglobs = "docs/**"\n',
                "src/app.py": "x = 1\n",
                "docs/sample.py": "y = 2\n",
                "gen/built.py": "z = 3\n",
            })

            proc = self._scan(root, "--ignore", "gen/**")

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("src/app.py", proc.stdout)
            self.assertNotIn("gen/built.py", proc.stdout)      # from --ignore
            self.assertNotIn("docs/sample.py", proc.stdout)    # from .sniff.toml, still applied


class ScanConfigWarningsTest(unittest.TestCase):
    """sniff-i9x: a plain `sniff DIR` scan must surface `.sniff.toml` config
    warnings too, not only `sniff doctor`."""

    def _tree(self, root: str, files: "dict[str, str]") -> None:
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    def test_markdown_scan_prints_config_warning_to_stderr(self):
        with tempfile.TemporaryDirectory() as root:
            self._tree(root, {".sniff.toml": "[detectors]\nbogus = 1\n", "a.py": "x = 1\n"})

            proc = subprocess.run(
                [*RUN, "--only", "sniff-patterns", root],
                capture_output=True, text=True, env=SUBPROCESS_ENV,
            )

            self.assertIn("warning: .sniff.toml", proc.stderr)
            self.assertIn("unknown detectors key", proc.stderr)

    def test_json_scan_stdout_still_parses_while_warning_goes_to_stderr(self):
        with tempfile.TemporaryDirectory() as root:
            self._tree(root, {".sniff.toml": "[detectors]\nbogus = 1\n", "a.py": "x = 1\n"})

            proc = subprocess.run(
                [*RUN, "--json", "--only", "sniff-patterns", root],
                capture_output=True, text=True, env=SUBPROCESS_ENV,
            )

            self.assertIn("warning: .sniff.toml", proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["path"], root)
            self.assertTrue(any("unknown detectors key" in w for w in data["config_warnings"]))

    def test_clean_sniff_toml_gives_no_warning(self):
        with tempfile.TemporaryDirectory() as root:
            self._tree(root, {".sniff.toml": "[detectors]\ntop = 5\n", "a.py": "x = 1\n"})

            proc = subprocess.run(
                [*RUN, "--only", "sniff-patterns", root],
                capture_output=True, text=True, env=SUBPROCESS_ENV,
            )

            self.assertNotIn("warning: .sniff.toml", proc.stderr)


class DetectorFlagPassthroughTest(unittest.TestCase):
    """Unknown trailing flags reach a single --only detector, and only then."""

    THREE_FUNCS = (
        "def one():\n" + "    x = 1\n" * 30 +
        "\n\ndef two():\n" + "    y = 2\n" * 20 +
        "\n\ndef three():\n" + "    z = 3\n" * 10 + "\n"
    )

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([*RUN, *args], capture_output=True, text=True, env=SUBPROCESS_ENV)

    def test_extra_flag_reaches_the_single_only_detector(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "sample.py"), "w", encoding="utf-8") as fh:
                fh.write(self.THREE_FUNCS)

            proc = self._run("--only", "largest-methods", root, "--top", "1")

            self.assertEqual(proc.returncode, 0, proc.stderr)
            # --top 1 caps the ranked table at a single data row: only the biggest function.
            self.assertIn("one", proc.stdout)
            self.assertNotIn("two", proc.stdout)
            self.assertNotIn("three", proc.stdout)

    def test_extra_flag_without_only_errors(self):
        proc = self._run(".", "--top", "1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--only", proc.stderr)

    def test_extra_flag_with_unknown_only_name_errors(self):
        """An --only typo resolves to no detector, so the extras have nowhere to go."""
        proc = self._run("--only", "bogus-detector", ".", "--top", "1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("exactly one detector", proc.stderr)

    def test_extra_flag_beats_sniff_toml_threshold(self):
        """A CLI flag is appended after the config-derived args, so it wins."""
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, ".sniff.toml"), "w", encoding="utf-8") as fh:
                fh.write("[detectors]\nlargest-files.top = 5\n")
            for name in ("a.py", "b.py", "c.py"):
                with open(os.path.join(root, name), "w", encoding="utf-8") as fh:
                    fh.write("x = 1\n")

            proc = self._run("--only", "largest-files", root, "--top", "1")

            self.assertEqual(proc.returncode, 0, proc.stderr)
            data_rows = [
                line for line in proc.stdout.splitlines()
                if line.startswith("|") and "LINES" not in line and set(line) - set("| -:")
            ]
            self.assertEqual(len(data_rows), 1, proc.stdout)

    def test_extra_flag_reaches_an_external_subprocess_detector(self):
        """Passthrough is not built-in-only: a manifest detector gets the flag in argv."""
        with tempfile.TemporaryDirectory() as root:
            detector_dir = os.path.join(root, ".sniff", "detectors", "echo-argv")
            os.makedirs(detector_dir)
            with open(os.path.join(detector_dir, "detector.yml"), "w", encoding="utf-8") as fh:
                fh.write("name: echo-argv\ntitle: Echo argv\nscript: echo_argv.py\n")
            with open(os.path.join(detector_dir, "echo_argv.py"), "w", encoding="utf-8") as fh:
                fh.write("import sys\nprint('ARGV:', ' '.join(sys.argv[1:]))\n")

            proc = self._run("--only", "echo-argv", root, "--marker", "42")

            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("--marker 42", proc.stdout)

    def test_extra_flag_with_two_only_detectors_errors(self):
        proc = self._run("--only", "largest-methods,largest-files", ".", "--top", "1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("exactly one detector", proc.stderr)


class ParserFreeCaveatTest(unittest.TestCase):
    """`sniff prime` must name the detectors that survive a missing ast-grep.

    The list used to be written out by hand and went stale the moment a
    parser-free detector landed, which told agents a working detector would
    fail. Both halves are checked: that each detector's declaration matches what
    its module actually does, and that prime prints the declared set."""

    def _builtin_modules(self):
        from sniff.detectors import BUILTIN
        return BUILTIN

    def test_every_parser_free_detector_runs_without_ast_grep(self):
        """The claim is behavioural, so it is checked by making it true or false.

        Hiding the binary makes the harness exit with its own error, so a
        detector that only looks parser-free fails this outright."""
        import io
        import contextlib
        from sniff import harness

        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "sample.py"), "w", encoding="utf-8") as fh:
                fh.write("def f(x):\n    return x\n")
            with open(os.path.join(root, "sample.ts"), "w", encoding="utf-8") as fh:
                fh.write("export function f(x: number) {\n  return x;\n}\n")

            for module in self._builtin_modules():
                if getattr(module, "NEEDS_AST_GREP", True):
                    continue
                with self.subTest(detector=module.NAME), \
                        unittest.mock.patch.object(harness.shutil, "which", return_value=None), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(module.main([root]), 0,
                                     f"{module.NAME} declares NEEDS_AST_GREP=False but did not run")

    def test_prime_names_every_parser_free_detector(self):
        import io
        import contextlib

        detectors, _ = discovery.discover()
        parser_free = [d.name for d in detectors if not d.needs_ast_grep]
        self.assertGreater(len(parser_free), 1, "expected several parser-free detectors")

        out = io.StringIO()
        with unittest.mock.patch.object(run_module.shutil, "which", return_value=None), \
                unittest.mock.patch.dict(os.environ, {"SNIFF_NO_VERSION_CHECK": "1"}), \
                contextlib.redirect_stdout(out):
            run_module.run_prime()
        caveat = out.getvalue()

        for name in parser_free:
            self.assertIn(name, caveat)
        for detector in detectors:
            if detector.needs_ast_grep:
                self.assertNotIn(f"only {detector.name}", caveat)


class SniffMissingDirTest(unittest.TestCase):
    """A nonexistent DIR fails fast with a hint instead of running every detector."""

    def test_nonexistent_dir_errors_without_running_detectors(self):
        proc = subprocess.run([*RUN, "/no/such/dir"], capture_output=True, text=True, env=SUBPROCESS_ENV)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("is not a directory", proc.stderr)
        self.assertNotIn("## ", proc.stdout)

    def test_plain_bad_dir_gets_no_recovery_hint(self):
        # No detector passthrough flags involved, so there is nothing to hint at.
        proc = subprocess.run([*RUN, "/no/such/dir"], capture_output=True, text=True, env=SUBPROCESS_ENV)
        self.assertNotIn("hint:", proc.stderr)

    def test_bad_dir_alongside_detector_flags_gets_a_recovery_hint(self):
        # `sniff --only <name> --top 3` (forgetting DIR): argparse's optional
        # positional greedily swallows "3" as the path, leaving "--top" behind
        # as an unforwardable extra. The bare rejection gave no way out.
        proc = subprocess.run(
            [*RUN, "--only", "largest-methods", "--top", "3"],
            capture_output=True, text=True, env=SUBPROCESS_ENV,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("'3' is not a directory", proc.stderr)
        self.assertIn("hint: detector flags need an explicit DIR before them", proc.stderr)
        self.assertIn("sniff --only <name> . --top 3", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
