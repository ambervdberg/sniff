#!/usr/bin/env python3
"""Behavioural tests for sniff.patterns.expand: rule discovery and per-language expansion.

expand.py is pure file/string handling (no ast-grep involved), so every test
here runs unconditionally: no @unittest.skipUnless(tool_available(...)) guard
is needed.

Run: python -m pytest tests/test_patterns_expand.py -q
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from sniff.patterns import expand


def _write_rule(rules_dir: str, filename: str, rule_id: str, language: str,
                extra_languages: "list[str] | None" = None,
                severity: "str | None" = "warning") -> str:
    """Write one minimal rule yml under `rules_dir`, in the shape the real catalog uses.

    severity=None omits the `severity:` line entirely, so a caller can exercise
    expand.py's "defaults to warning when the field is absent" behaviour."""
    lines = [f"id: {rule_id}", f"language: {language}"]
    if severity is not None:
        lines.append(f"severity: {severity}")
    lines.append("message: test rule")
    if extra_languages:
        lines.append("metadata:")
        lines.append(f"  languages: [{', '.join(extra_languages)}]")
    lines.append("rule:")
    lines.append('  pattern: "x"')

    path = os.path.join(rules_dir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


class LocalRulesDirTest(unittest.TestCase):
    """local_rules_dir is the one place that decides where consumer rules live.

    Every caller (catalog_rules, doctor.py, scan.py) trusts this join; a typo
    here would silently stop a repo's own .sniff/rules from ever loading."""

    def test_joins_dot_sniff_rules_under_the_scan_path(self):
        got = expand.local_rules_dir(os.path.join("repo", "proj"))
        self.assertEqual(got, os.path.join("repo", "proj", ".sniff", "rules"))


class WriteLanguageCopiesTest(unittest.TestCase):
    """_write_language_copies: one physical rule file per declared extra language."""

    def setUp(self):
        self.rules_dir = tempfile.mkdtemp()
        self.out_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.rules_dir, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.out_dir, ignore_errors=True)

    def _copy_body(self, copy_id: str) -> str:
        with open(os.path.join(self.out_dir, f"{copy_id}.yml"), encoding="utf-8") as fh:
            return fh.read()

    def test_one_copy_per_declared_extra_language(self):
        _write_rule(self.rules_dir, "multi.yml", "no-var", "typescript",
                    extra_languages=["tsx", "javascript"])

        generated = expand._write_language_copies(self.rules_dir, self.out_dir)

        # Both extra languages get their own generated id, mapped back to the real one.
        self.assertEqual(generated, {
            "no-var--lang-tsx": "no-var",
            "no-var--lang-javascript": "no-var",
        })
        self.assertEqual(sorted(os.listdir(self.out_dir)),
                          ["no-var--lang-javascript.yml", "no-var--lang-tsx.yml"])

    def test_each_copy_carries_its_own_language_key(self):
        _write_rule(self.rules_dir, "multi.yml", "no-var", "typescript",
                    extra_languages=["tsx", "javascript"])

        expand._write_language_copies(self.rules_dir, self.out_dir)

        tsx_body = self._copy_body("no-var--lang-tsx")
        js_body = self._copy_body("no-var--lang-javascript")

        self.assertIn("id: no-var--lang-tsx", tsx_body)
        self.assertIn("language: tsx", tsx_body)
        self.assertNotIn("language: typescript", tsx_body)

        self.assertIn("id: no-var--lang-javascript", js_body)
        self.assertIn("language: javascript", js_body)
        self.assertNotIn("language: typescript", js_body)

    def test_single_language_rule_produces_no_copies(self):
        _write_rule(self.rules_dir, "single.yml", "no-console-log", "python")

        generated = expand._write_language_copies(self.rules_dir, self.out_dir)

        self.assertEqual(generated, {})
        self.assertEqual(os.listdir(self.out_dir), [])

    def test_extra_language_matching_the_declared_one_is_skipped(self):
        # A rule that re-lists its own declared language in metadata must not
        # spawn a redundant self-copy (ast-grep would reject the duplicate id
        # anyway, but the id/language would also be a no-op).
        _write_rule(self.rules_dir, "redundant.yml", "no-any", "typescript",
                    extra_languages=["typescript", "tsx"])

        generated = expand._write_language_copies(self.rules_dir, self.out_dir)

        self.assertEqual(generated, {"no-any--lang-tsx": "no-any"})


class RuleLanguagesTest(unittest.TestCase):
    """rule_languages: declared language first, then whatever metadata adds."""

    def setUp(self):
        self.scan_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.scan_root, ignore_errors=True)
        self.local_dir = expand.local_rules_dir(self.scan_root)
        os.makedirs(self.local_dir)

    def test_declared_language_is_listed_first_then_extras(self):
        _write_rule(self.local_dir, "multi.yml", "sniff-local-multi", "typescript", extra_languages=["tsx"])

        langs = expand.rule_languages(self.scan_root)

        self.assertEqual(langs["sniff-local-multi"], ["typescript", "tsx"])

    def test_local_rule_reusing_a_core_id_does_not_override_its_languages(self):
        # no-explicit-any ships in the core catalog as typescript + tsx (see
        # src/sniff/patterns/rules/no-explicit-any.yml). A local rule that
        # claims the same id but declares a different language must not win,
        # or a consumer repo could silently repoint a built-in check's
        # language coverage just by naming a local rule after it.
        _write_rule(self.local_dir, "shadow.yml", "no-explicit-any", "python")

        langs = expand.rule_languages(self.scan_root)

        self.assertEqual(langs["no-explicit-any"], ["typescript", "tsx"])


class CatalogRulesLocalPathTest(unittest.TestCase):
    """catalog_rules only looks under local_rules_dir(scan_path), never scan_path itself."""

    def setUp(self):
        self.scan_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.scan_root, ignore_errors=True)

    def test_finds_local_rule_only_under_dot_sniff_rules(self):
        # Wrong place: a rule dropped straight in the scan root must stay invisible.
        _write_rule(self.scan_root, "misplaced.yml", "sniff-misplaced", "python")

        # Right place: .sniff/rules, resolved through local_rules_dir.
        local_dir = expand.local_rules_dir(self.scan_root)
        os.makedirs(local_dir)
        _write_rule(local_dir, "correct.yml", "sniff-correct", "python")

        ids = {row[0] for row in expand.catalog_rules(self.scan_root)}

        self.assertIn("sniff-correct", ids)
        self.assertNotIn("sniff-misplaced", ids)


class CatalogRulesRowShapeTest(unittest.TestCase):
    """catalog_rules: the full (id, severity, message, origin, language) row.

    Earlier coverage only ever read row[0] (the id). That leaves the severity
    default, the local-shadows-core skip, the missing-id skip, and the whole
    language column (row[4], half of what this catalog is for) unguarded.
    """

    def setUp(self):
        self.scan_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.scan_root, ignore_errors=True)
        self.local_dir = expand.local_rules_dir(self.scan_root)
        os.makedirs(self.local_dir)

    def _row(self, rule_id: str) -> tuple:
        rows = {row[0]: row for row in expand.catalog_rules(self.scan_root)}
        return rows[rule_id]

    def test_severity_defaults_to_warning_when_the_rule_omits_it(self):
        _write_rule(self.local_dir, "no-sev.yml", "sniff-no-severity", "python", severity=None)

        self.assertEqual(self._row("sniff-no-severity"),
                         ("sniff-no-severity", "warning", "test rule", "local", "python"))

    def test_full_row_carries_severity_message_origin_and_language(self):
        _write_rule(self.local_dir, "typed.yml", "sniff-typed", "javascript", severity="error")

        self.assertEqual(self._row("sniff-typed"),
                         ("sniff-typed", "error", "test rule", "local", "javascript"))

    def test_local_rule_reusing_a_core_id_is_dropped_and_the_core_row_survives(self):
        # Same shadowing risk as RuleLanguagesTest above, but for catalog_rows:
        # the local copy must never make it into the catalog at all, so its
        # (deliberately different) severity can never surface.
        _write_rule(self.local_dir, "shadow.yml", "no-explicit-any", "python", severity="info")

        rows = expand.catalog_rules(self.scan_root)
        matches = [row for row in rows if row[0] == "no-explicit-any"]

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][3], "core")
        self.assertNotEqual(matches[0][1], "info")

    def test_local_rule_without_an_id_is_skipped(self):
        # Hand-written, not via _write_rule, specifically to omit `id:`.
        path = os.path.join(self.local_dir, "no-id.yml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('language: python\nseverity: warning\nmessage: test rule\nrule:\n  pattern: "x"\n')

        rows = expand.catalog_rules(self.scan_root)

        self.assertTrue(all(row[0] for row in rows))  # no blank-id row leaked through
        self.assertFalse(any(row[3] == "local" for row in rows))  # the malformed rule contributed nothing


if __name__ == "__main__":
    unittest.main(verbosity=2)
