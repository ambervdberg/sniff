"""Walking a tree: which directories to skip, which files are tests, and the
supported source files (and their line counts) that remain."""

from __future__ import annotations

import os
import re

from sniff.harness.gitignore import (
    _extra_ignore_patterns,
    _is_gitignored,
    _matches_extra_ignore,
)
from sniff.harness.langs import EXT_LANG

# Directories that never contain hand-written source worth ranking.
IGNORE_DIRS = {
    "node_modules", "dist", "build", "out", "coverage", ".git", ".nx",
    ".angular", ".astro", ".next", ".svelte-kit", ".nuxt", ".turbo",
    "vendor", "target", "__pycache__", ".venv", "venv", ".claude",
}

# Files that look like tests, excluded unless the caller opts in.
#
# Every supported ecosystem names its tests differently, and a detector header
# that says "tests excluded" has to be true for all of them. Matching only the
# JavaScript spelling is how scrapy's test classes ended up ranked as production
# code while the header claimed otherwise.
TEST_RE = re.compile(
    r"""
      \.(spec|test)\.[a-z]+$      # JS/TS:  thing.test.ts, thing.spec.tsx
    | (^|/)test_[^/]*\.py$        # Python: test_thing.py
    | _test\.py$                  # Python: thing_test.py
    | (^|/)conftest\.py$          # Python: pytest's shared fixtures
    | _test\.go$                  # Go:     thing_test.go
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Directories whose entire contents are test code. Filename rules alone leave the
# helpers behind (scrapy's tests/utils/bases/http_response.py defines a 399-line
# class that no test-file naming convention would catch).
TEST_DIRS = {"tests", "test", "__tests__", "spec", "specs"}


def is_test_file(path: str) -> bool:
    """True if `path` is test code rather than the source being measured."""
    normalized = path.replace("\\", "/")
    if TEST_RE.search(normalized):
        return True
    return any(segment in TEST_DIRS for segment in normalized.split("/")[:-1])


def _in_ignored_dir(
    path: str, root: "str | None" = None, extra_ignores: "list[str] | None" = None
) -> bool:
    """True if any path segment is an ignored (vendored/build) directory, or the
    path matches an extra-ignore glob (see `_extra_ignore_patterns`).

    Both checks run on `path` relative to `root` (forward-slashed). For the glob
    check that base makes a consumer's `[ignore] globs` match the same
    scan-root-relative path that sniff-patterns' format.py matches against;
    without it, an absolute or scan-arg-prefixed file path would never match a
    pattern like `generated/**`.

    The vendored-dir check needs the same base for a different reason: a checkout
    can live anywhere, including under a parent directory named `build`, `out`,
    `vendor`, or `.claude` (where Claude Code puts its worktrees). Matching
    segments above the scan root would drop every match in the repo and, because
    an empty result is indistinguishable from a clean one, report it as no
    findings rather than as an error.

    Extends the fixed vendored-dir list rather than replacing it, so both apply
    together."""
    rel = path
    if root is not None:
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            # Different drive on Windows: relpath raises, keep the original path.
            rel = path
    norm = rel.replace("\\", "/")

    if any(seg in IGNORE_DIRS for seg in norm.split("/")):
        return True
    patterns = _extra_ignore_patterns(extra_ignores)
    return _matches_extra_ignore(norm, patterns)


def detect_languages(root: str, extra_ignores: "list[str] | None" = None) -> set[str]:
    """Walk the tree once and collect which supported languages are present.

    Gitignored files are skipped when `root` is a git repo (see `_is_gitignored`),
    so this agrees with the AST-based detectors, which ast-grep already filters
    through .gitignore natively.

    `extra_ignores`, when a non-empty list, drops files matching one of those
    globs as well, matching `iter_source_files` and `run()`. Sharing the exclusion
    list matters because this function decides which languages a run scans at all:
    without it, `--ignore "**/*.py"` would still detect python and send every
    python detector off to scan a set of files it had just excluded."""
    found: set[str] = set()

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in place so os.walk never descends into them.
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        for name in filenames:
            lang = EXT_LANG.get(os.path.splitext(name)[1].lower())
            if not lang:
                continue
            path = os.path.join(dirpath, name)
            if extra_ignores and _in_ignored_dir(path, root, extra_ignores):
                continue
            if _is_gitignored(path, root):
                continue
            found.add(lang)

    return found


def iter_source_files(
    root: str, include_tests: bool = True, extra_ignores: "list[str] | None" = None
) -> "list[str]":
    """Yield supported source file paths (forward-slashed) under root.

    The file-metric engine's counterpart to detect_languages: it walks once,
    prunes ignored directories, keeps only known source extensions, and (unless
    include_tests) drops *.spec.* / *.test.* files. `extra_ignores`, when a
    non-empty list, additionally drops files matching one of those globs
    (scan-root-relative), mirroring `run()`'s handling for AST-based detectors.
    Gitignored files are skipped when `root` is a git repo (see `_is_gitignored`),
    so this agrees with the AST-based detectors, which ast-grep already filters
    through .gitignore natively."""
    out: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        for name in filenames:
            if EXT_LANG.get(os.path.splitext(name)[1].lower()) is None:
                continue
            path = os.path.join(dirpath, name).replace("\\", "/")
            if not include_tests and is_test_file(path):
                continue
            if extra_ignores and _in_ignored_dir(path, root, extra_ignores):
                continue
            if _is_gitignored(path, root):
                continue
            out.append(path)

    return out


def count_code_lines(path: str) -> int:
    """Count non-blank lines in a file. A cheap proxy for 'how big is this file',
    deliberately not a comment-aware SLOC count (that is a separate tool's job)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0
