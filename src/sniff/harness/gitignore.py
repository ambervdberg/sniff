"""What git says a repo ignores, plus the extra-ignore globs from config.

Asking git is deliberate: .gitignore semantics are far too subtle to
reimplement, and it is what ast-grep honors natively, so both engines agree."""

from __future__ import annotations

import fnmatch
import functools
import os
import subprocess

def _extra_ignore_patterns(extra_ignores: "list[str] | None" = None) -> list[str]:
    """Glob patterns to exclude, comma-separated where applicable.

    `extra_ignores` is the parsed `--extra-ignore` args a built-in detector
    collected from argparse; when given (even an empty list), it wins outright.
    Only when it is absent (None) does this fall back to SNIFF_EXTRA_IGNORE (set
    by cli.py around subprocess/external detectors, from .sniff.toml's
    `[ignore] globs = "..."`)."""
    if extra_ignores is not None:
        return [p.strip() for p in extra_ignores if p.strip()]
    raw = os.environ.get("SNIFF_EXTRA_IGNORE", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def _matches_extra_ignore(rel: str, patterns: "list[str]") -> bool:
    """True if a scan-root-relative, forward-slashed path matches any extra-ignore glob.

    Shared by `_in_ignored_dir` here and by `sniff.patterns.paths._matches_extra_ignore`,
    so both engines resolve `.sniff.toml`'s `[ignore] globs` against the same rule
    instead of maintaining two copies of the same fnmatch loop."""
    return any(fnmatch.fnmatch(rel, pat) for pat in patterns)


def _run_git(root: str, args: "list[str]") -> "str | None":
    """stdout of `git -C <root> <args>`, or None when git cannot answer.

    Both failure modes collapse into one return value on purpose: every caller
    here treats "git is missing" and "this is not a repo" the same way, by falling
    back to the fixed IGNORE_DIRS list alone."""
    try:
        proc = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None  # git not installed
    if proc.returncode != 0:
        return None  # not a git repo (or other git failure)
    return proc.stdout


@functools.lru_cache(maxsize=None)
def _is_repo_root(path: str) -> bool:
    """True if `path` is the top level of its own git repository.

    `git -C` on a directory that is not a repo does not fail: it walks up until
    it finds one. A submodule recorded in the index but never checked out is an
    empty directory, so every query inside it is answered by the parent repo,
    which reports that gitlink relative to the current directory as "." -- a path
    that joins straight back to where we started. Comparing the resolved top
    level against the directory itself is what tells the two cases apart."""
    out = _run_git(path, ["rev-parse", "--show-toplevel"])
    if out is None:
        return False
    return _same_dir(out.strip(), path)


def _same_dir(left: str, right: str) -> bool:
    """True if two path strings name the same directory.

    `realpath`, not `abspath`: on Windows the same directory has two spellings,
    and git always answers with the long one. A caller working under a path that
    contains an 8.3 alias (`C:\\Users\\RUNNER~1\\...`, which is what `%TEMP%`
    expands to for a long user name) would otherwise compare unequal to itself.
    It also collapses symlinks, which does the same job on POSIX."""
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


@functools.lru_cache(maxsize=None)
def _git_submodule_dirs(root: str) -> "tuple[str, ...]":
    """Root-relative paths of the submodules recorded in `root`'s index.

    A submodule is a gitlink: a single index entry with mode 160000 standing in
    for an entire nested repo. `ls-files` never descends through one, so every
    file inside a submodule would otherwise be absent from the visible set and
    read as ignored (see `_git_visible_files`)."""
    out = _run_git(root, ["ls-files", "--stage", "-z"])
    if out is None:
        return ()

    # `--stage` records are "<mode> <object> <stage>\t<path>", NUL-separated.
    dirs: list[str] = []
    for record in out.split("\0"):
        if not record.startswith("160000 "):
            continue
        _metadata, _tab, path = record.partition("\t")
        if path:
            dirs.append(path)

    return tuple(dirs)


@functools.lru_cache(maxsize=None)
def _git_visible_files(root: str) -> "frozenset[str] | None":
    """Root-relative forward-slashed paths git does not ignore, or None when unknown.

    ast-grep honors .gitignore natively, so the AST-based detectors already skip
    ignored files; without this the os.walk-based file-metric detectors would
    disagree with them on the same repo. Asking git is deliberate: .gitignore
    semantics (negation, nested files, precedence, core.excludesFile) are far too
    subtle to reimplement, and `ls-files` also picks up .git/info/exclude and the
    user's global ignore file for free.

    None means "no gitignore data" (not a repo, git missing, git failed) and the
    caller falls back to the fixed IGNORE_DIRS list alone. Cached because several
    detectors walk the same root in one run."""
    out = _run_git(
        root,
        # -z is deliberate: without it git quote-escapes non-ASCII paths per
        # core.quotePath, which would never match a walked path. `git -C <dir>
        # ls-files` prints paths relative to <dir>, exactly the key the walkers
        # build below.
        ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    )
    if out is None:
        return None

    visible = {p for p in out.split("\0") if p}

    # A submodule's files live in its own repo, so it gets its own question, and
    # the answers come back re-prefixed with the submodule's path. Recursing
    # through this same function beats `--recurse-submodules`, which cannot be
    # combined with `--others` (dropping untracked-but-unignored files) and which
    # ast-grep does not apply either -- leaving the two engines disagreeing about
    # submodule code, the very split this whole function exists to close.
    # Submodules nested inside submodules fall out of the recursion for free.
    for submodule in _git_submodule_dirs(root):
        nested_root = os.path.abspath(os.path.join(root, submodule))
        # An unchecked-out submodule has no repo of its own, so recursing into it
        # would just re-ask the parent and loop forever (see `_is_repo_root`).
        # Nothing is lost by skipping: the directory is empty.
        if not _is_repo_root(nested_root):
            continue
        nested = _git_visible_files(nested_root)
        if nested is None:
            continue
        visible |= {f"{submodule}/{path}" for path in nested}

    return frozenset(visible)


def reset_git_ignore_cache() -> None:
    """Forget everything git has said about every scanned root.

    A CLI run only ever sees one snapshot of the tree, so nothing in this module
    clears these caches on its own. A long-lived process that imports the harness
    as a library -- scan, write files, scan again -- has to call this in between,
    or the second scan filters against the first scan's file list."""
    _git_visible_files.cache_clear()
    _git_submodule_dirs.cache_clear()


def _is_gitignored(path: str, root: str) -> bool:
    """True if git ignores `path`, a file under `root`.

    `path` may use either separator (detect_languages walks with the native one,
    iter_source_files has already forward-slashed its paths), so the relative key
    is normalized before the lookup: git always reports forward slashes.

    Absence from the visible set is what marks a file ignored, so an unknown
    result (`None`) has to mean "not ignored" -- otherwise a missing git would
    make every detector report an empty repo."""
    visible = _git_visible_files(os.path.abspath(root))
    if visible is None:
        return False
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        # Different drive on Windows: relpath raises, treat as not ignored.
        return False
    return rel.replace("\\", "/") not in visible
