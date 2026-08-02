#!/usr/bin/env python3
"""Node-metric engine: score each function/method, rank by the score.

Where `harness.py` ranks nodes by physical size (lines), this layer computes a
*derived* numeric metric per node and ranks by that. The first metric is
**nesting depth**: how deeply control-flow blocks stack
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

from sniff import harness as h

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

# Decision-point node kinds per language for cyclomatic complexity.
# Each is one branch in the control-flow graph: a branch, loop, case, or catch.
# Boolean operators (&&/||/and/or) and ternaries add branches too, but in some
# grammars they share a node kind with other operators, so those are matched by
# pattern instead (DECISION_PATTERNS) rather than by kind.
DECISION_KINDS = {
    "python": ["if_statement", "elif_clause", "for_statement", "while_statement",
               "except_clause", "case_clause", "conditional_expression", "boolean_operator"],
    "typescript": ["if_statement", "for_statement", "for_in_statement", "while_statement",
                   "do_statement", "switch_case", "catch_clause", "ternary_expression"],
    "tsx": ["if_statement", "for_statement", "for_in_statement", "while_statement",
            "do_statement", "switch_case", "catch_clause", "ternary_expression"],
    "javascript": ["if_statement", "for_statement", "for_in_statement", "while_statement",
                   "do_statement", "switch_case", "catch_clause", "ternary_expression"],
    "java": ["if_statement", "for_statement", "enhanced_for_statement", "while_statement",
             "do_statement", "switch_label", "catch_clause", "ternary_expression"],
    "csharp": ["if_statement", "for_statement", "for_each_statement", "while_statement",
               "do_statement", "switch_section", "catch_clause", "conditional_expression"],
    "go": ["if_statement", "for_statement", "expression_case", "type_case",
           "communication_case"],
    "ruby": ["if", "unless", "while", "until", "for", "when", "rescue"],
    "c": ["if_statement", "for_statement", "while_statement", "do_statement",
          "case_statement", "conditional_expression"],
    "cpp": ["if_statement", "for_statement", "while_statement", "do_statement",
            "case_statement", "catch_clause", "conditional_expression"],
}

# Boolean operators that each add a decision point but are not reliably their own
# node kind. Matched by ast-grep pattern instead. `and`/`or` in Python already
# have a kind (boolean_operator) so Python is absent here.
DECISION_PATTERNS = {
    "typescript": ["$A && $B", "$A || $B"],
    "tsx": ["$A && $B", "$A || $B"],
    "javascript": ["$A && $B", "$A || $B"],
    "java": ["$A && $B", "$A || $B"],
    "csharp": ["$A && $B", "$A || $B"],
    "go": ["$A && $B", "$A || $B"],
    "c": ["$A && $B", "$A || $B"],
    "cpp": ["$A && $B", "$A || $B"],
}

# Languages this metric can score.
CYCLOMATIC_LANGS = sorted(DECISION_KINDS)

# The node kind wrapping a function's formal parameter list, per language. There
# is exactly one such node per function signature; counting its top-level entries
# gives the parameter count.
PARAM_LIST_KINDS = {
    "python": ["parameters"],
    "typescript": ["formal_parameters"],
    "tsx": ["formal_parameters"],
    "javascript": ["formal_parameters"],
    "java": ["formal_parameters"],
    "csharp": ["parameter_list"],
    "go": ["parameter_list"],
    "rust": ["parameters"],
    "c": ["parameter_list"],
    "cpp": ["parameter_list"],
    "ruby": ["method_parameters"],
    "php": ["formal_parameters"],
    "kotlin": ["function_value_parameters"],
}

PARAM_LANGS = sorted(PARAM_LIST_KINDS)

# Bracket pairs whose interior commas must NOT be counted as parameter separators
# (generics, default lists/objects/tuples). Only top-level commas split params.
_OPEN = {"(": ")", "[": "]", "{": "}", "<": ">"}
_CLOSE = set(_OPEN.values())


def count_params(list_text: str) -> int:
    """Count parameters in a formal-parameter-list node's source text.

    Strips the outer delimiters, then counts commas at bracket depth zero so a
    nested generic (`Map<string, number>`) or default (`x = {a, b}`) counts as one
    parameter, not several. An empty list is zero."""
    text = list_text.strip()

    # Drop a single pair of outer delimiters: ( ), [ ] used by Go/Rust receivers, etc.
    if text and text[0] in _OPEN and text[-1] == _OPEN[text[0]]:
        text = text[1:-1]

    if not text.strip():
        return 0

    depth = 0
    params = 1
    for ch in text:
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            params += 1

    return params


# Angular components live in TypeScript; the decorator node carries the inline
# template, so this metric only applies to these languages.
TEMPLATE_LANGS = ["typescript", "tsx"]

# Pull the inline template literal and the selector out of an @Component decorator.
# `template:` followed by a backtick string; selector by its quoted string. The
# template regex is non-greedy and stops at the first backtick, so it does not
# span past the literal (nested backticks in Angular templates are vanishingly rare).
import re as _re

_TEMPLATE_RE = _re.compile(r"template\s*:\s*`([^`]*)`", _re.DOTALL)
_SELECTOR_RE = _re.compile(r"selector\s*:\s*['\"]([^'\"]+)['\"]")


def count_template_lines(decorator_text: str) -> int:
    """Line count of an @Component's inline template, or 0 if there is none.

    Reads the `template: \\`...\\`` literal from the decorator's source text. An
    external `templateUrl` (no inline template) scores 0, as does an empty
    template."""
    m = _TEMPLATE_RE.search(decorator_text)
    if not m:
        return 0

    body = m.group(1).strip("\n")
    if not body.strip():
        return 0

    return body.count("\n") + 1


def inline_template_lines(
    path: str = ".",
    langs: "list[str] | None" = None,
    include_tests: bool = False,
    extra_ignores: "list[str] | None" = None,
) -> list[h.Match]:
    """Score each Angular @Component by its inline-template line count.

    Large inline templates belong in their own `.html` file; this ranks the
    worst offenders. Returns decorator Matches with `metrics['template_lines']`
    set and `name` taken from the component selector. Components with no inline
    template (e.g. `templateUrl`) are dropped."""
    if langs is None:
        langs = sorted(h.detect_languages(path, extra_ignores))

    langs = [l for l in langs if l in TEMPLATE_LANGS]
    if not langs:
        return []

    decorators = h.run(
        {l: ["decorator"] for l in langs}, path, lang=langs,
        include_tests=include_tests, with_name=False, extra_ignores=extra_ignores,
    )

    scored: list[h.Match] = []
    for dec in decorators:
        if "@Component" not in dec.text:
            continue

        lines = count_template_lines(dec.text)
        if lines == 0:
            continue  # external or no template: not an inline-template smell

        sel = _SELECTOR_RE.search(dec.text)
        dec.name = sel.group(1) if sel else "(component)"
        dec.metrics["template_lines"] = lines
        scored.append(dec)

    return scored


def params(
    path: str = ".",
    langs: "list[str] | None" = None,
    include_tests: bool = False,
    extra_ignores: "list[str] | None" = None,
) -> list[h.Match]:
    """Score every function under `path` by its parameter count.

    Returns the function Matches with `metrics['params']` set. A function's own
    parameter list is the earliest-starting list node inside it (the signature,
    which precedes any nested function); nested functions' lists are ignored for
    the enclosing function. Languages without a PARAM_LIST_KINDS entry are
    skipped."""
    if langs is None:
        langs = sorted(h.detect_languages(path, extra_ignores))

    langs = [l for l in langs if l in PARAM_LIST_KINDS]
    if not langs:
        return []

    functions = h.fold_nested(
        h.run(FUNCTION_KINDS, path, lang=langs, include_tests=include_tests, extra_ignores=extra_ignores)
    )
    lists = h.run(
        PARAM_LIST_KINDS, path, lang=langs, include_tests=include_tests, with_name=False,
        extra_ignores=extra_ignores,
    )

    by_file: dict[str, list[h.Match]] = {}
    for node in lists:
        by_file.setdefault(node.file, []).append(node)

    for func in functions:
        # The signature's list starts first among the lists inside this function.
        owned = [l for l in by_file.get(func.file, []) if _contains(func, l)]
        own_list = min(owned, key=lambda l: l.byte_start, default=None)
        func.metrics["params"] = count_params(own_list.text) if own_list else 0

    return functions


def _decision_rule(lang: str) -> "str | None":
    """Inline ast-grep rule matching every decision point in `lang`.

    Combines the decision node kinds with the boolean-operator patterns into one
    `any:` rule, so a single scan returns all branches that bump complexity."""
    kinds = DECISION_KINDS.get(lang)
    if not kinds:
        return None

    parts = [f"    - kind: {k}" for k in kinds]
    for pat in DECISION_PATTERNS.get(lang, []):
        parts.append(f"    - pattern: {pat}")

    return "id: h\nlanguage: {}\nrule:\n  any:\n{}".format(lang, "\n".join(parts))


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


def _cognitive_within(func: h.Match, nodes: list[h.Match]) -> int:
    """Cognitive-complexity score for one function from its nesting nodes.

    Each control structure costs 1, plus a nesting penalty equal to how many
    other control structures enclose it (the nesting increment). So a
    branch three levels deep costs 1 + 3 = 4, while two sibling branches cost
    1 + 1 = 2. The sum over all the function's control structures is its score."""
    inside = [n for n in nodes if _contains(func, n)]

    total = 0
    for node in inside:
        enclosing = sum(1 for other in inside if _contains(other, node))
        total += 1 + enclosing

    return total


def _functions_and_nesting(
    path: str, langs: "list[str] | None", include_tests: bool,
    extra_ignores: "list[str] | None" = None,
) -> "tuple[list[h.Match], dict[str, list[h.Match]]]":
    """Shared scan for the nesting-based metrics (depth, cognitive).

    Returns the folded functions and the file -> nesting-nodes index. Returns
    ([], {}) when no scorable language is present."""
    if langs is None:
        langs = sorted(h.detect_languages(path, extra_ignores))

    langs = [l for l in langs if l in NESTING_KINDS]
    if not langs:
        return [], {}

    functions = h.fold_nested(
        h.run(FUNCTION_KINDS, path, lang=langs, include_tests=include_tests, extra_ignores=extra_ignores)
    )
    nodes = h.run(
        NESTING_KINDS, path, lang=langs, include_tests=include_tests, with_name=False,
        extra_ignores=extra_ignores,
    )

    # Bucket nesting nodes by file so each function only scans its own file's nodes.
    by_file: dict[str, list[h.Match]] = {}
    for node in nodes:
        by_file.setdefault(node.file, []).append(node)

    return functions, by_file


def nesting_depth(
    path: str = ".",
    langs: "list[str] | None" = None,
    include_tests: bool = False,
    extra_ignores: "list[str] | None" = None,
) -> list[h.Match]:
    """Score every function under `path` by its maximum control-flow nesting depth.

    Returns the function Matches with `metrics['depth']` set. Unsupported
    languages (no NESTING_KINDS entry) are simply skipped."""
    functions, by_file = _functions_and_nesting(path, langs, include_tests, extra_ignores)

    for func in functions:
        func.metrics["depth"] = _depth_within(func, by_file.get(func.file, []))

    return functions


def cognitive(
    path: str = ".",
    langs: "list[str] | None" = None,
    include_tests: bool = False,
    extra_ignores: "list[str] | None" = None,
) -> list[h.Match]:
    """Score every function under `path` by cognitive complexity.

    Each control structure costs 1 plus a nesting penalty for how deeply it sits
    (the nesting increment), so deeply nested branching scores far above
    the same number of flat branches. Returns the function Matches with
    `metrics['cognitive']` set. Unsupported languages are skipped.

    Note: boolean-operator sequences are not yet
    counted here; use cyclomatic complexity for boolean-heavy code."""
    functions, by_file = _functions_and_nesting(path, langs, include_tests, extra_ignores)

    for func in functions:
        func.metrics["cognitive"] = _cognitive_within(func, by_file.get(func.file, []))

    return functions


def cyclomatic(
    path: str = ".",
    langs: "list[str] | None" = None,
    include_tests: bool = False,
    extra_ignores: "list[str] | None" = None,
) -> list[h.Match]:
    """Score every function under `path` by cyclomatic complexity.

    Complexity = 1 + the number of decision points (branches, loops, cases,
    catches, boolean operators, ternaries) inside the function. Returns the
    function Matches with `metrics['cyclomatic']` set. Languages without a
    DECISION_KINDS entry are skipped."""
    if langs is None:
        langs = sorted(h.detect_languages(path, extra_ignores))

    langs = [l for l in langs if l in DECISION_KINDS]
    if not langs:
        return []

    functions = h.fold_nested(
        h.run(FUNCTION_KINDS, path, lang=langs, include_tests=include_tests, extra_ignores=extra_ignores)
    )
    # _decision_rule is a per-language callable, the engine's escape-hatch shape.
    decisions = h.run(
        _decision_rule, path, lang=langs, include_tests=include_tests, with_name=False,
        extra_ignores=extra_ignores,
    )

    by_file: dict[str, list[h.Match]] = {}
    for node in decisions:
        by_file.setdefault(node.file, []).append(node)

    for func in functions:
        contained = sum(1 for d in by_file.get(func.file, []) if _contains(func, d))
        func.metrics["cyclomatic"] = 1 + contained

    return functions
