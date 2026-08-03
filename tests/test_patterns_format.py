#!/usr/bin/env python3
"""Catalog test: a fixture with known smells must yield the expected counts.

Run: python tests/test_patterns_format.py
Skips cleanly if ast-grep is not on PATH.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
FORMAT = os.path.join(REPO_ROOT, "src", "sniff", "patterns", "format.py")
HAS_AST_GREP = shutil.which("ast-grep") is not None

# Load format.py as a module (not just a subprocess target) so the pytest-style
# tests below can call catalog_rules() directly and inspect its return value.
_spec = importlib.util.spec_from_file_location("format_mod", FORMAT)
format_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(format_mod)


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        # 3 explicit anys; 1 nested ternary.
        self._write("bad.ts", "let a: any = 1;\nfunction f(b: any) { return b; }\nconst c: any = [];\n")
        self._write("ternary.ts", "const t = x ? 1 : y ? 2 : 3;\n")
        self._write("clean.ts", "const n: number = 1;\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, rel, body):
        with open(os.path.join(self.root, rel), "w", encoding="utf-8") as fh:
            fh.write(body)

    def _run(self, *extra):
        proc = subprocess.run([sys.executable, FORMAT, self.root, *extra],
                              capture_output=True, text=True)
        return proc.stdout

    def test_explicit_any_counted(self):
        out = self._run("--rule", "no-explicit-any")
        self.assertIn("no-explicit-any", out)
        self.assertIn("### no-explicit-any (warning): 3", out)

    def test_nested_ternary_found(self):
        out = self._run("--rule", "no-nested-ternary")
        self.assertIn("no-nested-ternary", out)

    def test_severity_filter_excludes_others(self):
        out = self._run("--severity", "error")
        self.assertIn("0 findings", out)   # no seeded fixture matches the error rule
        self.assertIn("across 1 rules", out)  # the catalog currently has one error-severity rule
        self.assertNotIn("### no-empty-catch (error): 0", out)
        self.assertNotIn("| (none) |", out)

    def test_clean_reports_summary_without_empty_rule_tables(self):
        empty = tempfile.mkdtemp()
        try:
            with open(os.path.join(empty, "ok.ts"), "w", encoding="utf-8") as fh:
                fh.write("const n: number = 1;\n")
            proc = subprocess.run([sys.executable, FORMAT, empty],
                                  capture_output=True, text=True)
            self.assertIn("0 findings", proc.stdout)
            # Clean repo should not spend tokens on one empty table per rule.
            self.assertNotIn("### no-explicit-any (warning): 0", proc.stdout)
            self.assertNotIn("### no-nested-ternary (warning): 0", proc.stdout)
            self.assertNotIn("| (none) |", proc.stdout)
            self.assertIn("Ran ", proc.stdout)
        finally:
            shutil.rmtree(empty, ignore_errors=True)


def run_format(args: list[str]) -> str:
    """Run format.py as a subprocess with `args`, return stdout.

    Module-level equivalent of CatalogTest._run, for pytest-style tests below
    that don't need the unittest fixture's tmpdir setUp/tearDown."""
    proc = subprocess.run([sys.executable, FORMAT, *args], capture_output=True, text=True)
    return proc.stdout


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
def test_disable_flag_hides_rule_findings(tmp_path):
    (tmp_path / "a.ts").write_text("console.log('x')\n", encoding="utf-8")
    out = run_format([str(tmp_path), "--disable", "no-console-log"])
    assert "no-console-log" not in out.split("Ran ")[0]  # not in findings section


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
def test_severity_override_rewrites_reported_severity(tmp_path):
    # no-console-log ships as a warning; override it to error for this scan.
    (tmp_path / "a.ts").write_text("console.log('x')\n", encoding="utf-8")
    out = run_format([str(tmp_path), "--rule", "no-console-log",
                      "--severity-override", "no-console-log=error"])
    assert "### no-console-log (error):" in out
    assert "### no-console-log (warning):" not in out


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
def test_locations_are_capped_by_default_but_count_is_complete(tmp_path):
    """A noisy rule reports its true total while listing only DEFAULT_TOP_LOCS rows.

    Guards the whole point of the cap: one info-severity rule must never be able
    to flood the caller's context with hundreds of location rows."""
    hits = format_mod.DEFAULT_TOP_LOCS + 5
    (tmp_path / "a.ts").write_text("console.log('x')\n" * hits, encoding="utf-8")

    out = run_format([str(tmp_path), "--rule", "no-console-log"])

    assert f"### no-console-log (warning): {hits}" in out
    assert out.count("| a.ts:") == format_mod.DEFAULT_TOP_LOCS
    assert "| +5 more (raise --top-locs to list them) |" in out


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
def test_top_locs_zero_lists_every_location(tmp_path):
    """`--top-locs 0` is the escape hatch: no cap, and so no "+N more" row."""
    hits = format_mod.DEFAULT_TOP_LOCS + 5
    (tmp_path / "a.ts").write_text("console.log('x')\n" * hits, encoding="utf-8")

    out = run_format([str(tmp_path), "--rule", "no-console-log", "--top-locs", "0"])

    assert out.count("| a.ts:") == hits
    assert "more (raise --top-locs" not in out


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
def test_rules_are_ordered_worst_severity_first(tmp_path):
    """Errors sort above warnings, warnings above info, whatever the hit counts.

    The cap makes ordering matter: whoever reads only the top of the output must
    see the severe rules there, not an info rule that happened to match more."""
    (tmp_path / "a.ts").write_text(
        # no-empty-catch is an error rule, no-console-log a warning; give the
        # warning more hits so a count-first sort would wrongly put it on top.
        "try { f() } catch (e) {}\n" + "console.log('x')\n" * 3, encoding="utf-8")

    out = run_format([str(tmp_path)])

    assert out.index("### no-empty-catch (error)") < out.index("### no-console-log (warning)")


def test_local_rules_are_discovered(tmp_path):
    rules = tmp_path / ".sniff" / "rules"
    rules.mkdir(parents=True)
    (rules / "no-todo-comment.yml").write_text(
        "id: no-todo-comment\nlanguage: typescript\nseverity: warning\n"
        "message: TODO comment left in code.\nrule:\n  pattern: \"// TODO $$$\"\n",
        encoding="utf-8")
    cat = format_mod.catalog_rules(str(tmp_path))
    origins = {rid: origin for rid, _sev, _msg, origin, _lang in cat}
    assert origins.get("no-todo-comment") == "local"
    assert all(o == "core" for rid, o in origins.items() if rid != "no-todo-comment")


def test_malformed_local_rule_warns_and_skips(tmp_path, capsys):
    rules = tmp_path / ".sniff" / "rules"
    rules.mkdir(parents=True)
    (rules / "broken.yml").write_text("not: a rule", encoding="utf-8")
    cat = format_mod.catalog_rules(str(tmp_path))
    assert all(rid != "broken" for rid, _s, _m, _o, _lang in cat)


def test_list_rules_shows_origin(capsys, tmp_path):
    rules = tmp_path / ".sniff" / "rules"
    rules.mkdir(parents=True)
    (rules / "my-local.yml").write_text(
        "id: my-local\nlanguage: typescript\nmessage: x\nrule:\n  pattern: \"debugger\"\n",
        encoding="utf-8")
    format_mod.print_list_rules(format_mod.catalog_rules(str(tmp_path)))
    out = capsys.readouterr().out
    assert "| ORIGIN |" in out and "| local |" in out and "| core |" in out


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
def test_list_rules_groups_by_language(capsys):
    format_mod.print_list_rules(format_mod.catalog_rules())
    out = capsys.readouterr().out
    assert "### typescript" in out and "### python" in out


def _run_patterns(scan_dir, *extra):
    """Run the catalog over `scan_dir` and return its stdout."""
    proc = subprocess.run(
        [sys.executable, "-m", "sniff.cli", "--only", "sniff-patterns", str(scan_dir), *extra],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": os.path.join(REPO_ROOT, "src")},
    )
    return proc.stdout


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
def test_pattern_findings_in_test_files_are_skipped_by_default(tmp_path):
    """Every other detector skips test code, and the catalog used to not.

    On excalidraw that meant 57% of no-non-null-assertion's findings sat in
    specs, which is not work anyone is going to do."""
    (tmp_path / "app.py").write_text("print('ship')\n", encoding="utf-8")
    (tmp_path / "test_app.py").write_text("print('spec')\n", encoding="utf-8")

    out = _run_patterns(tmp_path)

    assert "app.py" in out
    assert "test_app.py" not in out, out
    assert "tests excluded" in out


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
def test_include_tests_brings_pattern_findings_back(tmp_path):
    (tmp_path / "app.py").write_text("print('ship')\n", encoding="utf-8")
    (tmp_path / "test_app.py").write_text("print('spec')\n", encoding="utf-8")

    out = _run_patterns(tmp_path, "--include-tests")

    assert "test_app.py" in out, out
    assert "tests included" in out


def test_pattern_ignore_dirs_stay_in_step_with_the_harness():
    """The local copy had already drifted, so pattern rules reported build
    output from .astro/.nuxt/.turbo that every other detector skipped."""
    from sniff import harness as h

    assert format_mod.IGNORE_DIRS == h.IGNORE_DIRS


def test_vendored_dir_check_ignores_parents_above_scan_root():
    """A checkout under a 'build'/'.claude'-named parent is still real source.

    Counting parent segments drops every finding in the repo, and an empty
    result is indistinguishable from a clean one, so the scan reports no smells
    instead of an error."""
    root = "C:/Users/me/.claude/worktrees/proj"
    assert not format_mod._in_ignored_dir(f"{root}/src/app.ts", root)


def test_vendored_dir_check_still_matches_below_scan_root():
    root = "C:/work/proj"
    assert format_mod._in_ignored_dir(f"{root}/node_modules/pkg/index.ts", root)


def test_vendored_dir_check_without_root_stays_base_independent():
    assert format_mod._in_ignored_dir("proj/dist/bundle.js")


if __name__ == "__main__":
    unittest.main(verbosity=2)
