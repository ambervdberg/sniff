#!/usr/bin/env python3
"""Load .sniff.toml for a scan dir. Hand-parsed TOML subset (stdlib-only):
[section] headers and flat `key = value` lines; values are quoted strings, ints,
or true/false. Unknown keys warn, never raise."""

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


def _repo_root(scan_dir: str) -> "str | None":
    """Nearest ancestor of `scan_dir` holding a `.git` entry, or None outside a repo.

    Checked with `os.path.exists`, not `isdir`: a worktree's `.git` is a file."""
    current = scan_dir
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def config_path(scan_dir: str) -> "str | None":
    """Path of the `.sniff.toml` that governs `scan_dir`, nearest first, or None.

    Scanning a subdirectory must still honour the config its repo committed at the
    root, so the search walks up. It stops at the repository root, and does not walk
    at all outside a repo: climbing past that point would let a stray file in a home
    directory silently rewrite an unrelated scan."""
    scan_dir = os.path.abspath(scan_dir)
    root = _repo_root(scan_dir)

    current = scan_dir
    while True:
        candidate = os.path.join(current, ".sniff.toml")
        if os.path.isfile(candidate):
            return candidate
        if root is None or current == root:
            return None
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def load(scan_dir: str) -> Config:
    cfg = Config()
    path = config_path(scan_dir)
    if path is None:
        return cfg
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

        parser = _SECTION_PARSERS.get(section)
        if parser is not None:
            parser(cfg, key, value, lineno)
    return cfg


def _apply_rules_entry(cfg: Config, key: str, value: str, lineno: int) -> None:
    """A [rules] entry: `false` disables the rule, a severity name overrides it."""
    if value == "false":
        cfg.disabled_rules.add(key)
    elif value in ("error", "warning", "info", "hint"):
        cfg.severity_overrides[key] = value
    elif value != "true":
        cfg.warnings.append(f".sniff.toml:{lineno}: rule value must be false or a severity")


def _apply_detectors_entry(cfg: Config, key: str, value: str, lineno: int) -> None:
    """A [detectors] entry: `skip` is a name list, `<detector>.<arg>` a threshold."""
    if key == "skip":
        cfg.skip_detectors |= {p.strip() for p in value.split(",") if p.strip()}
    elif "." in key:
        detector, arg = key.split(".", 1)
        cfg.thresholds.setdefault(detector, {})[arg] = value
    else:
        cfg.warnings.append(f".sniff.toml:{lineno}: unknown detectors key {key!r}")


def _apply_ignore_entry(cfg: Config, key: str, value: str, lineno: int) -> None:
    """An [ignore] entry: `globs` is the only recognized key."""
    if key == "globs":
        cfg.extra_ignores += _string_list(value)
    else:
        cfg.warnings.append(f".sniff.toml:{lineno}: unknown ignore key {key!r}")


# Section name -> the parser that turns one of its key/value lines into config.
# Unknown sections are already warned about at the section header, so a missing
# entry here simply means the line is ignored.
_SECTION_PARSERS = {
    "rules": _apply_rules_entry,
    "detectors": _apply_detectors_entry,
    "ignore": _apply_ignore_entry,
}
