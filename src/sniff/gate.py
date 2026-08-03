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

from collections import Counter

from sniff import harness

# detector name -> (key holding the finding's value, lowest value that violates)
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


def fingerprint_findings(detector_name: str, findings: list[dict]) -> dict[str, int]:
    """Sink entries -> {fingerprint: value}, keeping only gate violations.

    A detector with a gate threshold is measured: its value is the worst finding
    on that fingerprint. A detector without one is counted: every finding it
    reports is already a violation, so its value is how many of them there are
    (see the module docstring on why counting, not flattening to 1)."""
    if detector_name not in GATE_THRESHOLDS:
        return dict(Counter(_fingerprint_of(f, detector_name) for f in findings))

    metric, floor = GATE_THRESHOLDS[detector_name]

    fingerprints: dict[str, int] = {}
    for finding in findings:
        value = _value_of(finding, metric)
        if value < floor:
            continue

        # The worst value wins: two findings can share a fingerprint (an
        # overloaded method, a name resolved from a line that repeats), and a
        # gate must not be talked down by the milder of the two.
        key = _fingerprint_of(finding, detector_name)
        fingerprints[key] = max(value, fingerprints.get(key, 0))

    return fingerprints


def _value_of(finding: dict, metric: str) -> int:
    """The finding's measured value.

    A metric lives either in the detector's `metrics` dict or, for the detectors
    that rank on a plain row field, directly on the sink entry."""
    raw = finding["metrics"].get(metric, finding.get(metric, 1))
    return int(raw)


def _fingerprint_of(finding: dict, detector_name: str) -> str:
    """The finding's line-free identity: the file, plus the entity inside it.

    sniff-patterns is keyed by the rule instead of the entity, since a pattern
    hit names a rule, not a definition."""
    if detector_name == "sniff-patterns":
        return f"{finding['metrics']['rule']}|{finding['file']}"
    if detector_name in _FILE_LEVEL:
        return finding["file"]
    return f"{finding['file']}|{finding['name']}"


def _is_builtin(detector) -> bool:
    """True when the detector runs in-process, so its findings reach the sink.

    Same test `cli.run_detector_json` uses to choose the in-process path; an
    external detector is a script run in a subprocess, whose sink is its own."""
    return detector.module is not None


def _run_one(detector, path: str) -> dict:
    from sniff import cli  # local import; cli imports gate, avoid a cycle
    return cli.run_detector_json(detector, path)


def scan_fingerprints(detectors, path: str) -> dict[str, dict[str, int]]:
    """Run every built-in detector over `path` -> {detector: {fingerprint: value}}.

    Raises DetectorFailure on any non-zero exit or error. Failing closed is the
    point: a detector that silently reported nothing is indistinguishable from a
    clean repo, and a gate that cannot tell those apart is worse than no gate.
    External (subprocess) detectors are skipped entirely."""
    results: dict[str, dict[str, int]] = {}

    for detector in detectors:
        if not _is_builtin(detector):
            continue  # external subprocess detectors have no sink; not gated
        findings = _collect(detector, path)
        results[detector.name] = fingerprint_findings(detector.name, findings)

    return results


def _collect(detector, path: str) -> list[dict]:
    """Run one detector with the sink installed and hand back what it recorded.

    The sink is a module global, so it is uninstalled in a `finally`: leaking it
    would make every later print_table call in the process keep appending to a
    list nobody reads."""
    harness.FINDINGS_SINK = []
    try:
        result = _run_one(detector, path)
    finally:
        findings, harness.FINDINGS_SINK = harness.FINDINGS_SINK, None

    _raise_if_failed(detector, result)
    return findings


def _raise_if_failed(detector, result: dict) -> None:
    """Turn a detector's error or non-zero exit into a DetectorFailure."""
    if not result.get("error") and result.get("exit_code") in (0, None):
        return

    cause = result.get("error") or f"exit code {result.get('exit_code')}"
    raise DetectorFailure(f"detector {detector.name!r} failed: {cause}")
