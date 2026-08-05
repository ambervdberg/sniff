"""Quality-gate scanning: fingerprints, thresholds, fail-closed collection.

`sniff baseline` and `sniff diff` gate on *violations*, not on how many entities
exist. A violation is a finding at or above its detector's gate threshold.
Fingerprints identify the violating entity without line numbers, so unrelated
edits do not shift them.

Where a detector keeps its ranking value differs by detector, so a threshold
names the key rather than assuming one place:

    metrics dict   cyclomatic, cognitive, depth, params, template_lines
    sink field     lines (largest-files, largest-methods, large-classes),
                   count (most-imports)

Detectors that are already self-thresholded (sniff-patterns, duplicate-code,
no-duplicate-string, self-admitted-debt) have no entry here at all: every finding
they report is a violation, so their value is how many findings landed on that
fingerprint. That is also the fallback for any detector added later, so a new
detector is gated by default rather than silently ignored.

Counting matters wherever one fingerprint can legitimately cover several
findings. duplicate-code is the sharpest case: a clone group is identified by the
files it spans, so two unrelated duplicated blocks inside the same file share a
fingerprint. Flattening each to 1 would let the second one arrive for free.
"""

from __future__ import annotations

import os
from collections import Counter

from sniff import execution, harness

# detector name -> (key holding the finding's value, lowest value that violates)
#
# These floors filter what the *sink already received*, so they can only ever
# narrow a detector's own `--min`, never widen it: a detector that drops findings
# below its `--min` never hands them to the sink, and the gate cannot gate on a
# finding it never saw. Raising a detector's default `--min` above its floor here
# therefore silently moves the gate up with it. Keep every `--min` default at or
# below the floor below it, or move both together.
GATE_THRESHOLDS: dict[str, tuple[str, int]] = {
    "cyclomatic-complexity": ("cyclomatic", 10),
    "cognitive-complexity": ("cognitive", 15),
    "deepest-nesting": ("depth", 4),
    "most-parameters": ("params", 5),
    "large-inline-templates": ("template_lines", 50),
    "largest-methods": ("lines", 75),
    "large-classes": ("lines", 300),
    "largest-files": ("lines", 400),
    "most-imports": ("count", 20),
}

# Detectors whose fingerprint is the file alone (whole-file metrics).
_FILE_LEVEL = {"largest-files", "most-imports"}


class DetectorFailure(Exception):
    """A detector errored during a gated scan; the gate must not pass."""


def fingerprint_findings(
    detector_name: str, findings: list[dict], scan_root: str = "."
) -> dict[str, int]:
    """Sink entries -> {fingerprint: value}, keeping only gate violations.

    A detector with a gate threshold is measured: its value is the worst finding
    on that fingerprint. A detector without one is counted: every finding it
    reports is already a violation, so its value is how many of them there are
    (see the module docstring on why counting, not flattening to 1).

    `scan_root` is the directory the caller scanned (`sniff baseline write DIR`
    or `sniff diff DIR`); every fingerprint is built relative to it so the same
    repo scanned under two different spellings of that path (`.` vs its
    absolute form) produces the same fingerprints. See `_relative_file`."""
    if detector_name not in GATE_THRESHOLDS:
        return dict(Counter(_fingerprint_of(f, detector_name, scan_root) for f in findings))

    metric, floor = GATE_THRESHOLDS[detector_name]

    fingerprints: dict[str, int] = {}
    for finding in findings:
        value = _value_of(finding, metric)
        if value < floor:
            continue

        # The worst value wins: two findings can share a fingerprint (an
        # overloaded method, a name resolved from a line that repeats), and a
        # gate must not be talked down by the milder of the two.
        key = _fingerprint_of(finding, detector_name, scan_root)
        fingerprints[key] = max(value, fingerprints.get(key, 0))

    return fingerprints


def _value_of(finding: dict, metric: str) -> int:
    """The finding's measured value.

    A metric lives either in the detector's `metrics` dict or, for the detectors
    that rank on a plain row field, directly on the sink entry."""
    raw = finding["metrics"].get(metric, finding.get(metric, 1))
    return int(raw)


def _fingerprint_of(finding: dict, detector_name: str, scan_root: str) -> str:
    """The finding's line-free identity: the file, plus the entity inside it.

    sniff-patterns is keyed by the rule instead of the entity, since a pattern
    hit names a rule, not a definition."""
    file = _relative_file(finding["file"], scan_root)
    if detector_name == "sniff-patterns":
        return f"{finding['metrics']['rule']}|{file}"
    if detector_name in _FILE_LEVEL:
        return file
    return f"{file}|{finding['name']}"


def _relative_file(file: str, scan_root: str) -> str:
    """A finding's file path, made portable: relative to `scan_root`, forward
    slashes only.

    A detector reports `file` exactly as the command-line path was spelled
    (`.`, an absolute path, some other relative prefix), so the raw value is
    not stable across two scans of the same directory spelled two different
    ways. duplicate-code's fingerprint is the one exception worth naming: a
    clone group spans several files, joined with `+` (see `_sink_row_file`),
    so each side of the join is normalized on its own."""
    return "+".join(_relative_single_file(part, scan_root) for part in file.split("+"))


def _relative_single_file(file: str, scan_root: str) -> str:
    """One path, made portable relative to `scan_root`.

    Resolving both `file` and `scan_root` to absolute paths first (via
    `os.path.abspath`, which does not touch the filesystem) makes the
    subtraction agree regardless of spelling, as long as both scans ran from
    the same working directory, which every `sniff` invocation does."""
    absolute_file = os.path.abspath(file)
    absolute_root = os.path.abspath(scan_root)
    relative = os.path.relpath(absolute_file, absolute_root)
    return relative.replace("\\", "/")


def _is_builtin(detector) -> bool:
    """True when the detector runs in-process, so its findings reach the sink.

    Same test `execution.run_detector_json` uses to choose the in-process path; an
    external detector is a script run in a subprocess, whose sink is its own."""
    return detector.module is not None


def _run_one(detector, path: str) -> dict:
    return execution.run_detector_json(detector, path)


def scan_fingerprints(detectors, path: str) -> dict[str, dict[str, int]]:
    """Run every built-in detector over `path` -> {detector: {fingerprint: value}}.

    Raises DetectorFailure when any detector errors or exits non-zero. Failing
    closed is the point: a detector that silently reported nothing is
    indistinguishable from a clean repo, and a gate that cannot tell those apart
    is worse than no gate.

    Every detector runs even once one has failed, and the failures are reported
    together. Stopping at the first would hide the rest, so a broken environment
    (no ast-grep, an unreadable tree) would take one `sniff diff` run per broken
    detector to diagnose. External (subprocess) detectors are skipped entirely."""
    results: dict[str, dict[str, int]] = {}
    failures: list[str] = []

    for detector in detectors:
        if not _is_builtin(detector):
            continue  # external subprocess detectors have no sink; not gated

        findings, failure = _collect(detector, path)
        if failure:
            failures.append(failure)
            continue

        results[detector.name] = fingerprint_findings(detector.name, findings, path)

    if failures:
        raise DetectorFailure("; ".join(failures))

    return results


def _collect(detector, path: str) -> tuple[list[dict], str | None]:
    """Run one detector with the sink installed -> (findings, failure or None).

    The sink is a module global, so it is uninstalled in a `finally`: leaking it
    would make every later print_table call in the process keep appending to a
    list nobody reads."""
    harness.FINDINGS_SINK = []
    try:
        result = _run_one(detector, path)
    finally:
        findings, harness.FINDINGS_SINK = harness.FINDINGS_SINK, None

    return findings, _failure_of(detector, result)


def _failure_of(detector, result: dict) -> str | None:
    """How this detector failed, or None when it ran cleanly."""
    if not result.get("error") and result.get("exit_code") in (0, None):
        return None

    cause = result.get("error") or f"exit code {result.get('exit_code')}"
    return f"detector {detector.name!r} failed: {cause}"
