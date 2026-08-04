"""`sniff baseline write` and `sniff diff`: fingerprint-based regression gating.

`run_baseline` snapshots every detector's current fingerprints to
`.sniff/baseline.json`; `run_diff` re-scans and compares against that
snapshot. A regression is a fingerprint that is new or whose value climbed
since the baseline; anything fixed or removed counts as an improvement
instead. `run_diff`'s exit code is the gate signal CI reads, so it answers
"did this get worse?" on its own, without folding in unrelated clean growth.
"""

from __future__ import annotations

import json
import os
import sys

from sniff import gate
from sniff.commands.scan import _discover_with_warnings


def run_baseline(argv: list[str]) -> int:
    """`sniff baseline write [DIR]`: scan DIR, save per-detector fingerprints as JSON.

    Saved to <DIR>/.sniff/baseline.json so a later `sniff diff` can compare
    against it. Returns 0 on success, 1 on a usage, path, or detector error."""
    if not argv or argv[0] != "write":
        print("usage: sniff baseline write [DIR]", file=sys.stderr)
        return 1

    path = argv[1] if len(argv) > 1 else "."
    if not os.path.isdir(path):
        print(f"error: {path!r} is not a directory. Check the path and try again.", file=sys.stderr)
        return 1

    try:
        fingerprints = gate.scan_fingerprints(_discover_with_warnings(path), path)
    except gate.DetectorFailure as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    payload = {"version": 3, "path": path, "fingerprints": fingerprints}

    baseline_dir = os.path.join(path, ".sniff")
    os.makedirs(baseline_dir, exist_ok=True)
    baseline_path = os.path.join(baseline_dir, "baseline.json")
    with open(baseline_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    print(f"sniff: baseline written to {baseline_path} ({len(fingerprints)} detectors)")
    return 0


def run_diff(argv: list[str]) -> int:
    """`sniff diff [DIR]`: compare a fresh fingerprint scan of DIR against its baseline.

    A regression is a fingerprint that is new (absent from the baseline) or whose
    value increased; fixed or removed fingerprints count as improvements instead.
    Returns 0 if no detector regressed (same or better), 1 if any detector has a
    new or worsened fingerprint, so the exit code alone answers "did this get
    worse?" without adding clean, unrelated growth to the count.

    --comment switches the table to markdown with a bold verdict line, suitable
    to paste as a PR comment."""
    comment = "--comment" in argv
    argv = [a for a in argv if a != "--comment"]
    path = argv[0] if argv else "."
    if not os.path.isdir(path):
        print(f"error: {path!r} is not a directory. Check the path and try again.", file=sys.stderr)
        return 1

    baseline_path = os.path.join(path, ".sniff", "baseline.json")
    if not os.path.isfile(baseline_path):
        print(f"error: no baseline at {baseline_path!r}. Run `sniff baseline write {path}` first.", file=sys.stderr)
        return 1

    with open(baseline_path, "r", encoding="utf-8") as fh:
        baseline_data = json.load(fh)

    if baseline_data.get("version") != 3:
        print(
            "error: baseline is in an old format. "
            f"Run `sniff baseline write {path}` to refresh it.",
            file=sys.stderr,
        )
        return 1

    try:
        current = gate.scan_fingerprints(_discover_with_warnings(path), path)
    except gate.DetectorFailure as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    baseline_fps: dict[str, dict[str, int]] = baseline_data.get("fingerprints", {})

    # A fingerprint is a regression when it is new to a detector's set or its
    # value climbed; the inverse (present in the baseline, gone or lower now)
    # is an improvement. Comparing on value, not presence alone, is what lets a
    # repeated duplicate-code block register even though its fingerprint (the
    # pair of files it spans) does not change between the two scans.
    names = sorted(set(baseline_fps) | set(current))
    regressions: dict[str, list[str]] = {}
    improvements = 0
    for name in names:
        before, after = baseline_fps.get(name, {}), current.get(name, {})
        new = [fp for fp, v in after.items() if v > before.get(fp, 0)]
        improvements += sum(1 for fp in before if before[fp] > after.get(fp, 0))
        if new:
            regressions[name] = sorted(new)

    if comment:
        return _print_diff_comment(names, regressions)
    return _print_diff_text(regressions, improvements)


def _print_diff_comment(names: list[str], regressions: dict[str, list[str]]) -> int:
    """Markdown table for `sniff diff --comment`, one row per detector.

    NEW VIOLATIONS lists up to 5 fingerprints per detector, then a `+N more`
    tally, so a detector with dozens of new violations doesn't blow up a PR
    comment."""
    lines = ["| DETECTOR | REGRESSIONS | NEW VIOLATIONS |", "| --- | --- | --- |"]
    for name in names:
        new = regressions.get(name, [])
        shown = ", ".join(new[:5])
        if len(new) > 5:
            shown += f", +{len(new) - 5} more"
        lines.append(f"| {name} | {len(new)} | {shown} |")
    print("\n".join(lines))
    print()
    print("**worse**" if regressions else "**same or better**")
    return 1 if regressions else 0


def _print_diff_text(regressions: dict[str, list[str]], improvements: int) -> int:
    """Plain-text `sniff diff` output: regression lines when any exist, the
    exact `same or better` phrase (CI greps for it) when none do."""
    if regressions:
        lines = [f"{'DETECTOR':<24} NEW VIOLATIONS"]
        for name in sorted(regressions):
            lines.append(f"{name:<24} {', '.join(regressions[name])}")
        print("\n".join(lines))
        print()
        total_new = sum(len(fps) for fps in regressions.values())
        print(f"worse: {total_new} new violation(s), {improvements} improvement(s)")
        return 1

    print(f"same or better ({improvements} improvement(s))" if improvements else "same or better")
    return 0
