#!/usr/bin/env python3
"""Integration test: the Codex plugin manifest and hooks are wired correctly.

Mirrors test_hook_wiring.py's approach for the Claude plugin, but for the
native Codex plugin: .codex-plugin/plugin.json (manifest) and hooks.json
(SessionStart/Stop wiring) at the repo root.

AC: .codex-plugin/plugin.json exists and validates. Hooks do not run scans
automatically. Default prompts include scan, list, and sniff-create.

Run: python -m pytest tests/test_codex_plugin_wiring.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
# repo root = plugin root: tests -> <root>
PLUGIN_ROOT = os.path.normpath(os.path.join(HERE, ".."))
CODEX_PLUGIN_JSON = os.path.join(PLUGIN_ROOT, ".codex-plugin", "plugin.json")
HOOKS_JSON = os.path.join(PLUGIN_ROOT, "hooks.json")


class CodexPluginManifestTest(unittest.TestCase):
    def test_manifest_exists_and_validates(self):
        with open(CODEX_PLUGIN_JSON, encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["name"], "sniff")
        self.assertIn("version", manifest)
        self.assertIn("skills", manifest)
        self.assertIn("interface", manifest)

    def test_default_prompts_cover_scan_list_and_sniff_create(self):
        with open(CODEX_PLUGIN_JSON, encoding="utf-8") as fh:
            manifest = json.load(fh)
        prompts = " ".join(manifest["interface"]["defaultPrompt"])
        self.assertIn("sniff", prompts)
        self.assertIn("--list", prompts)
        self.assertIn("sniff-create", prompts)


class CodexHooksWiringTest(unittest.TestCase):
    def setUp(self):
        with open(HOOKS_JSON, encoding="utf-8") as fh:
            self.hooks = json.load(fh)["hooks"]

    def test_session_start_and_stop_hooks_registered(self):
        self.assertIn("SessionStart", self.hooks)
        self.assertIn("Stop", self.hooks)

    def test_session_start_hook_runs_prime_not_a_scan(self):
        command = self.hooks["SessionStart"][0]["hooks"][0]["command"]
        self.assertIn("prime", command)

        proc = subprocess.run(command, cwd=PLUGIN_ROOT, shell=True, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        # A scan would print per-detector "## name" markdown sections; prime never does.
        self.assertNotIn("## ", proc.stdout)
        self.assertIn("CAVEATS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
