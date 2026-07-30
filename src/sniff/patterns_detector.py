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


def main(argv: "list[str] | None" = None) -> int:
    return fmt.main(argv)
