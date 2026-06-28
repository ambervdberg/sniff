#!/usr/bin/env python3
"""Integration test: the Stop hook is wired in plugin.json and behaves.

Proves Phase 4 end-to-end without a live Claude session: read the Stop-hook
command straight out of plugin.json, expand ${CLAUDE_PLUGIN_ROOT}, then run it
exactly as the harness would, feeding synthetic Stop-hook JSON on stdin.

AC: a single nudge line on a costly structural turn; nothing on a normal turn.

Run: python skills/sniff-create/scripts/test_hook_wiring.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
# repo root = plugin root: scripts -> sniff-create -> skills -> <root>
PLUGIN_ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
PLUGIN_JSON = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")


def stop_hook_command() -> str:
    """The expanded Stop-hook command as declared in plugin.json."""

    manifest = json.load(open(PLUGIN_JSON, encoding="utf-8"))
    command = manifest["hooks"]["Stop"][0]["hooks"][0]["command"]
    return command.replace("${CLAUDE_PLUGIN_ROOT}", PLUGIN_ROOT)


def _user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def _assistant(*tools: str) -> dict:
    content = [{"type": "tool_use", "name": t, "input": {}} for t in tools]
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


class HookWiringTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.command = stop_hook_command()

    def _run_turn(self, lines: list[dict]) -> subprocess.CompletedProcess:
        """Write a transcript, hand its path to the hook command on stdin."""

        transcript = os.path.join(self.dir, "t.jsonl")
        with open(transcript, "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(x) for x in lines))

        hook_json = json.dumps({"transcript_path": transcript})

        # shell=True so the quoted ${CLAUDE_PLUGIN_ROOT} path is parsed as one arg.
        return subprocess.run(
            self.command, input=hook_json, shell=True, capture_output=True, text=True
        )

    def test_costly_turn_emits_single_nudge(self):
        proc = self._run_turn([_user("which methods call save?"), _assistant(*(["Read"] * 6))])
        self.assertEqual(proc.returncode, 0)
        nudge_lines = [ln for ln in proc.stdout.splitlines() if "sniff-create" in ln]
        self.assertEqual(len(nudge_lines), 1)  # exactly one nudge, never a wall

    def test_normal_turn_is_silent(self):
        proc = self._run_turn([_user("fix the login bug"), _assistant("Edit")])
        self.assertEqual(proc.stdout.strip(), "")
        # Always exit 0: empty stdout is the silence. A non-zero exit would surface
        # a spurious "non-blocking status code" error after every quiet turn.
        self.assertEqual(proc.returncode, 0)

    def test_hook_is_registered_as_stop(self):
        manifest = json.load(open(PLUGIN_JSON, encoding="utf-8"))
        self.assertIn("Stop", manifest.get("hooks", {}))


if __name__ == "__main__":
    unittest.main()
