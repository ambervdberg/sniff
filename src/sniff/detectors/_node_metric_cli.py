#!/usr/bin/env python3
"""Shared CLI scaffolding for the node-metric detectors.

Six detectors share the same three-part shape: build an argparse parser with
the same core flags, detect and gate the repo's languages against what the
detector covers, then score/rank/print. Four of them (cognitive complexity,
cyclomatic complexity, deepest nesting, most parameters) additionally share
the exact "score, drop anything below --min, print a table" tail, because
they all call a `node_metric` scorer with the same signature. The other two
(largest methods, largest classes) share a simpler "scan, fold nested matches,
print a LINES table" tail instead, with no threshold flag at all.

This module is that shared shape, kept in one place so each detector file only
has to state what makes it different: its NAME/TITLE/LANGUAGES, its scoring
call, its table columns, and its own wording. Like `harness.py`, it is a plain
importable module, not a triggerable skill: no SKILL.md names it, so a skill
loader never surfaces it on its own.

Public API:
    new_parser(description)                    -> parser with path/--top/--lang
    finish_parser(parser)                       -> adds --include-tests/--extra-ignore
    detect_and_gate(args, languages)            -> langs to scan, or None (caller returns 0)
    run_metric_main(...)                        -> shared tail for the four node_metric detectors
    run_size_main(...)                          -> shared tail for largest-methods/largest-classes
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from sniff import harness as h


def new_parser(description: str) -> argparse.ArgumentParser:
    """Start a detector's parser with the three flags every one of them takes
    first: the scan path, how many rows to show, and a language override.

    A detector that needs its own flag (e.g. --min) adds it right after calling
    this, so it lands between --lang and the trailing flags `finish_parser`
    appends, matching every detector's original argument order."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("path", nargs="?", default=".", help="directory to scan (default: .)")
    parser.add_argument("--top", type=int, default=10, help="how many to show (default: 10)")
    parser.add_argument("--lang", action="append", help="force a language (repeatable); skips auto-detect")
    return parser


def finish_parser(parser: argparse.ArgumentParser) -> None:
    """Append the two flags every detector takes last, after its own flags."""
    parser.add_argument("--include-tests", action="store_true", help="include *.spec.* / *.test.* files")
    parser.add_argument("--extra-ignore", action="append", default=[],
                        help="glob to exclude, relative to PATH (repeatable)")


def detect_and_gate(args: argparse.Namespace, languages: "list[str]") -> "list[str] | None":
    """Work out which languages to scan, printing the exit messages that apply.

    Auto-detects the repo's languages (or trusts an explicit --lang), exits
    loudly if nothing was found at all, and prints the "not applicable" line
    if what was found falls entirely outside `languages` (the calling
    detector's coverage). Returns the sorted languages to scan, or None when
    the caller should print nothing further and return 0."""
    present = sorted(set(args.lang)) if args.lang else sorted(h.detect_languages(args.path, args.extra_ignore))
    if not present:
        sys.exit(f"No supported source files found under {args.path!r}.")

    langs = h.covered_languages(present, languages)
    if not langs:
        print(h.not_applicable(present, languages))
        return None
    return langs


# A node_metric scorer: cognitive/cyclomatic/nesting_depth/params all share this
# exact signature, which is what lets run_metric_main call any of them the same way.
Scorer = Callable[..., "list[h.Match]"]


def _tests_word(include_tests: bool) -> str:
    """The one word every detector's header uses to say whether tests counted."""
    return "included" if include_tests else "excluded"


def run_metric_main(
    args: argparse.Namespace,
    langs: "list[str]",
    scorer: Scorer,
    metric_key: str,
    minimum: int,
    column: str,
    header: "Callable[[int, int, str, str], str]",
    empty_message: "Callable[[str], str]",
) -> int:
    """Shared tail of a node_metric detector's main(): score, threshold, print.

    `scorer` is one of node_metric's per-metric functions; it must return
    Matches with `metric_key` set in `.metrics`. `header` and `empty_message`
    are the calling detector's own wording: `header` is called with (shown,
    total, langs_str, tests_str) once the threshold filter is known,
    `empty_message` with just langs_str. Keeping those as callables (rather
    than plain strings built here) is what lets four detectors with four
    different phrasings share this one function."""
    langs_str = ", ".join(langs)

    scored = scorer(args.path, langs=langs, include_tests=args.include_tests,
                     extra_ignores=args.extra_ignore)
    scored = [m for m in scored if m.metrics.get(metric_key, 0) >= minimum]

    if not scored:
        print(empty_message(langs_str))
        return 0

    h.print_table(
        scored,
        columns=[
            (column, lambda m: m.metrics[metric_key]),
            ("NAME", lambda m: m.name),
            ("LOCATION", lambda m: m.location),
        ],
        sort_key=lambda m: m.metrics[metric_key],
        top=args.top,
        header=header(min(args.top, len(scored)), len(scored), langs_str, _tests_word(args.include_tests)),
    )
    return 0


def run_size_main(
    args: argparse.Namespace,
    langs: "list[str]",
    rule: "dict[str, list[str]]",
    header: "Callable[[int, int, str, str], str]",
    empty_message: str,
) -> int:
    """Shared tail for the two line-count detectors (largest-methods,
    largest-classes): scan structurally, fold nested matches into their outer
    one, and print the LINES/NAME/LOCATION table. There is no threshold flag
    here, unlike `run_metric_main`, so every match found is eligible for
    display up to --top.

    `header` is called with (shown, total, langs_str, tests_str) once the
    match count is known; `empty_message` is a plain string since neither
    detector's "nothing found" line varies with anything computed here."""
    matches = h.run(rule, args.path, lang=langs, include_tests=args.include_tests,
                     extra_ignores=args.extra_ignore)
    matches = h.fold_nested(matches)

    if not matches:
        print(empty_message)
        return 0

    h.print_table(
        matches,
        columns=[
            ("LINES", lambda m: m.lines),
            ("NAME", lambda m: m.name),
            ("LOCATION", lambda m: m.location),
        ],
        sort_key=lambda m: m.lines,
        top=args.top,
        header=header(min(args.top, len(matches)), len(matches),
                       ", ".join(langs), _tests_word(args.include_tests)),
    )
    return 0
