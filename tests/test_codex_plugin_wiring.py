#!/usr/bin/env python3
"""Integration test: the Codex plugin manifest and hooks are wired correctly.

Mirrors test_hook_wiring.py's approach for the Claude plugin, but for the
native Codex plugin: .codex-plugin/plugin.json (manifest) and hooks/hooks.json
(SessionStart/Stop wiring) at the plugin root.

hooks/hooks.json is the path Codex auto-discovers, so no "hooks" entry is
needed in the manifest. Moving or renaming this file silently disables every
hook in Codex, which is why the path is asserted here.

AC: .codex-plugin/plugin.json exists and validates. Hooks do not run scans
automatically. Default prompts include scan, list, and sniff-create.

Run: python -m pytest tests/test_codex_plugin_wiring.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
# repo root = plugin root: tests -> <root>
PLUGIN_ROOT = os.path.normpath(os.path.join(HERE, ".."))
CODEX_PLUGIN_JSON = os.path.join(PLUGIN_ROOT, ".codex-plugin", "plugin.json")
CLAUDE_PLUGIN_JSON = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")
HOOKS_JSON = os.path.join(PLUGIN_ROOT, "hooks", "hooks.json")


class CodexPluginManifestTest(unittest.TestCase):
    def test_manifest_exists_and_validates(self):
        with open(CODEX_PLUGIN_JSON, encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["name"], "sniff")
        self.assertIn("version", manifest)
        self.assertIn("skills", manifest)
        self.assertIn("interface", manifest)

    def _default_prompts(self) -> list[str]:
        with open(CODEX_PLUGIN_JSON, encoding="utf-8") as fh:
            return json.load(fh)["interface"]["defaultPrompt"]

    def test_default_prompts_are_prose_not_cli_invocations(self):
        """Starter prompts are what a user clicks, so they read as sentences.

        The spec's own examples are prose ("Use My Plugin to summarize new CRM
        notes."), never bare commands. Asserting shape rather than literal
        substrings also keeps the copy editable: an earlier version of this test
        grepped for "sniff-create", which forced the user-facing wording to
        carry an internal skill name.
        """

        for prompt in self._default_prompts():
            self.assertTrue(prompt[0].isupper(), prompt)
            self.assertTrue(prompt.endswith("."), prompt)
            self.assertIn("sniff", prompt)

    def test_default_prompts_cover_scan_list_and_create(self):
        joined = " ".join(self._default_prompts()).lower()
        for intent in ("scan", "list", "create"):
            self.assertIn(intent, joined)


class SingleHookSourceTest(unittest.TestCase):
    """Guards the one-file-serves-both-hosts arrangement. Do not relax these.

    Claude Code and Codex both auto-discover hooks at exactly hooks/hooks.json,
    so that file is the single source of hooks for both. Two mistakes are easy
    to make here, and each one is silent at runtime:

    1. Re-adding an inline "hooks" block to .claude-plugin/plugin.json. The
       Claude manifest's "hooks" field is additive, not a replacement, so the
       Stop hook would register twice and nudge twice per turn.
    2. "Correcting" ${CLAUDE_PLUGIN_ROOT} to ${PLUGIN_ROOT} because this is a
       Codex-facing file. Codex sets both variables, but Claude Code sets only
       CLAUDE_PLUGIN_ROOT, so bare PLUGIN_ROOT breaks every hook under Claude.
    """

    def _hook_commands(self) -> list[str]:
        with open(HOOKS_JSON, encoding="utf-8") as fh:
            events = json.load(fh)["hooks"]
        return [
            entry["command"]
            for matchers in events.values()
            for matcher in matchers
            for entry in matcher["hooks"]
        ]

    def test_claude_manifest_declares_no_inline_hooks(self):
        with open(CLAUDE_PLUGIN_JSON, encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertNotIn("hooks", manifest)

    def test_codex_manifest_relies_on_auto_discovery(self):
        with open(CODEX_PLUGIN_JSON, encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertNotIn("hooks", manifest)

    def test_hook_commands_use_the_portable_plugin_root_variable(self):
        for command in self._hook_commands():
            self.assertNotRegex(command, r"\$\{?PLUGIN_ROOT")
            if "PLUGIN_ROOT" in command:
                self.assertIn("${CLAUDE_PLUGIN_ROOT}", command)

    def test_hook_commands_try_both_interpreter_names(self):
        """No single interpreter name is portable: most Linux and macOS boxes
        ship only `python3`, while a python.org install on Windows gives only
        `python`. Naming one of them strands every hook on the other platform,
        silently, because a hook that cannot start looks the same as one with
        nothing to say. `||` fires the second name only when the first is not a
        command, which holds in sh, cmd and PowerShell alike."""
        for command in self._hook_commands():
            self.assertIn("||", command)
            self.assertTrue(command.startswith("python3 "), command)
            self.assertIn("|| python ", command)

    def test_hook_scripts_always_exit_zero(self):
        """What makes the `||` chain safe: the fallback must mean "the first
        interpreter does not exist", never "the script ran and failed". A hook
        script that can exit non-zero would be run twice, and the SessionStart
        block would land in the session twice over."""
        for command in self._hook_commands():
            script = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}(\S+\.py)", command).group(1)
            path = os.path.join(PLUGIN_ROOT, script.lstrip("/").replace("/", os.sep))
            proc = subprocess.run([sys.executable, path], cwd=PLUGIN_ROOT,
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"{script}: {proc.stderr}")


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

        expanded = command.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN_ROOT)
        proc = subprocess.run(expanded, cwd=PLUGIN_ROOT, shell=True, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        # A scan would print per-detector "## name" markdown sections; prime never does.
        self.assertNotIn("## ", proc.stdout)
        self.assertIn("CAVEATS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
