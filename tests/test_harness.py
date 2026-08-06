#!/usr/bin/env python3
"""Unit tests for the shared ast-search engine.

Run: python -m pytest tests/test_harness.py -q

Tests that exercise scanning need the `ast-grep` binary on PATH; they skip
themselves cleanly if it is missing, so the pure-Python tests still run.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

from conftest import tool_available, write_tree_file

from sniff import harness as h

HAS_AST_GREP = tool_available("ast-grep")
HAS_GIT = tool_available("git")


def _short_path(path: str) -> str:
    """The 8.3 spelling of `path` on Windows, or `path` unchanged elsewhere."""
    if sys.platform != "win32":
        return path

    import ctypes

    buffer = ctypes.create_unicode_buffer(len(path) + 260)
    written = ctypes.windll.kernel32.GetShortPathNameW(path, buffer, len(buffer))
    return buffer.value if written else path


def _match(file, start, end, b_start, b_end, name="(anon)"):
    """Construct a Match without touching disk."""
    return h.Match(file=file, start_line=start, end_line=end,
                   byte_start=b_start, byte_end=b_end, name=name)


class MatchTest(unittest.TestCase):
    def test_line_span_is_inclusive(self):
        m = _match("a.py", 10, 12, 0, 0)
        self.assertEqual(m.lines, 3)

    def test_display_line_is_one_based(self):
        m = _match("a.py", 0, 0, 0, 0)
        self.assertEqual(m.line, 1)

    def test_location_uses_one_based_line(self):
        m = _match("src/a.py", 41, 41, 0, 0)
        self.assertEqual(m.location, "src/a.py:42")


class InIgnoredDirTest(unittest.TestCase):
    """_in_ignored_dir matches SNIFF_EXTRA_IGNORE globs against the path relative
    to the scan root, the same base sniff-patterns' format.py uses, so an
    ignore glob behaves identically across every detector."""

    def setUp(self):
        self._saved = os.environ.get("SNIFF_EXTRA_IGNORE")
        os.environ["SNIFF_EXTRA_IGNORE"] = "generated/**"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SNIFF_EXTRA_IGNORE", None)
        else:
            os.environ["SNIFF_EXTRA_IGNORE"] = self._saved

    def test_glob_matches_root_relative_for_scan_arg_prefixed_path(self):
        # ast-grep emits "<scan-arg>/generated/big.ts" for a relative scan path;
        # only the root-relative base ("generated/big.ts") matches "generated/**".
        self.assertTrue(h._in_ignored_dir("proj/generated/big.ts", "proj"))

    def test_glob_matches_root_relative_for_absolute_path(self):
        root = os.path.join("C:", os.sep, "work", "proj")
        abs_file = os.path.join(root, "generated", "big.ts")
        self.assertTrue(h._in_ignored_dir(abs_file, root))

    def test_glob_does_not_match_outside_ignored_dir(self):
        self.assertFalse(h._in_ignored_dir("proj/src/big.ts", "proj"))

    def test_trailing_slash_pattern_matches_a_file_directly_inside_the_dir(self):
        # A gitignore-style "docs/" entry, pasted straight into .sniff.toml's
        # [ignore] globs, must exclude the directory it names -- not silently
        # match nothing, which is what fnmatch("docs/a.md", "docs/") does on
        # its own (see _normalize_ignore_pattern).
        os.environ["SNIFF_EXTRA_IGNORE"] = "generated/"
        self.assertTrue(h._in_ignored_dir("proj/generated/big.ts", "proj"))

    def test_trailing_slash_pattern_matches_a_file_nested_inside_the_dir(self):
        os.environ["SNIFF_EXTRA_IGNORE"] = "generated/"
        self.assertTrue(h._in_ignored_dir("proj/generated/sub/deep.py", "proj"))

    def test_bare_name_without_trailing_slash_does_not_gain_directory_syntax(self):
        # "generated" (no trailing slash) stays today's literal/exact-match
        # pattern. Only the explicit trailing-slash form means "this dir".
        os.environ["SNIFF_EXTRA_IGNORE"] = "generated"
        self.assertFalse(h._in_ignored_dir("proj/generated/big.ts", "proj"))


class ExtraIgnorePatternsTest(unittest.TestCase):
    """_extra_ignore_patterns: the single choke point both --extra-ignore and
    SNIFF_EXTRA_IGNORE flow through, so a trailing-slash pattern normalizes the
    same way regardless of which one supplied it."""

    def setUp(self):
        self._saved = os.environ.get("SNIFF_EXTRA_IGNORE")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SNIFF_EXTRA_IGNORE", None)
        else:
            os.environ["SNIFF_EXTRA_IGNORE"] = self._saved

    def test_trailing_slash_expands_to_a_globstar_via_extra_ignore_arg(self):
        self.assertEqual(h._extra_ignore_patterns(["docs/"]), ["docs/**"])

    def test_trailing_slash_expands_to_a_globstar_via_env_var(self):
        os.environ["SNIFF_EXTRA_IGNORE"] = "docs/"
        self.assertEqual(h._extra_ignore_patterns(), ["docs/**"])

    def test_bare_name_without_slash_is_left_alone(self):
        # "docs" (no trailing slash) is today's literal/exact-match pattern,
        # not directory syntax. Expanding it too would start excluding any
        # file merely named "docs" alongside real directories, which nothing
        # asked for.
        self.assertEqual(h._extra_ignore_patterns(["docs"]), ["docs"])

    def test_existing_globstar_pattern_is_untouched(self):
        self.assertEqual(h._extra_ignore_patterns(["docs/**"]), ["docs/**"])


class VendoredDirScopeTest(unittest.TestCase):
    """The vendored-dir check only looks at segments at or below the scan root.

    A checkout can live anywhere, including under a directory that happens to be
    named like a build output ('build/', 'out/', 'vendor/') or under '.claude'
    (where Claude Code puts its worktrees). Counting those parent segments drops
    every AST match with no warning, which reads as 'this repo is clean'."""

    def test_ignored_name_above_scan_root_is_not_ignored(self):
        root = "C:/Users/me/.claude/worktrees/proj"
        self.assertFalse(h._in_ignored_dir(f"{root}/src/app.ts", root))

    def test_build_named_parent_above_scan_root_is_not_ignored(self):
        root = "/home/me/build/proj"
        self.assertFalse(h._in_ignored_dir(f"{root}/src/app.ts", root))

    def test_ignored_dir_below_scan_root_is_still_ignored(self):
        root = "C:/work/proj"
        self.assertTrue(h._in_ignored_dir(f"{root}/node_modules/pkg/index.ts", root))

    def test_without_root_the_check_stays_base_independent(self):
        # run() is not the only caller; format.py-style callers pass no root and
        # rely on the whole path being searched.
        self.assertTrue(h._in_ignored_dir("proj/dist/bundle.js"))


class FoldNestedTest(unittest.TestCase):
    def test_inner_match_folded_into_outer(self):
        outer = _match("a.ts", 0, 20, 0, 200, "outer")
        inner = _match("a.ts", 5, 15, 50, 150, "inner")
        kept = h.fold_nested([inner, outer])  # order should not matter
        self.assertEqual([m.name for m in kept], ["outer"])

    def test_siblings_both_kept(self):
        a = _match("a.ts", 0, 5, 0, 50, "a")
        b = _match("a.ts", 6, 10, 60, 100, "b")
        kept = h.fold_nested([a, b])
        self.assertEqual({m.name for m in kept}, {"a", "b"})

    def test_same_region_in_different_files_both_kept(self):
        a = _match("a.ts", 0, 5, 0, 50, "a")
        b = _match("b.ts", 0, 5, 0, 50, "b")
        kept = h.fold_nested([a, b])
        self.assertEqual(len(kept), 2)


class PrintTableTest(unittest.TestCase):
    def _render(self, matches, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            h.print_table(matches, [("LINES", lambda m: m.lines),
                                    ("NAME", lambda m: m.name),
                                    ("LOCATION", lambda m: m.location)], **kw)
        return buf.getvalue()

    def test_empty_prints_no_matches(self):
        self.assertIn("No matches.", self._render([]))

    def test_sort_and_top(self):
        rows = [_match("a.ts", 0, 4, 0, 0, "small"),
                _match("b.ts", 0, 99, 0, 0, "big")]
        out = self._render(rows, sort_key=lambda m: m.lines, top=1)
        self.assertIn("big", out)
        self.assertNotIn("small", out)

    def test_no_trailing_whitespace(self):
        rows = [_match("a.ts", 0, 4, 0, 0, "f")]
        for line in self._render(rows).splitlines():
            self.assertEqual(line, line.rstrip(), f"trailing space in: {line!r}")


@unittest.skipUnless(HAS_AST_GREP, "ast-grep not on PATH")
class ScanIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._write("src/app.py", """
            def small():
                return 1

            def big():
                a = 1
                b = 2
                c = 3
                return a + b + c
        """)
        # A test file + a node_modules file that must be ignored.
        self._write("src/app.test.py", "def in_test():\n    return 1\n")
        self._write("node_modules/dep.py", "def vendored():\n    return 1\n")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, rel, body):
        return write_tree_file(self.root, rel, body.lstrip("\n"))

    def test_detect_languages_skips_ignored_dirs(self):
        langs = h.detect_languages(self.root)
        self.assertIn("python", langs)

    def test_run_finds_functions_excludes_tests_and_vendor(self):
        kinds = {"python": ["function_definition"]}
        matches = h.run(kinds, self.root, lang="python")
        names = {m.name for m in matches}
        self.assertIn("small", names)
        self.assertIn("big", names)
        self.assertNotIn("in_test", names)    # *.test.* excluded
        self.assertNotIn("vendored", names)   # node_modules ignored

    def test_include_tests_flag(self):
        kinds = {"python": ["function_definition"]}
        matches = h.run(kinds, self.root, lang="python", include_tests=True)
        self.assertIn("in_test", {m.name for m in matches})

    def test_biggest_function_ranks_first(self):
        kinds = {"python": ["function_definition"]}
        matches = h.fold_nested(h.run(kinds, self.root, lang="python"))
        matches.sort(key=lambda m: m.lines, reverse=True)
        self.assertEqual(matches[0].name, "big")


class FileMetricTest(unittest.TestCase):
    """The file-metric engine helpers: iter_source_files + count_code_lines."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._write("src/app.ts", "const a = 1;\n\n\nconst b = 2;\n")   # 2 non-blank
        self._write("src/app.test.ts", "test('x', () => {});\n")
        self._write("node_modules/dep.ts", "export const x = 1;\n")
        self._write(".astro/content.d.ts", "declare module {}\n")        # generated, ignored
        self._write("README.md", "# not source\n")                       # unknown ext, ignored

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, rel, body):
        return write_tree_file(self.root, rel, body)

    def test_iter_excludes_vendor_generated_and_unknown(self):
        files = h.iter_source_files(self.root, include_tests=True)
        names = {os.path.basename(f) for f in files}
        self.assertIn("app.ts", names)
        self.assertIn("app.test.ts", names)        # tests included when asked
        self.assertNotIn("dep.ts", names)          # node_modules pruned
        self.assertNotIn("content.d.ts", names)    # .astro pruned
        self.assertNotIn("README.md", names)       # unknown extension

    def test_iter_excludes_tests_by_flag(self):
        files = h.iter_source_files(self.root, include_tests=False)
        names = {os.path.basename(f) for f in files}
        self.assertIn("app.ts", names)
        self.assertNotIn("app.test.ts", names)

    def test_iter_excludes_test_files_of_every_supported_ecosystem(self):
        """A header that says "tests excluded" has to be true beyond JavaScript.

        Matching only `*.test.ts` is how scrapy's test classes were ranked as
        production code while the header claimed they were filtered out."""
        self._write("pkg/test_client.py", "def test_x():\n    pass\n")
        self._write("pkg/client_test.py", "def test_x():\n    pass\n")
        self._write("pkg/conftest.py", "import pytest\n")
        self._write("pkg/server_test.go", "package pkg\n")
        self._write("pkg/client.py", "x = 1\n")

        names = {os.path.basename(f) for f in h.iter_source_files(self.root, include_tests=False)}

        self.assertIn("client.py", names, "production source must survive")
        for test_file in ("test_client.py", "client_test.py", "conftest.py", "server_test.go"):
            self.assertNotIn(test_file, names)

    def test_iter_excludes_helpers_living_in_a_test_directory(self):
        """Test helpers rarely carry a test-shaped filename. scrapy's
        tests/utils/bases/http_response.py holds a 399-line class that no naming
        convention would catch, so the directory itself has to count."""
        self._write("tests/utils/bases/http_response.py", "class TestResponseBase:\n    pass\n")
        self._write("src/lib/response.py", "class Response:\n    pass\n")

        names = {os.path.basename(f) for f in h.iter_source_files(self.root, include_tests=False)}

        self.assertIn("response.py", names)
        self.assertNotIn("http_response.py", names)

    def test_include_tests_still_brings_them_all_back(self):
        """The exclusion is a default, not a wall: --include-tests must undo it."""
        self._write("pkg/test_client.py", "def test_x():\n    pass\n")
        self._write("tests/helper.py", "def helper():\n    pass\n")

        names = {os.path.basename(f) for f in h.iter_source_files(self.root, include_tests=True)}

        self.assertIn("test_client.py", names)
        self.assertIn("helper.py", names)

    def test_a_source_file_merely_containing_test_in_its_name_is_kept(self):
        """`latest_test_results.py` is not a test, and `contest.py` is not conftest."""
        self._write("pkg/contest.py", "x = 1\n")
        self._write("pkg/attestation.py", "y = 2\n")

        names = {os.path.basename(f) for f in h.iter_source_files(self.root, include_tests=False)}

        self.assertIn("contest.py", names)
        self.assertIn("attestation.py", names)

    def test_count_code_lines_skips_blanks(self):
        path = next(f for f in h.iter_source_files(self.root) if f.endswith("app.ts"))
        self.assertEqual(h.count_code_lines(path), 2)


@unittest.skipUnless(HAS_GIT, "git not on PATH")
class GitignoreAwarenessTest(unittest.TestCase):
    """The os.walk-based walkers skip gitignored files, so they agree with the
    AST detectors (ast-grep filters through .gitignore natively).

    The other half of the contract matters just as much: when git cannot answer
    (no repo here, or no git at all) nothing may be hidden, otherwise every
    non-git project would suddenly scan as empty."""

    def setUp(self):
        # git answers are lru_cached on the root path; clearing keeps these tests
        # independent of each other and of whatever ran before them.
        h.reset_git_ignore_cache()
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        h.reset_git_ignore_cache()
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, rel, body):
        return write_tree_file(self.root, rel, body)

    def _git(self, *args, cwd=None):
        """Run one git command, failing the test on a non-zero exit.

        Identity is forced inline because a CI runner has no global user.name and
        `git commit` would otherwise abort."""
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=test", *args],
            cwd=cwd or self.root, capture_output=True, text=True, check=True,
        )

    def _git_init(self):
        subprocess.run(["git", "init", self.root], capture_output=True, text=True, check=True)

    def _add_submodule(self, name):
        """Commit a nested repo under `name` and record it in the outer index.

        Plain `git add` on a directory that is itself a repo writes the mode
        160000 gitlink, which is all `_git_submodule_dirs` reads. That avoids
        `git submodule add`, which clones over the file:// protocol and is
        refused by default on current git."""
        sub = os.path.join(self.root, name)
        os.makedirs(sub, exist_ok=True)
        subprocess.run(["git", "init", sub], capture_output=True, text=True, check=True)
        self._write(f"{name}/tracked.py", "a = 1\n")
        self._git("add", "-A", cwd=sub)
        self._git("commit", "-m", "init", cwd=sub)
        self._git("add", name)

    def test_iter_source_files_skips_gitignored_file(self):
        self._write(".gitignore", "skipme/\n")
        self._write("keep/a.py", "x = 1\n")
        self._write("skipme/b.py", "y = 2\n")
        self._git_init()

        files = h.iter_source_files(self.root)

        names = {os.path.basename(f) for f in files}
        self.assertIn("a.py", names)
        self.assertNotIn("b.py", names)

    def test_iter_source_files_keeps_everything_when_not_a_git_repo(self):
        # Same tree, no `git init`: git fails, _git_visible_files returns None,
        # and the walker must fall back to showing every source file.
        self._write(".gitignore", "skipme/\n")
        self._write("keep/a.py", "x = 1\n")
        self._write("skipme/b.py", "y = 2\n")

        self.assertIsNone(h._git_visible_files(os.path.abspath(self.root)),
                          "precondition: this tree is not a git repo")

        names = {os.path.basename(f) for f in h.iter_source_files(self.root)}
        self.assertIn("a.py", names)
        self.assertIn("b.py", names)

    def test_detect_languages_skips_gitignored_file(self):
        self._write(".gitignore", "skipme/\n")
        self._write("keep/a.ts", "const a = 1;\n")
        self._write("skipme/b.py", "y = 2\n")
        self._git_init()

        langs = h.detect_languages(self.root)

        self.assertIn("typescript", langs)
        self.assertNotIn("python", langs)

    def test_detect_languages_honors_extra_ignores(self):
        # This decides which detectors run at all, so it has to exclude the same
        # paths the scan itself will: otherwise an excluded language is still
        # detected and its detectors scan a set they were told to skip.
        self._write("keep/a.ts", "const a = 1;\n")
        self._write("generated/b.py", "y = 2\n")
        self._git_init()

        langs = h.detect_languages(self.root, ["generated/**"])

        self.assertIn("typescript", langs)
        self.assertNotIn("python", langs)

    def test_detect_languages_honors_a_trailing_slash_dir_ignore(self):
        # A gitignore-style "generated/" entry, copied straight into
        # .sniff.toml's [ignore] globs, must exclude the whole directory here
        # too -- the same choke point (_extra_ignore_patterns) this function
        # and the AST-based detectors both read.
        self._write("keep/a.ts", "const a = 1;\n")
        self._write("generated/sub/b.py", "y = 2\n")
        self._git_init()

        langs = h.detect_languages(self.root, ["generated/"])

        self.assertIn("typescript", langs)
        self.assertNotIn("python", langs)

    def test_submodule_tracked_file_stays_visible(self):
        # `git ls-files` stops at the gitlink, so the submodule has to be asked
        # separately. Without that every file under it reads as ignored, while
        # ast-grep keeps scanning them -- exactly the disagreement this filter
        # exists to remove, only inverted.
        self._write("root.py", "r = 1\n")
        self._git_init()
        self._add_submodule("sub")

        names = {os.path.basename(f) for f in h.iter_source_files(self.root)}

        self.assertIn("root.py", names)
        self.assertIn("tracked.py", names)

    def test_submodule_untracked_file_stays_visible(self):
        # An unignored file that is merely not committed yet is still real source,
        # and ast-grep reports it. `ls-files --recurse-submodules` cannot see it
        # (it rejects --others), which is why each submodule gets its own query.
        self._git_init()
        self._add_submodule("sub")
        self._write("sub/untracked.py", "b = 2\n")

        names = {os.path.basename(f) for f in h.iter_source_files(self.root)}

        self.assertIn("untracked.py", names)

    def test_submodule_gitignored_file_stays_hidden(self):
        # The submodule's own .gitignore still governs its contents; recursing
        # must not degrade into "everything under a submodule is visible".
        self._git_init()
        self._add_submodule("sub")
        # "artifacts" is deliberately not in IGNORE_DIRS: a name from that fixed
        # list would be pruned by the walker anyway and the test would pass even
        # with the gitignore filter gone.
        self._write("sub/.gitignore", "artifacts/\n")
        self._write("sub/artifacts/generated.py", "c = 3\n")

        names = {os.path.basename(f) for f in h.iter_source_files(self.root)}

        self.assertIn("tracked.py", names)
        self.assertNotIn("generated.py", names)

    def test_unchecked_out_submodule_does_not_recurse(self):
        # A submodule recorded in the index but never checked out is just an empty
        # directory. `git -C` inside it walks UP to the parent repo instead of
        # failing, and the parent reports that gitlink relative to the current
        # directory as ".", which joins straight back to the same path. Without a
        # guard the walk recurses on itself until RecursionError, so every
        # file-metric detector hangs on any shallow clone (submodules are not
        # initialized by default).
        self._write("root.py", "r = 1\n")
        self._git_init()

        # A gitlink pointing at a commit this clone does not have, plus the empty
        # placeholder directory git leaves behind: exactly the on-disk state of a
        # submodule that was never `--init`ed. Recording the index entry directly
        # avoids building a nested repo only to delete it, which Windows refuses
        # because git marks its object files read-only.
        os.makedirs(os.path.join(self.root, "sub"), exist_ok=True)
        self._git("update-index", "--add", "--cacheinfo",
                  "160000,6742055402de1aa48f93d12ded7d18f4057f9d1f,sub")
        h.reset_git_ignore_cache()

        names = {os.path.basename(f) for f in h.iter_source_files(self.root)}

        self.assertIn("root.py", names)

    @unittest.skipUnless(sys.platform == "win32", "8.3 aliases are a Windows filesystem feature")
    def test_repo_root_recognized_through_an_8_3_short_path(self):
        # Windows gives the same directory two spellings, and git always answers
        # with the long one. Compared as plain strings they differ, so a scan
        # started from the short spelling decided its own submodules were not
        # checked out and skipped every file in them. `%TEMP%` expands to the
        # short form whenever the user name is long, which is why this only ever
        # failed on CI: the runner user is `runneradmin`.
        self._git_init()
        short = _short_path(self.root)
        if os.path.normcase(short) == os.path.normcase(self.root):
            self.skipTest("this filesystem hands out no 8.3 alias for the temp dir")

        self.assertTrue(h._is_repo_root(short), f"{short} is the same repo as {self.root}")

    def test_reset_git_ignore_cache_forgets_the_previous_answer(self):
        # A library consumer that scans, writes files, and scans again would
        # otherwise keep filtering against the first scan's file list forever.
        self._write("first.py", "a = 1\n")
        self._git_init()
        first = {os.path.basename(f) for f in h.iter_source_files(self.root)}
        self._write("added_later.py", "d = 4\n")

        # The first scan is what fills the cache, and the second deliberately
        # still reflects it: caching within a run is the point, so `reset` is the
        # only thing that can make the new file appear.
        self.assertEqual({"first.py"}, first, "precondition: only the seed file exists")
        self.assertEqual({"first.py"}, {os.path.basename(f) for f in h.iter_source_files(self.root)},
                         "precondition: the cached answer survives a second scan")

        h.reset_git_ignore_cache()

        names = {os.path.basename(f) for f in h.iter_source_files(self.root)}
        self.assertIn("added_later.py", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
