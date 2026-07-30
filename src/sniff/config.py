#!/usr/bin/env python3
"""Load .sniff.toml from a scan dir. Hand-parsed TOML subset (stdlib-only,
Python 3.9): [section] headers and flat `key = value` lines; values are quoted
strings, ints, or true/false. Unknown keys warn, never raise."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

KNOWN_SECTIONS = {"rules", "detectors", "ignore"}


@dataclass
class Config:
    disabled_rules: "set[str]" = field(default_factory=set)
    severity_overrides: "dict[str, str]" = field(default_factory=dict)
    skip_detectors: "set[str]" = field(default_factory=set)
    thresholds: "dict[str, dict[str, str]]" = field(default_factory=dict)
    extra_ignores: "list[str]" = field(default_factory=list)
    warnings: "list[str]" = field(default_factory=list)


_KV = re.compile(r'^([A-Za-z0-9_.-]+)\s*=\s*(.+)$')


def _value(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def _string_list(raw: str) -> "list[str]":
    """Parse a multi-value setting written either way real TOML files write it.

    Both `globs = "a/**,b/**"` (this parser's flat form) and `globs = ["a/**",
    "b/**"]` (the array a TOML author reaches for) yield ["a/**", "b/**"].
    Without the array branch a bracketed value survives as one nonsense glob
    that silently matches nothing."""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    parts = (_value(part).strip() for part in raw.split(","))
    return [part for part in parts if part]


def load(scan_dir: str) -> Config:
    cfg = Config()
    path = os.path.join(scan_dir, ".sniff.toml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return cfg

    section = ""
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if section not in KNOWN_SECTIONS:
                cfg.warnings.append(f".sniff.toml:{lineno}: unknown section [{section}]")
            continue
        match = _KV.match(line)
        if not match:
            cfg.warnings.append(f".sniff.toml:{lineno}: cannot parse line")
            continue
        key, value = match.group(1), _value(match.group(2))

        if section == "rules":
            if value == "false":
                cfg.disabled_rules.add(key)
            elif value in ("error", "warning", "info", "hint"):
                cfg.severity_overrides[key] = value
            elif value != "true":
                cfg.warnings.append(f".sniff.toml:{lineno}: rule value must be false or a severity")
        elif section == "detectors":
            if key == "skip":
                cfg.skip_detectors |= {p.strip() for p in value.split(",") if p.strip()}
            elif "." in key:
                detector, arg = key.split(".", 1)
                cfg.thresholds.setdefault(detector, {})[arg] = value
            else:
                cfg.warnings.append(f".sniff.toml:{lineno}: unknown detectors key {key!r}")
        elif section == "ignore":
            if key == "globs":
                cfg.extra_ignores += _string_list(value)
            else:
                cfg.warnings.append(f".sniff.toml:{lineno}: unknown ignore key {key!r}")
    return cfg
