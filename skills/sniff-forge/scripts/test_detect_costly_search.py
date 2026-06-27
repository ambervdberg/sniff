#!/usr/bin/env python3
"""Tests for the suggest-forge detection heuristic.

Run: python skills/sniff-forge/scripts/test_detect_costly_search.py

Pure-Python, no external tools: the heuristic only reads transcript dicts.
"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import detect_costly_search as d  # noqa: E402


def user(text: str) -> dict:
    """A genuine user prompt line."""

    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def tool_result() -> dict:
    """A tool-result line (also typed 'user') that must NOT open a turn."""

    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
    }


def assistant_searches(*names: str) -> dict:
    """An assistant line issuing the given tool calls."""

    content = [{"type": "tool_use", "name": n, "input": {}} for n in names]
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


SIX_READS = assistant_searches(*(["Read"] * 6))


class StructuralPromptTest(unittest.TestCase):
    def test_lookup_plus_noun_is_structural(self):
        self.assertTrue(d.is_structural_prompt("which functions call login?"))
        self.assertTrue(d.is_structural_prompt("how many classes are there"))
        self.assertTrue(d.is_structural_prompt("find all usages of foo"))

    def test_lookup_or_noun_alone_is_not(self):
        self.assertFalse(d.is_structural_prompt("which one do you prefer"))
        self.assertFalse(d.is_structural_prompt("refactor this class please"))
        self.assertFalse(d.is_structural_prompt("fix the bug"))


class DetectTest(unittest.TestCase):
    def test_fires_on_costly_structural_turn(self):
        lines = [user("which methods call save?"), SIX_READS]
        result = d.detect(lines)
        self.assertTrue(result.fired)
        self.assertEqual(result.search_calls, 6)
        self.assertTrue(result.structural_prompt)

    def test_silent_when_below_threshold(self):
        lines = [user("which methods call save?"), assistant_searches("Read", "Grep", "Glob")]
        self.assertFalse(d.detect(lines).fired)

    def test_silent_when_prompt_not_structural(self):
        lines = [user("clean up the auth module"), SIX_READS]
        result = d.detect(lines)
        self.assertFalse(result.fired)
        self.assertEqual(result.search_calls, 6)

    def test_only_last_turn_counts(self):
        # First turn racks up reads; a fresh prompt must reset the tally.
        lines = [user("which classes exist?"), SIX_READS, user("thanks"), assistant_searches("Read")]
        result = d.detect(lines)
        self.assertEqual(result.search_calls, 1)
        self.assertFalse(result.fired)

    def test_tool_results_do_not_open_a_turn(self):
        # Interleaved tool_result lines must not reset the running count.
        lines = [user("how many services exist?"), assistant_searches("Read", "Read", "Read")]
        lines += [tool_result(), assistant_searches("Read", "Read", "Read")]
        result = d.detect(lines)
        self.assertEqual(result.search_calls, 6)
        self.assertTrue(result.fired)

    def test_non_search_tools_are_ignored(self):
        lines = [user("which functions exist?"), assistant_searches("Bash", "Edit", "Write", "Bash")]
        self.assertEqual(d.detect(lines).search_calls, 0)

    def test_threshold_is_tunable(self):
        lines = [user("which functions exist?"), assistant_searches("Read", "Read")]
        self.assertTrue(d.detect(lines, min_calls=2).fired)
        self.assertFalse(d.detect(lines, min_calls=3).fired)

    def test_top_level_content_string_shape(self):
        # Tolerate a line that puts a bare string content at the top level.
        line = {"type": "user", "content": "which methods exist?"}
        lines = [line, SIX_READS]
        self.assertTrue(d.detect(lines).fired)


if __name__ == "__main__":
    unittest.main()
