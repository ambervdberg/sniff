#!/usr/bin/env python3
"""Discover smell detectors by globbing skills/*/detector.yml.

Each detector skill drops a small `detector.yml` manifest next to its script. The
umbrella runner (`run.py`) globs every manifest under the skills root and invokes
the named script uniformly, so adding a detector is zero-cost: drop a manifest and
it joins `sniff` automatically, with no edit to the runner. This mirrors the
sniff-patterns rule catalog, where adding a rule file costs nothing.

The manifest is parsed without PyYAML (the project stays dependency-free, matching
how sniff-patterns hand-parses its rule files). It is therefore a FLAT key: value file:

    name: cognitive-complexity
    title: High cognitive complexity methods
    script: scripts/cognitive_complexity.py
    args: --top 20

`args` is optional and space-split into extra CLI args appended after the scan DIR.
"""

from __future__ import annotations

import glob
import os
import shlex
from dataclasses import dataclass, field

# src/sniff/discovery.py -> repo root is three levels up; skills/ lives beside src/.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_ROOT = os.path.join(_REPO_ROOT, "skills")


@dataclass
class Detector:
    """One discovered detector: enough to invoke it and label its section."""

    name: str
    title: str
    script: str  # absolute path to the detector's script
    args: list[str] = field(default_factory=list)
    skill_dir: str = ""


def _parse_manifest(path: str) -> dict[str, str]:
    """Read a flat `key: value` manifest. Blank lines and `#` comments are skipped."""
    fields: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def discover() -> tuple[list[Detector], list[str]]:
    """Return (detectors, errors).

    Globs skills/*/detector.yml, parses each into a Detector. A manifest missing a
    required field (name + script) is collected as an error string rather than
    crashing the whole run, so one broken detector cannot hide all the others.
    Detectors are returned sorted by name for stable output."""
    detectors: list[Detector] = []
    errors: list[str] = []

    for manifest in sorted(glob.glob(os.path.join(SKILLS_ROOT, "*", "detector.yml"))):
        skill_dir = os.path.dirname(manifest)
        fields = _parse_manifest(manifest)

        name = fields.get("name") or os.path.basename(skill_dir)
        script_rel = fields.get("script", "")
        if not script_rel:
            errors.append(f"{manifest}: missing required 'script' field")
            continue

        script_abs = os.path.normpath(os.path.join(skill_dir, script_rel))
        if not os.path.isfile(script_abs):
            errors.append(f"{name}: script not found: {script_abs}")
            continue

        detectors.append(Detector(
            name=name,
            title=fields.get("title", name),
            script=script_abs,
            args=shlex.split(fields.get("args", "")),
            skill_dir=skill_dir,
        ))

    detectors.sort(key=lambda d: d.name)
    return detectors, errors


def render_list(detectors: list[Detector]) -> str:
    """One markdown table of every discovered detector, for `sniff --list`."""
    if not detectors:
        return "No detectors found (no skills/*/detector.yml manifests)."

    lines = ["| DETECTOR | TITLE | RUN |", "| --- | --- | --- |"]
    for d in detectors:
        lines.append(f"| {d.name} | {d.title} | `sniff --only {d.name} [DIR]` |")

    if any(d.name == "sniff-patterns" for d in detectors):
        lines.append("\nTip: `sniff --list-patterns` lists the individual pattern rules.")

    return "\n".join(lines)
