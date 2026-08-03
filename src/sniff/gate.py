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
they report is a violation worth one point. That is also the fallback for any
detector added later, so a new detector is gated by default rather than silently
ignored.
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

# Every finding of a self-thresholded or unknown detector counts once.
_UNGATED = (None, 1)


class DetectorFailure(Exception):
    """A detector errored during a gated scan; the gate must not pass."""


def fingerprint_findings(detector_name: str, findings: list[dict]) -> dict[str, int]:
    """Sink entries -> {fingerprint: value}, keeping only gate violations."""
    if detector_name == "sniff-patterns":
        return _pattern_fingerprints(findings)

    metric, floor = GATE_THRESHOLDS.get(detector_name, _UNGATED)

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


def _pattern_fingerprints(findings: list[dict]) -> dict[str, int]:
    """sniff-patterns fingerprints: how often each rule fires in each file.

    Every pattern hit is a violation by construction, so the value is a count
    rather than a metric. Counting per rule per file (not per line) is what
    keeps the fingerprint stable while the file around it moves."""
    return dict(Counter(f"{f['metrics']['rule']}|{f['file']}" for f in findings))


def _value_of(finding: dict, metric: "str | None") -> int:
    """The finding's gated value: 1 when the detector is self-thresholded.

    A metric lives either in the detector's `metrics` dict or, for the detectors
    that rank on a plain row field, directly on the sink entry."""
    if metric is None:
        return 1
    raw = finding["metrics"].get(metric, finding.get(metric, 1))
    return int(raw)


def _fingerprint_of(finding: dict, detector_name: str) -> str:
    """The finding's line-free identity: the file, plus the entity inside it."""
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
