#!/usr/bin/env python3
"""Catalog test: a fixture with known smells must yield the expected counts.

Run: python skills/sniff-patterns/scripts/test_format.py
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
FORMAT = os.path.join(HERE, "format.py")
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
