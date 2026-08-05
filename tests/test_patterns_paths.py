#!/usr/bin/env python3
"""Behavioural tests for sniff.patterns.paths: relativizing paths, vendored-dir
skipping, and the extra-ignore glob semantics shared with the harness.

paths.py is pure path/string handling (no ast-grep involved), so every test
here runs unconditionally: no @unittest.skipUnless(tool_available(...)) guard
is needed.

Run: python -m pytest tests/test_patterns_paths.py -q
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from sniff import harness as h
from sniff.patterns import paths


class RelTest(unittest.TestCase):
    """_rel: scan-root-relative, forward-slashed, findings-table-friendly paths."""

    def test_relativizes_and_forward_slashes_the_path(self):
        root = os.path.join("C:" + os.sep, "work", "proj")
        file = os.path.join(root, "src", "app.ts")

        self.assertEqual(paths._rel(file, root), "src/app.ts")

    def test_relpath_failure_falls_back_to_the_original_forward_slashed_path(self):
        # os.path.relpath only raises ValueError for a cross-drive pair on
        # ntpath; posixpath silently returns "../D:/other/app.ts" instead.
        # Patching relpath itself (rather than relying on a real drive
        # mismatch) exercises the except branch on every OS, so this stays
        # green on the ubuntu/macos CI legs too.
        file = os.path.join("D:" + os.sep, "other", "app.ts")
        root = os.path.join("C:" + os.sep, "work")

        with mock.patch("os.path.relpath", side_effect=ValueError):
            self.assertEqual(paths._rel(file, root), "D:/other/app.ts")

    @unittest.skipUnless(os.name == "nt", "cross-drive ValueError only actually happens on ntpath")
    def test_different_drive_falls_back_to_the_original_path_on_windows(self):
        # Belt-and-braces real-world case behind the platform it's true on,
        # alongside the platform-independent mock above.
        file = os.path.join("D:" + os.sep, "other", "app.ts")
        root = os.path.join("C:" + os.sep, "work")

        self.assertEqual(paths._rel(file, root), "D:/other/app.ts")


class InIgnoredDirTest(unittest.TestCase):
    """_in_ignored_dir: vendored/build segments at-or-below root, never above it."""

    def test_matches_a_vendored_segment_below_the_scan_root(self):
        root = os.path.join("C:" + os.sep, "work", "proj")
        path = os.path.join(root, "node_modules", "pkg", "index.ts")

        self.assertTrue(paths._in_ignored_dir(path, root))

    def test_ignores_a_vendored_segment_above_the_scan_root(self):
        # A checkout can live under a parent directory literally named "build"
        # or ".claude" (where Claude Code puts its worktrees). Counting those
        # parent segments would drop every finding in the repo, and an empty
        # result reads as "clean" rather than as a bug.
        root = os.path.join("C:" + os.sep, "Users", "me", ".claude", "worktrees", "proj")
        path = os.path.join(root, "src", "app.ts")

        self.assertFalse(paths._in_ignored_dir(path, root))

    def test_clean_source_path_is_not_ignored(self):
        root = os.path.join("C:" + os.sep, "work", "proj")
        path = os.path.join(root, "src", "app.ts")

        self.assertFalse(paths._in_ignored_dir(path, root))

    def test_ignore_dirs_stay_the_same_object_as_the_harness(self):
        # paths.py declares its own IGNORE_DIRS name so scan.py/format.py can
        # import it locally, but it must never fork into a second, driftable
        # copy of the harness's vendored-dir list.
        self.assertIs(paths.IGNORE_DIRS, h.IGNORE_DIRS)


class MatchesExtraIgnoreTest(unittest.TestCase):
    """_matches_extra_ignore: the same fnmatch-based glob semantics as the harness."""

    def setUp(self):
        self.root = os.path.join("C:" + os.sep, "work", "proj")

    def test_no_patterns_short_circuits_before_relativizing(self):
        # any([]) is already False, so asserting False here would still pass
        # with the `if not patterns: return False` guard deleted -- that
        # deleted guard would just fall through to _rel() and then to
        # any([]) anyway. Patching _rel to blow up proves the guard actually
        # short-circuits before touching the path at all.
        path = os.path.join(self.root, "generated", "types.ts")

        with mock.patch("sniff.patterns.paths._rel", side_effect=AssertionError("_rel must not be called")):
            self.assertFalse(paths._matches_extra_ignore(path, self.root, []))

    def test_glob_matches_a_file_relative_to_the_scan_root(self):
        path = os.path.join(self.root, "generated", "types.ts")
        self.assertTrue(paths._matches_extra_ignore(path, self.root, ["generated/*"]))

    def test_glob_that_does_not_match_returns_false(self):
        path = os.path.join(self.root, "src", "app.ts")
        self.assertFalse(paths._matches_extra_ignore(path, self.root, ["generated/*"]))

    def test_star_glob_crosses_directory_boundaries_like_fnmatch(self):
        # fnmatch's `*` is not a directory-aware globstar: unlike a "real" glob
        # engine, `generated/*` still reaches into a nested subdirectory. This
        # proves paths.py inherited fnmatch's actual semantics rather than some
        # stricter one, since the harness's own extra-ignore matching is fnmatch
        # underneath (see sniff.harness.gitignore._matches_extra_ignore).
        path = os.path.join(self.root, "generated", "sub", "file.ts")
        self.assertTrue(paths._matches_extra_ignore(path, self.root, ["generated/*"]))

    # (path relative to root, forward-slashed) paired with the extra-ignore
    # glob list to try it against. Covers the pattern shapes a real
    # .sniff.toml [ignore] globs entry could plausibly use: a directory
    # wildcard, an extension wildcard, a doubled-star, a bare literal
    # (matching only itself, fnmatch has no directory-aware globstar), a
    # trailing slash, and a "./"-prefixed pattern.
    PARITY_CASES = [
        ("generated/types.ts", ["generated/*"]),
        ("src/app.ts", ["*.ts"]),
        ("deep/gen/file.ts", ["**/gen/*"]),
        ("generated", ["generated"]),
        ("generated/sub/file.ts", ["generated"]),
        ("generated/types.ts", ["generated/"]),
        ("generated/types.ts", ["./generated/*"]),
    ]

    def test_matches_the_harnesss_own_glob_result_for_every_pattern_shape(self):
        # Each expected value is computed live from the harness, not
        # hand-guessed, so this stays correct even if fnmatch's exact
        # cross-platform quirks shift: what it proves is that paths.py's
        # relativize-then-match wiring never disagrees with the harness on
        # any of these shapes.
        for rel, patterns in self.PARITY_CASES:
            with self.subTest(rel=rel, patterns=patterns):
                path = os.path.join(self.root, *rel.split("/"))
                expected = h._matches_extra_ignore(rel, patterns)
                self.assertEqual(paths._matches_extra_ignore(path, self.root, patterns), expected)

    def test_delegates_the_actual_pattern_loop_to_the_harness(self):
        # The parity test above cannot, by itself, catch the exact regression
        # the comment at paths.py:49-53 warns about: forking line 67 into a
        # local `any(fnmatch.fnmatch(rel, p) for p in patterns)` copy is
        # behaviourally identical today, so it would leave every glob-shape
        # assertion green. Only a call-level check on the harness function
        # itself can prove genuine delegation rather than a coincidentally
        # matching reimplementation.
        path = os.path.join(self.root, "generated", "types.ts")

        with mock.patch("sniff.patterns.paths.h._matches_extra_ignore", return_value="sentinel") as mocked:
            result = paths._matches_extra_ignore(path, self.root, ["generated/*"])

        mocked.assert_called_once_with("generated/types.ts", ["generated/*"])
        self.assertEqual(result, "sentinel")

    def test_extra_ignore_pattern_reader_stays_the_same_object_as_the_harness(self):
        # Guards a different re-export than the delegation test above:
        # `_extra_ignore_patterns` (the SNIFF_EXTRA_IGNORE/--extra-ignore
        # reader) must also stay the harness's own function, not a fork.
        self.assertIs(paths._extra_ignore_patterns, h._extra_ignore_patterns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
