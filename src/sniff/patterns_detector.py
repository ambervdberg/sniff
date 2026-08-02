#!/usr/bin/env python3
"""Built-in detector wrapper around the pattern-rule formatter.

Adapts `sniff.patterns.format` (the ast-grep rule catalog runner) to the same
`NAME` / `TITLE` / `DEFAULT_ARGS` / `main(argv) -> int` shape every other
built-in detector exposes, so `sniff.detectors.BUILTIN` can run it in-process
like the rest instead of shelling out to a subprocess script.
"""
from __future__ import annotations

from sniff.patterns import format as fmt

NAME = "sniff-patterns"
TITLE = "Pattern rule findings"
DEFAULT_ARGS: "list[str]" = []


def languages(scan_path: "str | None" = None) -> "list[str]":
    """The languages this detector covers: whatever its rules declare.

    Every other detector declares a static `LANGUAGES` list, but the pattern
    catalog grows: a consumer repo can drop its own rule into `.sniff/rules/`.
    Reading the catalog instead of hardcoding it means adding a rule for a new
    language is enough to make sniff scan that language."""
    return sorted({language for *_rest, language in fmt.catalog_rules(scan_path) if language})


def main(argv: "list[str] | None" = None) -> int:
    return fmt.main(argv)
