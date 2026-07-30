"""Static registry of built-in detectors.

Each module here exposes `NAME`, `TITLE`, `DEFAULT_ARGS`, and `main(argv) -> int`
(see any module for the shape). `discovery.discover()` wraps every entry in
`BUILTIN` into a `Detector` with `module` set, so `cli.py` can run it in-process
instead of shelling out to a subprocess script.

sniff-patterns runs through `sniff.patterns_detector`, a thin wrapper around
`sniff.patterns.format` (the ast-grep rule catalog runner), the same as every
other built-in.
"""

from sniff import patterns_detector
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
    most_parameters, no_duplicate_string, patterns_detector,
]
