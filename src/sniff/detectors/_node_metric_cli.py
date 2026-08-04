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

Each tail used to take its per-detector wording and callables as a fistful of
loose keyword arguments (nine for the metric tail, six for the size tail). That
long parameter list was itself a smell: the four/two callers were passing the
same bundle of "who am I" facts every time, just with different values. The
MetricSpec/SizeSpec dataclasses below carry that bundle as one object instead,
so each detector builds its spec once and the runners take only (args, langs,
spec).

Public API:
    new_parser(description)                    -> parser with path/--top/--lang
    finish_parser(parser)                       -> adds --include-tests/--extra-ignore
    detect_and_gate(args, languages)            -> langs to scan, or None (caller returns 0)
    MetricSpec                                  -> per-detector identity for run_metric_main
    SizeSpec                                    -> per-detector identity for run_size_main
    run_metric_main(args, langs, spec)          -> shared tail for the four node_metric detectors
    run_size_main(args, langs, spec)            -> shared tail for largest-methods/largest-classes
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
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


@dataclass(frozen=True)
class MetricSpec:
    """Everything that makes one node_metric detector different from the other
    three, bundled into a single value instead of five loose parameters.

    scorer         one of node_metric's per-metric functions (nm.cognitive,
                   nm.cyclomatic, nm.nesting_depth, nm.params); it must return
                   Matches with `metric_key` set in `.metrics`.
    metric_key     the key that scorer writes into each Match's `.metrics`
                   dict, e.g. "cognitive" or "params".
    minimum_attr   the argparse dest holding the detector's threshold flag
                   (e.g. "minimum" for --min, "min_depth" for --min-depth).
                   Reading it by name here means each detector keeps choosing
                   its own flag spelling without run_metric_main needing to
                   know it.
    column         the table's left-hand header, e.g. "COGNITIVE", "PARAMS".
    header         called with (shown, total, langs_str, tests_str) once the
                   threshold filter is known; each detector phrases this
                   differently, so it stays a callable rather than a template
                   string built here.
    empty_message  called with just langs_str when nothing cleared the
                   threshold.
    """

    scorer: Scorer
    metric_key: str
    minimum_attr: str
    column: str
    header: "Callable[[int, int, str, str], str]"
    empty_message: "Callable[[str], str]"


def run_metric_main(args: argparse.Namespace, langs: "list[str]", spec: MetricSpec) -> int:
    """Shared tail of a node_metric detector's main(): score, threshold, print.

    Everything that varies between the four callers (cognitive/cyclomatic
    complexity, nesting depth, parameter count) lives on `spec`; this function
    only knows the shape all four share."""
    langs_str = ", ".join(langs)
    minimum = getattr(args, spec.minimum_attr)

    scored = spec.scorer(args.path, langs=langs, include_tests=args.include_tests,
                          extra_ignores=args.extra_ignore)
    scored = [m for m in scored if m.metrics.get(spec.metric_key, 0) >= minimum]

    if not scored:
        print(spec.empty_message(langs_str))
        return 0

    h.print_table(
        scored,
        columns=[
            (spec.column, lambda m: m.metrics[spec.metric_key]),
            ("NAME", lambda m: m.name),
            ("LOCATION", lambda m: m.location),
        ],
        sort_key=lambda m: m.metrics[spec.metric_key],
        top=args.top,
        header=spec.header(min(args.top, len(scored)), len(scored), langs_str, _tests_word(args.include_tests)),
    )
    return 0


@dataclass(frozen=True)
class SizeSpec:
    """Everything that makes one line-count detector different from the other
    (largest-methods vs largest-classes), bundled into a single value.

    rule           the {language: [node kinds]} map (or ast-grep pattern) that
                   tells the harness what counts as a match.
    header         called with (shown, total, langs_str, tests_str) once the
                   match count is known; each detector phrases this
                   differently, so it stays a callable rather than a template
                   string built here.
    empty_message  a plain string, since neither detector's "nothing found"
                   line varies with anything computed here.
    """

    rule: "dict[str, list[str]]"
    header: "Callable[[int, int, str, str], str]"
    empty_message: str


def run_size_main(args: argparse.Namespace, langs: "list[str]", spec: SizeSpec) -> int:
    """Shared tail for the two line-count detectors (largest-methods,
    largest-classes): scan structurally, fold nested matches into their outer
    one, and print the LINES/NAME/LOCATION table. There is no threshold flag
    here, unlike `run_metric_main`, so every match found is eligible for
    display up to --top."""
    matches = h.run(spec.rule, args.path, lang=langs, include_tests=args.include_tests,
                     extra_ignores=args.extra_ignore)
    matches = h.fold_nested(matches)

    if not matches:
        print(spec.empty_message)
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
        header=spec.header(min(args.top, len(matches)), len(matches),
                            ", ".join(langs), _tests_word(args.include_tests)),
    )
    return 0
