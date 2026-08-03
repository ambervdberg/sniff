#!/usr/bin/env python3
"""Discover smell detectors: built-in registry modules plus manifest-based ones.

All 11 built-in detectors (complexity, nesting, size, sniff-patterns, etc.) live
as modules in `sniff.detectors.BUILTIN` and run in-process (see cli.py). No
built-in is discovered via a manifest any more.

External, consumer-defined detectors are added by dropping a `detector.yml`
manifest under `<scan_path>/.sniff/detectors/<name>/`. Manifests are parsed
without PyYAML (the project stays dependency-free), as a FLAT key: value file:

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
from typing import Iterable

from sniff import harness
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
    languages: list[str] = field(default_factory=list)  # empty means "unknown"

    def covers(self, present: "Iterable[str]") -> bool:
        """Whether this detector can match any of the languages in a repo.

        An external detector declares nothing, so its languages are unknown and
        it always runs: skipping it on a guess would hide findings."""
        if not self.languages:
            return True
        return bool(set(present) & set(self.languages))


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


def _load_manifest_detectors(
    manifest_glob: str, known_names: set[str]
) -> tuple[list[Detector], list[str]]:
    """Parse every `detector.yml` matching `manifest_glob` into a Detector.

    `known_names` is the set of names already claimed (built-ins plus anything
    already loaded from an earlier glob); a manifest whose name collides is
    rejected as an error and skipped rather than silently shadowing the
    existing detector. A manifest missing a required field (script) is also
    collected as an error rather than crashing the whole run, so one broken
    detector cannot hide all the others."""
    detectors: list[Detector] = []
    errors: list[str] = []

    for manifest in sorted(glob.glob(manifest_glob)):
        skill_dir = os.path.dirname(manifest)
        fields = _parse_manifest(manifest)

        name = fields.get("name") or os.path.basename(skill_dir)
        if name in known_names:
            errors.append(f"{name}: external detector at {manifest} shadows built-in detector, skipped")
            continue

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
        known_names.add(name)

    return detectors, errors


def _module_languages(module: ModuleType, scan_path: "str | None") -> list[str]:
    """The languages a built-in detector covers, as the module itself declares them.

    Most declare a static `LANGUAGES` list. sniff-patterns instead exposes a
    `languages(scan_path)` function, because its coverage depends on the rule
    catalog, which the scanned repo can extend. Reading the declaration rather
    than keeping a table here is what stops the support matrix from drifting
    away from what the code actually matches."""
    resolver = getattr(module, "languages", None)
    if callable(resolver):
        return sorted(resolver(scan_path))
    return sorted(getattr(module, "LANGUAGES", []))


def discover(scan_path: "str | None" = None) -> tuple[list[Detector], list[str]]:
    """Return (detectors, errors).

    Built-in detectors come straight from `sniff.detectors.BUILTIN`, one Detector
    per module, no manifest involved. External, manifest-based detectors are
    found by globbing skills/*/detector.yml, and, when `scan_path` is given,
    also `<scan_path>/.sniff/detectors/*/detector.yml` (the project-local
    convention consumers use to add their own detectors). A manifest whose name
    collides with a built-in (or an already-loaded external detector) is
    rejected as an error and skipped rather than shadowing the existing one.
    Detectors are returned sorted by name for stable output."""
    detectors: list[Detector] = [
        Detector(name=m.NAME, title=m.TITLE, module=m, args=list(m.DEFAULT_ARGS),
                 languages=_module_languages(m, scan_path))
        for m in BUILTIN
    ]
    known_names = {d.name for d in detectors}
    errors: list[str] = []

    skill_detectors, skill_errors = _load_manifest_detectors(
        os.path.join(SKILLS_ROOT, "*", "detector.yml"), known_names)
    detectors.extend(skill_detectors)
    errors.extend(skill_errors)

    if scan_path is not None:
        project_detectors, project_errors = _load_manifest_detectors(
            os.path.join(scan_path, ".sniff", "detectors", "*", "detector.yml"), known_names)
        detectors.extend(project_detectors)
        errors.extend(project_errors)

    detectors.sort(key=lambda d: d.name)
    return detectors, errors


def language_cell(detector: Detector) -> str:
    """How one detector's language coverage reads in a listing.

    'all' stands for every language sniff recognizes at all, so a detector that
    needs no parser does not push a sixteen-item list into every table row."""
    if not detector.languages:
        return "unknown"
    if set(detector.languages) >= set(harness.ALL_LANGUAGES):
        return "all"
    return ", ".join(detector.languages)


def render_list(detectors: list[Detector]) -> str:
    """One markdown table of every discovered detector, for `sniff --list`."""
    if not detectors:
        return ("No detectors found (empty built-in registry and no "
                ".sniff/detectors/*/detector.yml manifests).")

    lines = ["| DETECTOR | TITLE | LANGUAGES | RUN |", "| --- | --- | --- | --- |"]
    for d in detectors:
        lines.append(f"| {d.name} | {d.title} | {language_cell(d)} | `sniff --only {d.name} [DIR]` |")

    lines.append("\n`all` means every language sniff recognizes; `unknown` means the "
                 "detector does not declare its coverage.")

    if any(d.name == PATTERNS_DETECTOR for d in detectors):
        lines.append("Tip: `sniff --list-patterns` lists the individual pattern rules.")

    return "\n".join(lines)


# The languages sniff commits to covering in every detector. Anything else a
# detector happens to support is listed beside them rather than mixed in, so the
# commitment stays readable at a glance.
FIRST_CLASS_LANGUAGES = ["typescript", "tsx", "javascript", "python"]

# The one detector whose language coverage is data, not code.
PATTERNS_DETECTOR = "sniff-patterns"


def render_language_matrix(detectors: list[Detector]) -> str:
    """A per-detector language support table.

    Generated from what each detector declares, never hand-maintained: a matrix
    that can drift is worse than no matrix, because a wrong 'yes' turns "this
    detector cannot read your files" into what looks like a clean scan.

    `sniff-patterns` is left out. Every other row is a fixed capability of the
    detector, while its coverage is whatever its rules happen to declare, so a
    row of yes/no reads as a promise the catalog does not make. The pattern rule
    catalog below the matrix says which languages its rules actually cover."""
    lines = [
        "| DETECTOR | " + " | ".join(FIRST_CLASS_LANGUAGES) + " | ALSO COVERS |",
        "| --- |" + " --- |" * (len(FIRST_CLASS_LANGUAGES) + 1),
    ]

    for d in detectors:
        if d.name == PATTERNS_DETECTOR:
            continue
        supported = set(d.languages)
        marks = ["yes" if lang in supported else "no" for lang in FIRST_CLASS_LANGUAGES]
        extra = sorted(supported - set(FIRST_CLASS_LANGUAGES))
        lines.append(f"| {d.name} | " + " | ".join(marks) + f" | {', '.join(extra) or '-'} |")

    return "\n".join(lines)
