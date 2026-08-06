#!/usr/bin/env python3
"""Guards for the shipped SKILL.md files.

Every skill repeats the same install instruction, with one optional clause: the
ast-grep line, which belongs only to detectors that actually parse code. Keeping
15 files in step by hand means 14 synchronized edits every time the wording
changes, so divergence fails the build here instead of shipping half-updated
instructions to agents.

The umbrella skill also names every detector it runs; a detector added without
touching that list would be invisible to any agent reading the skill.

Run: python -m pytest tests/test_skill_docs.py -q
"""

from __future__ import annotations

import glob
import os
import re
import unittest

from sniff import discovery

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SKILLS_GLOB = os.path.join(REPO_ROOT, "skills", "*", "SKILL.md")
SNIFF_SKILL = os.path.join(REPO_ROOT, "skills", "sniff", "SKILL.md")

# The install instruction, from its first word to whichever clause ends it.
INSTALL_RE = re.compile(
    r"If `sniff version` fails.*?(?:is missing\)\.|`uv tool install sniff-smells`\.)", re.DOTALL)
AST_GREP_CLAUSE = "and `uv tool install ast-grep-cli` if `ast-grep` is missing"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _install_sentence(text: str) -> str:
    """The install instruction, whitespace-normalized, or "" when absent."""
    match = INSTALL_RE.search(text)
    return re.sub(r"\s+", " ", match.group(0)).strip() if match else ""


def _sentences_by_skill() -> "dict[str, str]":
    found = {}
    for path in glob.glob(SKILLS_GLOB):
        sentence = _install_sentence(_read(path))
        if sentence:
            found[os.path.basename(os.path.dirname(path))] = sentence
    return found


class InstallBoilerplateTest(unittest.TestCase):
    def setUp(self):
        self.sentences = _sentences_by_skill()

    def test_every_skill_carries_the_install_instruction(self):
        self.assertGreaterEqual(len(self.sentences), 14, sorted(self.sentences))

    def test_only_the_ast_grep_clause_may_differ(self):
        """Two spellings at most: with the ast-grep clause and without it, where
        the shorter one is a prefix of the longer."""
        variants = sorted(set(self.sentences.values()), key=len)
        self.assertLessEqual(len(variants), 2, variants)
        if len(variants) == 2:
            short, long = variants
            self.assertTrue(long.startswith(short.rstrip(".")), variants)

    def test_ast_grep_clause_matches_what_the_detector_needs(self):
        """A detector that never runs ast-grep must not tell agents to install it,
        and one that does must say so."""
        needs = {d.name: d.needs_ast_grep for d in discovery.discover()[0]}
        for skill, sentence in sorted(self.sentences.items()):
            if skill not in needs:  # the umbrella skill runs everything
                continue
            self.assertEqual(AST_GREP_CLAUSE in sentence, needs[skill], skill)


class SniffSkillDetectorListTest(unittest.TestCase):
    def test_sniff_skill_names_every_detector(self):
        text = _read(SNIFF_SKILL)
        detectors, _ = discovery.discover()
        missing = [d.name for d in detectors if d.name not in text]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
