#!/usr/bin/env python3
"""Discover smell detectors: built-in registry modules plus manifest-based ones.

The 10 built-in detectors (complexity, nesting, size, etc.) live as modules in
`sniff.detectors.BUILTIN` and run in-process (see cli.py). sniff-patterns is not
yet in that registry (a later task adds it), so it is still discovered the old
way: `skills/sniff-patterns/detector.yml` is globbed and its script run as a
subprocess, exactly like every detector used to work before the registry existed.

The manifest is parsed without PyYAML (the project stays dependency-free, matching
how sniff-patterns hand-parses its rule files). It is therefore a FLAT key: value file:

    name: sniff-patterns
    title: Pattern rule catalog
    script: scripts/format.py
    args: --top 20

`args` is optional and space-split into extra CLI args appended after the scan DIR.
"""

from __future__ import annotations

import glob
import os
import shlex
from dataclasses import dataclass, field
from types import ModuleType

from sniff.detectors import BUILTIN

# src/sniff/discovery.py -> repo root is three levels up; skills/ lives beside src/.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_ROOT = os.path.join(_REPO_ROOT, "skills")


@dataclass
class Detector:
    """One discovered detector: enough to invoke it and label its section.

    Exactly one of `script` (subprocess/external detector) or `module` (built-in,
    run in-process) is set."""

    name: str
    title: str
    script: str = ""                      # set for subprocess (external) detectors
    module: "ModuleType | None" = None    # set for built-in detectors
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

    Built-in detectors come straight from `sniff.detectors.BUILTIN`, one Detector
    per module, no manifest involved. Any remaining manifest-based detector
    (currently just sniff-patterns) is still found by globbing
    skills/*/detector.yml, parsed into a Detector the same way as before the
    registry existed. A manifest missing a required field (name + script) is
    collected as an error string rather than crashing the whole run, so one
    broken detector cannot hide all the others. Detectors are returned sorted by
    name for stable output."""
    detectors: list[Detector] = [
        Detector(name=m.NAME, title=m.TITLE, module=m, args=list(m.DEFAULT_ARGS))
        for m in BUILTIN
    ]
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
