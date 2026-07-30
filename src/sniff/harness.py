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

    detect_languages(root)                         -> set[str]
    run(rule_or_pattern, path, lang, include_tests) -> list[Match]
    fold_nested(matches)                           -> list[Match]
    print_table(matches, columns, sort_key, top, header)

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
import json
import os
import re
import shutil
import subprocess
import sys
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


def _in_ignored_dir(
    path: str, root: "str | None" = None, extra_ignores: "list[str] | None" = None
) -> bool:
    """True if any path segment is an ignored (vendored/build) directory, or the
    path matches an extra-ignore glob (see `_extra_ignore_patterns`).

    The vendored-dir check runs on the raw path (base-independent). The glob check
    runs on `path` relative to `root` (forward-slashed), so a consumer's
    `[ignore] globs` matches the same scan-root-relative path that sniff-patterns'
    format.py matches against; without this, an absolute or scan-arg-prefixed
    file path would never match a pattern like `generated/**`. Extends the fixed
    vendored-dir list rather than replacing it, so both apply together."""
    if any(seg in IGNORE_DIRS for seg in re.split(r"[\\/]", path)):
        return True
    patterns = _extra_ignore_patterns(extra_ignores)
    if not patterns:
        return False
    rel = path
    if root is not None:
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            # Different drive on Windows: relpath raises, keep the original path.
            rel = path
    norm = rel.replace("\\", "/")
    return any(fnmatch.fnmatch(norm, pat) for pat in patterns)


def detect_languages(root: str) -> set[str]:
    """Walk the tree once and collect which supported languages are present."""
    found: set[str] = set()

    for _dirpath, dirnames, filenames in os.walk(root):
        # Prune ignored directories in place so os.walk never descends into them.
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]

        for name in filenames:
            lang = EXT_LANG.get(os.path.splitext(name)[1].lower())
            if lang:
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
    (scan-root-relative), mirroring `run()`'s handling for AST-based detectors."""
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


def _scan(root: str, lang: str, rule_yaml: str) -> list[dict]:
    """Run one inline rule over the tree and return ast-grep's raw match dicts."""
    try:
        proc = subprocess.run(
            [ast_grep_exe(), "scan", "--inline-rules", rule_yaml, "--json=compact", root],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        _require_ast_grep()
        return []

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
        langs = detect_languages(path)
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
