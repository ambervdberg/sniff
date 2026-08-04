#!/usr/bin/env python3
"""Path and ignore-list helpers shared by the scan and CLI layers.

Split out of format.py so both `scan.py` (which prunes vendored dirs while
walking the filesystem) and `format.py` (which filters ast-grep's raw matches
before they reach the findings table) can use the exact same ignore rules
without importing each other.
"""

from __future__ import annotations

import fnmatch
import os
import re

from sniff import harness as h

# Taken from the harness rather than copied. The copy that used to live here had
# already drifted: it never learned about .astro, .svelte-kit, .nuxt or .turbo, so
# pattern rules reported build output that every other detector skipped.
IGNORE_DIRS = h.IGNORE_DIRS


def _rel(file: str, root: str) -> str:
    """File path relative to the scan root, forward-slashed.

    Absolute paths make every table row hundreds of chars wide; stripping the
    common scan-root prefix keeps rows short so the markdown table renders, while
    the path stays unambiguous (it is relative to the scanned dir)."""
    try:
        rel = os.path.relpath(file, root)
    except ValueError:
        # Different drive on Windows: relpath raises, keep the absolute path.
        rel = file
    return rel.replace("\\", "/")


def _in_ignored_dir(path: str, root: "str | None" = None) -> bool:
    """True if a path segment at or below `root` is a vendored/build directory.

    Segments above the scan root do not count: a checkout can live under a parent
    named `build`, `out`, `vendor`, or `.claude` (where Claude Code puts its
    worktrees), and matching those would drop every finding in the repo. Since an
    empty result looks exactly like a clean one, that failure reports as "no
    smells" rather than as an error. Mirrors harness._in_ignored_dir."""
    scoped = _rel(path, root) if root is not None else path
    return any(seg in IGNORE_DIRS for seg in re.split(r"[\\/]", scoped))


def _extra_ignore_patterns(extra_ignores: "list[str] | None" = None) -> list[str]:
    """Glob patterns to exclude on top of the fixed vendored-dir list.

    `extra_ignores` is the parsed `--extra-ignore` args cli.py folds in from
    `.sniff.toml`'s `[ignore] globs = "..."`; when given (even empty), it wins.
    Only when it is absent (None) does this fall back to the SNIFF_EXTRA_IGNORE
    env var, which cli.py sets around subprocess/external detectors. Mirrors
    harness._extra_ignore_patterns so both engines resolve ignores identically."""
    if extra_ignores is not None:
        return [p.strip() for p in extra_ignores if p.strip()]
    raw = os.environ.get("SNIFF_EXTRA_IGNORE", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _matches_extra_ignore(path: str, root: str, patterns: list[str]) -> bool:
    """True if `path` (relative to `root`) matches any extra-ignore glob.

    Extends _in_ignored_dir's hardcoded vendored-dir list rather than replacing
    it, so both the fixed ignore list and a consumer's own .sniff.toml globs
    apply together."""
    if not patterns:
        return False
    rel = _rel(path, root)
    return any(fnmatch.fnmatch(rel, pat) for pat in patterns)
