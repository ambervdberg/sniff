#!/usr/bin/env python3
"""Shared engine for token-cheap structural code search skills.

Every "find structural pattern X, rank it, print a small table" skill in this
repo reuses this package. The whole point is that all the heavy lifting (running
ast-grep, parsing its JSON, folding nested matches, ranking, formatting) happens
here, so the calling agent only ever sees a small table, never the raw AST.

This package is deliberately NOT a triggerable skill: it has no SKILL.md of its
own, so a skill loader never surfaces it. Detectors and generated skills import
it; they don't duplicate it.

One responsibility per module, imported in one direction only:

    langs      extension -> language id, and which of them a detector covers
    model      Match, RuleSpec, the findings sink
    gitignore  what git (and `[ignore] globs`) says to skip
    files      the tree walk: ignored dirs, test files, source files, line counts
    scan       running ast-grep and turning its JSON into Matches
    fold       collapsing nested matches into their outermost parent
    render     printing the table

Everything below is re-exported so callers keep importing `sniff.harness`.

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

# Re-export: tests patch `harness.shutil.which` to simulate a machine without
# ast-grep. That patches the shutil module itself, so it reaches every submodule.
import shutil  # noqa: F401

from sniff.harness.files import (
    IGNORE_DIRS,
    TEST_DIRS,
    TEST_RE,
    _in_ignored_dir,
    count_code_lines,
    detect_languages,
    is_test_file,
    iter_source_files,
)
from sniff.harness.fold import fold_nested
from sniff.harness.gitignore import (
    _extra_ignore_patterns,
    _git_submodule_dirs,
    _git_visible_files,
    _is_gitignored,
    _is_repo_root,
    _matches_extra_ignore,
    _run_git,
    _same_dir,
    reset_git_ignore_cache,
)
from sniff.harness.langs import ALL_LANGUAGES, EXT_LANG, covered_languages, not_applicable
from sniff.harness.model import NAME_PATTERNS, Match, RuleSpec
from sniff.harness.render import Column, _fmt, _sink_entry, _sink_row_file, _sink_row_name, print_table
from sniff.harness.scan import (
    _line_name,
    _require_ast_grep,
    _rule_for,
    _scan,
    _to_match,
    ast_grep_exe,
    run,
)

# When a list is installed here, print_table records every match it was given
# (not just the rendered top-N) so `sniff baseline` / `sniff diff` can gate on
# the full finding set. None (the default) means rendering-only behaviour.
# It lives on the package, not in a submodule, because callers install one by
# assigning `harness.FINDINGS_SINK = []` (see render._findings_sink).
FINDINGS_SINK: list | None = None
