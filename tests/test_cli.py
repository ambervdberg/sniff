#!/usr/bin/env python3
"""Tests for LLM-facing sniff CLI help and detector list output."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

from sniff import cli as run_module
from sniff import discovery

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
RUN = [sys.executable, "-m", "sniff.cli"]
# The release check in `prime` talks to PyPI. Disabled for every subprocess here so
# the suite never depends on network reachability; the check has its own unit tests.
SUBPROCESS_ENV = {**os.environ, "PYTHONPATH": SRC, "SNIFF_NO_VERSION_CHECK": "1"}


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


class SniffUpgradeCaveatTest(unittest.TestCase):
    """`prime` warns when PyPI has a newer release than the installed one."""

    def _caveat(self, installed: str, latest: str | None) -> str | None:
        """Resolve the upgrade caveat with the PyPI lookup stubbed to `latest`."""
        with unittest.mock.patch.object(run_module, "_latest_released_version", return_value=latest):
            return run_module._upgrade_available_caveat(installed)

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
                unittest.mock.patch.object(run_module.urllib.request, "urlopen") as urlopen:
            self.assertIsNone(run_module._latest_released_version())
        urlopen.assert_not_called()

    def test_request_bypasses_the_cdn_cache(self):
        """PyPI's CDN can serve the previous release for a while after an upload,
        so a cached answer would keep prime silent through exactly the release it
        exists to announce."""
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SNIFF_NO_VERSION_CHECK", None)
            with unittest.mock.patch.object(
                run_module.urllib.request, "urlopen", side_effect=OSError("offline")
            ) as urlopen:
                run_module._latest_released_version()
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Cache-control"), "no-cache")

    def test_network_failure_returns_none_instead_of_raising(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SNIFF_NO_VERSION_CHECK", None)
            with unittest.mock.patch.object(
                run_module.urllib.request, "urlopen", side_effect=OSError("offline")
            ):
                self.assertIsNone(run_module._latest_released_version())


class SniffBaselineDiffTest(unittest.TestCase):
    """`sniff baseline write` saves counts; `sniff diff` compares against them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "a.py"), "w", encoding="utf-8") as fh:
            fh.write("def foo(a, b, c, d, e, f, g):\n    pass\n")

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([*RUN, *args], capture_output=True, text=True, env=SUBPROCESS_ENV)

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


def test_diff_comment_renders_markdown(tmp_path, capsys, monkeypatch):
    (tmp_path / ".sniff").mkdir()
    (tmp_path / ".sniff" / "baseline.json").write_text('{"counts": {"x": 1}}', encoding="utf-8")
    monkeypatch.setattr(run_module, "_scan_counts", lambda dets, path: {"x": 3})
    rc = run_module.run_diff(["--comment", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1 and "| DETECTOR |" in out and "**worse**" in out and "+2" in out


class CountFindingsTest(unittest.TestCase):
    """_count_table_rows handles multiple tables; _count_findings reads the true
    total from a detector's summary line instead of a possibly-capped table."""

    def test_count_table_rows_does_not_double_count_multiple_tables(self):
        # sniff-patterns prints one "| LOCATION |" table per matched rule; a
        # global "first row is the header" flag would miscount the second
        # table's own header as a finding (3 true rows, would read as 4).
        output = (
            "### ruleA (warning): 2\n\n"
            "| LOCATION |\n| --- |\n| loc1 |\n| loc2 |\n\n"
            "### ruleB (error): 1\n\n"
            "| LOCATION |\n| --- |\n| loc3 |\n"
        )
        self.assertEqual(run_module._count_table_rows(output), 3)

    def test_count_findings_reads_true_total_from_capped_table(self):
        # "Largest 20 of 262" — the table only shows 20 rows but the true
        # count is 262; a capped table must not mask a real regression.
        output = "Largest 20 of 262 methods/functions (python; tests excluded):\n"
        self.assertEqual(run_module._count_findings(output), 262)

    def test_count_findings_reads_sniff_patterns_total(self):
        output = "sniff-patterns: 5 findings across 9 rules in '.'\n"
        self.assertEqual(run_module._count_findings(output), 5)

    def test_count_findings_reads_duplicate_string_total(self):
        output = "Strings duplicated in 3+ distinct files (71 found; tests excluded):\n"
        self.assertEqual(run_module._count_findings(output), 71)

    def test_count_findings_falls_back_to_zero_for_no_matches(self):
        self.assertEqual(run_module._count_findings("No classes matched.\n"), 0)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
