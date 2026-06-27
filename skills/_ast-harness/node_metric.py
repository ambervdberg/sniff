#!/usr/bin/env python3
"""Node-metric engine: score each function/method, rank by the score.

Where `harness.py` ranks nodes by physical size (lines), this layer computes a
*derived* numeric metric per node and ranks by that. The first metric is
**nesting depth** (SonarSource S134): how deeply control-flow blocks stack
inside a function. Deeply nested code is the classic refactor smell.

It stays true to the AST without hand-walking a parse tree: it asks ast-grep for
two sets of nodes, the functions and the nesting constructs, then derives each
function's depth purely from byte-range *containment*. A nesting node's level is
1 + the number of nesting nodes (in the same function) that enclose it; the
function's depth is the deepest level it contains. That is genuine structural
nesting, computed from the tree's node ranges, not from regex over text.

Other metrics (cyclomatic, cognitive, params, inline-template LOC) are tracked
as their own beads and will plug into the same two-pass shape. Keep this module
the single home for "score a node and rank it" so generated skills stay tiny.

Public API:
    FUNCTION_KINDS                 language id -> function/method node kinds
    NESTING_KINDS                  language id -> control-flow node kinds
    nesting_depth(path, langs, include_tests) -> list[harness.Match]
        (each Match has metrics['depth'] populated)
"""

from __future__ import annotations

import os
import sys

# Import the shared engine from the sibling file in this directory.
sys.path.insert(0, os.path.dirname(__file__))
import harness as h  # noqa: E402

# What counts as a function/method per language. Mirrors largest-methods'
# LANG_KINDS; kept here so the node-metric skills do not depend on that skill.
FUNCTION_KINDS = {
    "typescript": ["method_definition", "function_declaration", "arrow_function", "function_expression"],
    "tsx": ["method_definition", "function_declaration", "arrow_function", "function_expression"],
    "javascript": ["method_definition", "function_declaration", "arrow_function", "function_expression"],
    "python": ["function_definition"],
    "rust": ["function_item"],
    "go": ["function_declaration", "method_declaration", "func_literal"],
    "java": ["method_declaration", "constructor_declaration"],
    "ruby": ["method", "singleton_method"],
    "csharp": ["method_declaration", "constructor_declaration", "local_function_statement"],
    "php": ["method_declaration", "function_definition"],
    "kotlin": ["function_declaration"],
    "swift": ["function_declaration"],
    "scala": ["function_definition"],
    "c": ["function_definition"],
    "cpp": ["function_definition"],
}

# Control-flow constructs that add a level of nesting per language. Loops, branches,
# switches and try/catch all count; sequential blocks at the same level do not.
NESTING_KINDS = {
    "typescript": ["if_statement", "for_statement", "for_in_statement", "while_statement",
                   "do_statement", "switch_statement", "try_statement", "catch_clause"],
    "tsx": ["if_statement", "for_statement", "for_in_statement", "while_statement",
            "do_statement", "switch_statement", "try_statement", "catch_clause"],
    "javascript": ["if_statement", "for_statement", "for_in_statement", "while_statement",
                   "do_statement", "switch_statement", "try_statement", "catch_clause"],
    "python": ["if_statement", "for_statement", "while_statement", "with_statement",
               "try_statement", "match_statement"],
    "rust": ["if_expression", "for_expression", "while_expression", "loop_expression",
             "match_expression"],
    "go": ["if_statement", "for_statement", "type_switch_statement",
           "expression_switch_statement", "select_statement"],
    "java": ["if_statement", "for_statement", "enhanced_for_statement", "while_statement",
             "do_statement", "switch_expression", "try_statement", "catch_clause"],
    "csharp": ["if_statement", "for_statement", "for_each_statement", "while_statement",
               "do_statement", "switch_statement", "try_statement", "catch_clause"],
    "ruby": ["if", "unless", "while", "until", "for", "case", "begin"],
    "c": ["if_statement", "for_statement", "while_statement", "do_statement",
          "switch_statement"],
    "cpp": ["if_statement", "for_statement", "while_statement", "do_statement",
            "switch_statement", "try_statement", "catch_clause"],
    "php": ["if_statement", "for_statement", "foreach_statement", "while_statement",
            "do_statement", "switch_statement", "try_statement"],
    "kotlin": ["if_expression", "for_statement", "while_statement", "do_while_statement",
               "when_expression", "try_expression"],
}

# Languages this metric can actually score (have a nesting-kinds entry).
SUPPORTED_LANGS = sorted(NESTING_KINDS)


def _contains(outer: h.Match, inner: h.Match) -> bool:
    """True when `outer`'s byte range strictly encloses `inner`'s.

    Strict: identical ranges (a node compared with itself, or two coincident
    nodes) do not count as containment, so a node never deepens its own level."""
    if outer.file != inner.file:
        return False

    same = outer.byte_start == inner.byte_start and outer.byte_end == inner.byte_end
    return (not same
            and outer.byte_start <= inner.byte_start
            and inner.byte_end <= outer.byte_end)


def _depth_within(func: h.Match, nodes: list[h.Match]) -> int:
    """Deepest nesting level among `nodes` that live inside `func`.

    A node's level is 1 + how many of the function's other nesting nodes enclose
    it. The function's depth is the maximum such level (0 if it nests nothing)."""
    inside = [n for n in nodes if _contains(func, n)]

    best = 0
    for node in inside:
        level = 1 + sum(1 for other in inside if _contains(other, node))
        best = max(best, level)

    return best


def nesting_depth(
    path: str = ".",
    langs: "list[str] | None" = None,
    include_tests: bool = False,
) -> list[h.Match]:
    """Score every function under `path` by its maximum control-flow nesting depth.

    Returns the function Matches with `metrics['depth']` set. Unsupported
    languages (no NESTING_KINDS entry) are simply skipped."""
    if langs is None:
        langs = sorted(h.detect_languages(path))

    # Only score languages we have nesting kinds for.
    langs = [l for l in langs if l in NESTING_KINDS]
    if not langs:
        return []

    functions = h.fold_nested(
        h.run(FUNCTION_KINDS, path, lang=langs, include_tests=include_tests)
    )
    nodes = h.run(
        NESTING_KINDS, path, lang=langs, include_tests=include_tests, with_name=False
    )

    # Bucket nesting nodes by file so each function only scans its own file's nodes.
    by_file: dict[str, list[h.Match]] = {}
    for node in nodes:
        by_file.setdefault(node.file, []).append(node)

    for func in functions:
        func.metrics["depth"] = _depth_within(func, by_file.get(func.file, []))

    return functions
