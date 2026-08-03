#!/usr/bin/env python3
"""Tests for the duplicate-code detector (token-level clone detection).

Run: python -m pytest tests/test_duplicate_code.py -q
No ast-grep needed: this detector tokenises with a regex, it does not parse.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from sniff.detectors import duplicate_code as dc

# A block big enough to clear both defaults (30 tokens, 5 lines) with room to
# spare, so a test that fails is failing about duplication and not about size.
HANDLER = """
def handle(self, payload):
    result = self.parser.parse(payload)
    if result is None:
        raise ValueError("bad payload")
    for item in result.items:
        self.sink.write(item)
    return result
"""

# The same shape with every name changed: a type-2 clone.
RENAMED_HANDLER = """
def process(self, message):
    outcome = self.decoder.decode(message)
    if outcome is None:
        raise ValueError("bad message")
    for entry in outcome.entries:
        self.target.append(entry)
    return outcome
"""

# The same shape again, this time async: the tokens differ only by async/await.
ASYNC_HANDLER = """
async def handle(self, payload):
    result = await self.parser.parse(payload)
    if result is None:
        raise ValueError("bad payload")
    for item in result.items:
        await self.sink.write(item)
    return result
"""

# TypeScript imports, not Python ones: `from x import y` normalises to four
# distinct tokens and never reaches the "says almost nothing" guard, so only the
# braced form actually reaches the import-ratio guard this fixture is here to test.
IMPORT_BLOCK = """
import {FirstHelper, SecondHelper} from './helpers/first';
import {ThirdHelper, FourthHelper} from './helpers/second';
import {FifthHelper, SixthHelper} from './helpers/third';
import {SeventhHelper, EighthHelper} from './helpers/fourth';
import {NinthHelper, TenthHelper} from './helpers/fifth';
import {EleventhHelper, TwelfthHelper} from './helpers/sixth';
"""


class DuplicateCodeTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name: str, source: str) -> str:
        path = os.path.join(self.root, name).replace("\\", "/")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(source)
        return path

    def _clones(self, *paths: str, min_tokens: int = dc.DEFAULT_MIN_TOKENS,
                min_lines: int = dc.DEFAULT_MIN_LINES) -> "list[dc.Clone]":
        return dc.find_clones(list(paths), min_tokens=min_tokens, min_lines=min_lines)

    def test_exact_clone_across_files_is_reported_with_both_locations(self):
        first = self._write("a.py", HANDLER)
        second = self._write("b.py", HANDLER)

        clones = self._clones(first, second)

        self.assertEqual(len(clones), 1)
        self.assertEqual(clones[0].copies, 2)
        self.assertEqual({o.file for o in clones[0].occurrences}, {first, second})

    def test_clone_survives_renaming(self):
        # Identifiers normalise to ID, so copy-paste-and-rename still matches.
        first = self._write("a.py", HANDLER)
        second = self._write("b.py", RENAMED_HANDLER)

        clones = self._clones(first, second)

        self.assertEqual(len(clones), 1)
        self.assertEqual(clones[0].copies, 2)

    def test_sync_and_async_twins_match(self):
        # The asyncio-migration case: same method, one of them awaited.
        first = self._write("a.py", HANDLER)
        second = self._write("b.py", ASYNC_HANDLER)

        clones = self._clones(first, second)

        self.assertEqual(len(clones), 1)
        self.assertEqual(clones[0].copies, 2)

    def test_repeated_imports_are_not_reported(self):
        # The false-positive guard: shared import blocks are duplication every
        # reader expects, and they are long enough to outrank real clones.
        first = self._write("a.ts", IMPORT_BLOCK)
        second = self._write("b.ts", IMPORT_BLOCK)

        self.assertEqual(self._clones(first, second), [])

    def test_data_table_is_not_reported(self):
        # A lookup table long enough that one half matches the other half is
        # data, not logic: no keyword appears anywhere in it.
        rows = "\n".join(
            f"  [TestKey.KEY_{n}]: {{code: keyCodes.KEY_{n}, key: 'k{n}', label: 'l{n}'}},"
            for n in range(40)
        )
        path = self._write("table.ts", f"const TABLE = {{\n{rows}\n}};\n")

        self.assertEqual(self._clones(path), [])

    def test_blocks_below_the_thresholds_are_not_reported(self):
        source = "def tiny(a):\n    return a + 1\n"
        first = self._write("a.py", source)
        second = self._write("b.py", source)

        self.assertEqual(self._clones(first, second), [])

    def test_overlapping_ranges_collapse_to_one_copy(self):
        # Two windows 10 tokens apart are one 30-token region, not two copies.
        self.assertEqual(dc._without_overlaps([0, 10, 40, 45, 90], 30), [0, 40, 90])

    def test_copies_of_one_clone_never_overlap(self):
        # A run of near-identical methods matches itself a few tokens along. Each
        # copy must be a separate region, or one method reads as ten copies.
        methods = "\n".join(
            f"    def send_{n}(self, value):\n"
            f"        prepared = self.encoder.encode(value)\n"
            f"        if prepared is None:\n"
            f"            raise ValueError('bad value')\n"
            f"        self.channel.publish(prepared)\n"
            f"        return prepared\n"
            for n in range(8)
        )
        path = self._write("repetitive.py", f"class Sender:\n{methods}")

        for clone in self._clones(path):
            spans = sorted((o.start_line, o.end_line) for o in clone.occurrences)
            for earlier, later in zip(spans, spans[1:]):
                self.assertLess(earlier[1], later[0], f"overlapping copies: {spans}")

    def test_copy_counts_say_when_they_stop_counting(self):
        # More copies than the search looks at: the count must announce itself as
        # a floor rather than read as a total.
        block = (
            "def handler_{n}(self, payload):\n"
            "    result = self.parser.parse(payload)\n"
            "    if result is None:\n"
            "        raise ValueError('bad payload')\n"
            "    for item in result.items:\n"
            "        self.sink.write(item)\n"
            "    return result\n"
        )
        copies = "\n".join(block.format(n=n) for n in range(dc.MAX_GROUP_MEMBERS + 6))
        path = self._write("many.py", copies)

        clones = self._clones(path)

        self.assertTrue(clones[0].capped)
        self.assertLessEqual(clones[0].copies, dc.MAX_GROUP_MEMBERS + 1)

    def test_degenerate_thresholds_are_refused(self):
        # A zero-token window used to index past the end of the corpus and dump a
        # traceback on the user mid-scan.
        self._write("a.py", HANDLER)

        for flag in ("--min-tokens", "--min-lines"):
            with self.subTest(flag=flag), self.assertRaises(SystemExit) as raised:
                dc.main([self.root, flag, "0"])
            self.assertIn("must be at least", str(raised.exception))

    def test_clones_stay_inside_one_file(self):
        # Files sit end to end in one token array; a clone must not span the seam.
        first = self._write("a.py", HANDLER)
        second = self._write("b.py", HANDLER)

        for clone in self._clones(first, second):
            for occurrence in clone.occurrences:
                self.assertIn(occurrence.file, {first, second})
                self.assertLessEqual(occurrence.start_line, occurrence.end_line)

    def test_minified_bundle_is_skipped(self):
        # Token-rich enough to clear every other guard: only the line length
        # tells this file apart from code somebody maintains.
        line = "".join(f"function f{n}(x){{if(x)return x+{n};return null;}}" for n in range(60))
        block = "\n".join(f"{line}// chunk {n}" for n in range(6))
        path = self._write("bundle.js", f"{block}\n{block}\n")

        self.assertEqual(self._clones(path), [])

    def test_comments_do_not_create_clones(self):
        # Two files whose only shared text is a long comment share no tokens.
        comment = "\n".join(f"# shared explanation line number {n}" for n in range(20))
        first = self._write("a.py", comment + "\nvalue = 1\n")
        second = self._write("b.py", comment + "\nother = 2\n")

        self.assertEqual(self._clones(first, second), [])


class TokenizerTest(unittest.TestCase):
    def _values(self, source: str) -> "list[str]":
        return [t.value for t in dc.tokenize(source)]

    def test_identifiers_and_literals_normalize(self):
        self.assertEqual(
            self._values("x = compute(42, 'text')"),
            ["ID", "=", "ID", "(", "NUM", ",", "STR", ")"],
        )

    def test_keywords_survive_normalization(self):
        self.assertEqual(self._values("if x: return 1"), ["if", "ID", ":", "return", "NUM"])

    def test_async_and_await_are_dropped(self):
        self.assertEqual(self._values("async def f(): await g()"),
                         self._values("def f(): g()"))

    def test_lines_are_tracked_per_token(self):
        tokens = dc.tokenize("first = 1\nsecond = 2\n")
        self.assertEqual([t.line for t in tokens], [1, 1, 1, 2, 2, 2])


if __name__ == "__main__":
    unittest.main()
