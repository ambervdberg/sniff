#!/usr/bin/env python3
"""Shared engine for token-cheap structural code search skills.

Every "find structural pattern X, rank it, print a small table" skill in this
repo reuses this module. The whole point is that all the heavy lifting (running
ast-grep, parsing its JSON, folding nested matches, ranking, formatting) happens
here, so the calling agent only ever sees a small table, never the raw AST.

This file is deliberately NOT a triggerable skill: it is a module inside the
`sniff` package with no SKILL.md of its own, so a skill loader never surfaces it.
Detectors and generated skills import it; they don't duplicate it.

Stable public API (kept small so generated scripts stay ~20 lines):

    detect_languages(root, extra_ignores)          -> set[str]
    covered_languages(present, supported)          -> list[str]
    not_applicable(present, supported)             -> str
    run(rule_or_pattern, path, lang, include_tests) -> list[Match]
    fold_nested(matches)                           -> list[Match]
    print_table(matches, columns, sort_key, top, header)
    reset_git_ignore_cache()                       -> None

`rule_or_pattern` accepts three shapes so it fits both simple and custom skills:

    - dict[str, list[str]]   maps language id -> tree-sitter node kinds. A match
                             is any node of those kinds. (What largest-methods uses.)
    - str                    an ast-grep *pattern*, applied to every detected language.
    - callable(lang) -> str  returns a full inline ast-grep rule YAML for a given
                             language, or None to skip that language. The escape
                             hatch for rules that differ per language.
"""

from __future__ import annotations

import fnmatch
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence, Union

# Map source extensions to ast-grep language ids.
EXT_LANG = {
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".py": "python",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
}

# Every language the file walk recognizes. Detectors that read files rather than
# parse them (line counts, string literals) support all of them, so they declare
# their LANGUAGES as this list instead of repeating it.
ALL_LANGUAGES = sorted(set(EXT_LANG.values()))

# Directories that never contain hand-written source worth ranking.
IGNORE_DIRS = {
    "node_modules", "dist", "build", "out", "coverage", ".git", ".nx",
    ".angular", ".astro", ".next", ".svelte-kit", ".nuxt", ".turbo",
    "vendor", "target", "__pycache__", ".venv", "venv", ".claude",
}

# Files that look like tests, excluded unless the caller opts in.
TEST_RE = re.compile(r"\.(spec|test)\.[a-z]+$", re.IGNORECASE)

# Best-effort name extraction, tried in order against a definition's first line.
# Reading the single line from disk costs the calling agent nothing.
NAME_PATTERNS = [
    re.compile(r"\b(?:def|fn|func|function|fun)\s+([A-Za-z0-9_$]+)"),
    re.compile(r"\b(?:class|interface|enum|struct|trait|type|namespace|module)\s+([A-Za-z0-9_$]+)"),
    re.compile(r"\b(?:get|set)\s+([A-Za-z0-9_$]+)\s*\("),
    re.compile(r"([A-Za-z0-9_$#]+)\s*[:=]\s*(?:async\s+)?(?:function\b|\(?[^)=]*\)?\s*=>)"),
    re.compile(r"\b([A-Za-z0-9_$#~]+)\s*\("),
]

_NAME_STOPWORDS = {"function", "async", "return", "if", "for", "while", "switch"}

# Type of the `rule_or_pattern` argument accepted by run().
RuleSpec = Union[Mapping[str, Sequence[str]], str, Callable[[str], "str | None"]]


@dataclass
class Match:
    """One structural hit. Line fields are 0-based (as ast-grep reports them);
    use `.line` for a 1-based number suitable for display and editor jumps."""

    file: str                       # normalized to forward slashes
    start_line: int                 # 0-based
    end_line: int                   # 0-based
    byte_start: int
    byte_end: int
    name: str = "(anon)"
    text: str = ""                  # the matched node's source (as ast-grep reports it)
    metrics: dict = field(default_factory=dict)  # skill-specific extras (e.g. params, depth)

    @property
    def lines(self) -> int:
        """Physical line span of the match (inclusive)."""
        return self.end_line - self.start_line + 1

    @property
    def line(self) -> int:
        """1-based start line, for display and `file:line` jump targets."""
        return self.start_line + 1

    @property
    def location(self) -> str:
        """Authoritative `file:line` pointer."""
        return f"{self.file}:{self.line}"


def ast_grep_exe() -> str:
    """Absolute path to ast-grep, resolving Windows .cmd/.exe shims; bare name if not found.

    Windows CreateProcess does not resolve the `.cmd` shim npm installs for a bare
    "ast-grep" argv[0], so passing the bare name to subprocess raises WinError 2.
    shutil.which does apply PATHEXT, so the resolved path works on every platform."""
    return shutil.which("ast-grep") or "ast-grep"


def _require_ast_grep() -> None:
    """Fail fast with a clear message if the ast-grep binary is missing."""
    if not shutil.which("ast-grep"):
        sys.exit("error: ast-grep is not installed or not on PATH. See https://ast-grep.github.io")


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
    return os.path.normcase(os.path.abspath(out.strip())) == os.path.normcase(os.path.abspath(path))


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
    if not patterns:
        return False
    return any(fnmatch.fnmatch(norm, pat) for pat in patterns)


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


def covered_languages(present: "Sequence[str]", supported: "Sequence[str]") -> "list[str]":
    """The languages a detector can actually match out of the ones in the repo.

    Every detector declares a LANGUAGES list: the languages it has rules for.
    Narrowing the detected languages against that list before scanning is what
    keeps a header from claiming a detector examined Java when it has no Java
    rules at all."""
    return sorted(lang for lang in set(present) if lang in set(supported))


def not_applicable(present: "Sequence[str]", supported: "Sequence[str]") -> str:
    """The one line a detector prints when it covers none of the repo's languages.

    Says what the detector does cover, so the reader can tell "nothing to report"
    apart from "this tool cannot see your code"."""
    found = ", ".join(sorted(set(present))) or "none"
    covers = ", ".join(sorted(set(supported))) or "no languages"
    return f"Not applicable: this detector covers {covers}; the files here are {found}."


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
            if not include_tests and TEST_RE.search(path):
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


def _kinds_rule(lang: str, kinds: Sequence[str]) -> str:
    """Build an inline ast-grep rule matching any of the given node kinds."""
    any_block = "\n".join(f"    - kind: {k}" for k in kinds)
    return f"id: h\nlanguage: {lang}\nrule:\n  any:\n{any_block}"


def _pattern_rule(lang: str, pattern: str) -> str:
    """Build an inline ast-grep rule from a single pattern string."""
    return f"id: h\nlanguage: {lang}\nrule:\n  pattern: {json.dumps(pattern)}"


def _rule_for(spec: RuleSpec, lang: str) -> "str | None":
    """Resolve `rule_or_pattern` into a concrete inline rule YAML for one language.

    Returns None when the spec does not apply to this language (so the caller
    skips scanning it)."""
    if callable(spec):
        return spec(lang)

    if isinstance(spec, str):
        return _pattern_rule(lang, spec)

    # Mapping of language -> node kinds.
    kinds = spec.get(lang)
    if not kinds:
        return None
    return _kinds_rule(lang, list(kinds))


def _write_rule_file(rule_yaml: str) -> str:
    """Write a rule YAML to a temp file and return its forward-slashed path.

    The caller is responsible for deleting it (see `_scan`)."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8")
    try:
        tmp.write(rule_yaml)
    finally:
        tmp.close()
    return tmp.name.replace("\\", "/")


def _scan(root: str, lang: str, rule_yaml: str) -> list[dict]:
    """Run one rule over the tree and return ast-grep's raw match dicts.

    The rule goes to a temp file rather than `--inline-rules`: a rule YAML is
    multi-line, and when argv[0] is a Windows `.cmd` shim (how npm installs
    ast-grep, which is what CI uses) the command line is re-parsed by cmd.exe,
    which mangles embedded newlines and quotes. ast-grep then exits nonzero with
    "Cannot parse rule INLINE_RULES" and every detector silently reports nothing.
    A file path is a single plain token, so it survives any shim."""
    rule_file = _write_rule_file(rule_yaml)
    try:
        proc = subprocess.run(
            [ast_grep_exe(), "scan", "--rule", rule_file, "--json=compact", root],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        _require_ast_grep()
        return []
    finally:
        try:
            os.unlink(rule_file)
        except OSError:
            pass

    # Never crash on a failed scan (an empty result stays the fallback), but do not
    # hide it either: a silent miss looks exactly like "this repo is clean".
    if proc.returncode != 0:
        first = next((ln for ln in proc.stderr.splitlines() if ln.strip()), "")
        print(f"warning: ast-grep scan failed for {lang} (exit {proc.returncode}): {first}",
              file=sys.stderr)

    if not proc.stdout.strip():
        return []

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []


def _line_name(path: str, start_line: int) -> str:
    """Best-effort name by reading only the definition's first line from disk."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i == start_line:
                    text = line.strip()
                    break
            else:
                return "(anon)"
    except OSError:
        return "(anon)"

    for pat in NAME_PATTERNS:
        m = pat.search(text)
        if m and m.group(1) not in _NAME_STOPWORDS:
            return m.group(1)

    return "(anon)"


def _to_match(raw: dict, with_name: bool) -> Match:
    """Convert one ast-grep JSON match into a Match, resolving its name lazily."""
    rng = raw["range"]
    file = raw["file"]
    start_line = rng["start"]["line"]

    return Match(
        file=file.replace("\\", "/"),
        start_line=start_line,
        end_line=rng["end"]["line"],
        byte_start=rng["byteOffset"]["start"],
        byte_end=rng["byteOffset"]["end"],
        name=_line_name(file, start_line) if with_name else "(anon)",
        text=raw.get("text", ""),
    )


def run(
    rule_or_pattern: RuleSpec,
    path: str = ".",
    lang: "str | Sequence[str] | None" = None,
    include_tests: bool = False,
    with_name: bool = True,
    extra_ignores: "list[str] | None" = None,
) -> list[Match]:
    """Scan `path` for a structural pattern and return the matches.

    Languages are auto-detected from file extensions unless `lang` is given
    (a single id or a sequence). Test files are excluded unless `include_tests`.
    `extra_ignores`, when given, is the caller's parsed `--extra-ignore` globs and
    wins over SNIFF_EXTRA_IGNORE (see `_extra_ignore_patterns`). See module
    docstring for the three accepted shapes of `rule_or_pattern`."""
    _require_ast_grep()

    if lang is None:
        langs = detect_languages(path, extra_ignores)
    elif isinstance(lang, str):
        langs = {lang}
    else:
        langs = set(lang)

    if not langs:
        return []

    raw: list[dict] = []
    for one in sorted(langs):
        rule_yaml = _rule_for(rule_or_pattern, one)
        if rule_yaml is None:
            continue
        raw.extend(_scan(path, one, rule_yaml))

    # Drop vendored/build dirs explicitly: ast-grep only skips them when they are
    # gitignored, which is not guaranteed (e.g. a tree with no .gitignore).
    raw = [m for m in raw if not _in_ignored_dir(m["file"], path, extra_ignores)]

    if not include_tests:
        raw = [m for m in raw if not TEST_RE.search(m["file"])]

    return [_to_match(m, with_name) for m in raw]


def fold_nested(matches: list[Match]) -> list[Match]:
    """Keep only the outermost match per overlapping region in each file.

    A 200-line function that contains a 150-line closure should report once, as
    200, not twice. Sorting by start byte ascending then end byte descending puts
    each outer match before the inner ones it contains, so we drop anything that
    starts before the current outer match ends."""
    by_file: dict[str, list[Match]] = {}
    for m in matches:
        by_file.setdefault(m.file, []).append(m)

    kept: list[Match] = []
    for items in by_file.values():
        items.sort(key=lambda m: (m.byte_start, -m.byte_end))

        open_end = -1
        for m in items:
            if m.byte_start < open_end:
                continue  # nested inside an already-kept outer match
            kept.append(m)
            open_end = m.byte_end

    return kept


# A column is a (header, accessor) pair. The accessor maps a Match to a cell value.
Column = tuple[str, Callable[[Match], object]]


def print_table(
    matches: Sequence[Match],
    columns: Sequence[Column],
    sort_key: "Callable[[Match], object] | None" = None,
    top: "int | None" = None,
    header: "str | None" = None,
) -> None:
    """Print matches as a compact, aligned table and nothing else.

    This is the only thing the calling agent should ever see. Never print raw
    matches or AST JSON alongside it. Numeric columns are right-aligned; the
    first column is sized to its content, the rest to their widest cell."""
    rows = list(matches)
    if sort_key is not None:
        rows.sort(key=sort_key, reverse=True)
    if top is not None:
        rows = rows[:top]

    if not rows:
        print("No matches.")
        return

    headers = [c[0] for c in columns]
    cells = [[_fmt(c[1](m)) for c in columns] for m in rows]

    if header:
        print(header + "\n")

    # Markdown table: renders as a real table when the agent relays it in a reply
    # (space-aligned text collapses there). Plain `---` separators only, no `:`
    # alignment markers, which some strict renderers reject and fall back to raw.
    def _row(values: Sequence[str]) -> str:
        return "| " + " | ".join(v.replace("|", "\\|") for v in values) + " |"

    print(_row(headers))
    print(_row(["---"] * len(headers)))
    for row in cells:
        print(_row(row))


def _fmt(value: object) -> str:
    return str(value)


def _is_num(value: str) -> bool:
    return value.lstrip("-").isdigit()


def _align(value: str, width: int, right: bool) -> str:
    return value.rjust(width) if right else value.ljust(width)
