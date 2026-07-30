"""Static registry of built-in detectors.

Each module here exposes `NAME`, `TITLE`, `DEFAULT_ARGS`, and `main(argv) -> int`
(see any module for the shape). `discovery.discover()` wraps every entry in
`BUILTIN` into a `Detector` with `module` set, so `cli.py` can run it in-process
instead of shelling out to a subprocess script.

sniff-patterns is not in this registry yet: it still runs through its old
`skills/sniff-patterns/scripts/format.py` subprocess path (see discovery.py).
A future task adds a `patterns_detector` module here and flips it over.
"""

from sniff.detectors import (
    cognitive_complexity,
    cyclomatic_complexity,
    deepest_nesting,
    large_classes,
    large_inline_templates,
    largest_files,
    largest_methods,
    most_imports,
    most_parameters,
    no_duplicate_string,
)

BUILTIN = [
    cognitive_complexity, cyclomatic_complexity, deepest_nesting, large_classes,
    large_inline_templates, largest_files, largest_methods, most_imports,
    most_parameters, no_duplicate_string,
]
