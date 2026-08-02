#!/usr/bin/env python3
"""Regenerate the parts of the docs that are derived from the code.

Run this after changing a detector's languages or a pattern rule. Two README
blocks are generated, each fenced by HTML markers so the rest of the file stays
hand-written:

    <!-- language-matrix:start -->   which languages each detector can read
    <!-- pattern-catalog:start -->   the sniff-patterns rule catalog

Both are guarded by tests, so forgetting to run this fails the suite rather than
shipping a README that claims support the code does not have.

Usage: python scripts/update_docs.py [--check]

`--check` reports drift without writing anything.
"""

from __future__ import annotations

import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Run straight from a checkout, with or without the package installed.
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from sniff import discovery                      # noqa: E402  (needs the path above)
from sniff.patterns import format as fmt         # noqa: E402

README = os.path.join(_REPO_ROOT, "README.md")


def generated_blocks() -> "dict[str, str]":
    """Marker name -> the text that belongs between its start and end markers."""
    detectors, _errors = discovery.discover()
    return {
        "language-matrix": discovery.render_language_matrix(detectors).strip(),
        "pattern-catalog": fmt.render_catalog_table(fmt.catalog_rules()).strip(),
    }


def rendered_readme(current: str) -> str:
    """`current` with every generated block replaced by its freshly rendered text."""
    for marker, body in generated_blocks().items():
        pattern = re.compile(rf"(<!-- {marker}:start -->\n).*?(<!-- {marker}:end -->)", re.DOTALL)
        current, count = pattern.subn(lambda m: m.group(1) + body + "\n" + m.group(2), current)
        if count != 1:
            sys.exit(f"error: expected exactly one {marker} block in README.md, found {count}")

    return current


def main(argv: "list[str] | None" = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    check_only = "--check" in argv

    with open(README, "r", encoding="utf-8") as fh:
        current = fh.read()

    updated = rendered_readme(current)
    if updated == current:
        # Say so out loud: silence on success is indistinguishable from a script
        # that did not run.
        print("README.md is already up to date")
        return 0

    if check_only:
        print("README.md is out of date; run python scripts/update_docs.py")
        return 1

    with open(README, "w", encoding="utf-8", newline="") as fh:
        fh.write(updated)
    print("README.md tables regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
