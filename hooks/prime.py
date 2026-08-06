#!/usr/bin/env python3
"""SessionStart hook: print `sniff prime` context without assuming the CLI is installed.

The plugin ships skills and hooks; the `sniff` CLI itself comes from PyPI. Neither
Claude Code nor Codex has an install-time lifecycle hook, so the first session is
the earliest moment the plugin can make the CLI available. Three tiers, first hit
wins:

1. `sniff` on PATH: the user's own install, always preferred.
2. `uvx` on PATH: run the PyPI package pinned to this plugin's own version, so the
   CLI the hook runs always matches the skills that shipped with it (never
   `@latest`, which would re-resolve on every session start and could drift ahead
   of the plugin). uvx caches the pinned resolve, so only the first session after
   an install or update touches the network.
3. Neither: print an install hint and exit 0. A missing optional tool must never
   fail the hook and block the session.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

# hooks/prime.py -> <plugin root>
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INSTALL_HINT = "install the sniff CLI with: uv tool install sniff-smells (or: pip install sniff-smells)"


def plugin_version() -> str:
    """The version this plugin shipped as; pins the uvx fallback to a matching CLI."""
    path = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["version"]


def main() -> int:
    if shutil.which("sniff"):
        # The installed CLI's own exit code is deliberately not propagated. This
        # hook always exits 0: a session must never fail to start over a context
        # block, and hooks.json chains interpreters with `||`, so a non-zero exit
        # here would rerun the whole wrapper under the other interpreter.
        subprocess.run(["sniff", "prime"])
        return 0

    if shutil.which("uvx"):
        pinned = f"sniff-smells=={plugin_version()}"
        proc = subprocess.run(["uvx", "--from", pinned, "sniff", "prime"])
        if proc.returncode == 0:
            print(f"(sniff ran via uvx; {INSTALL_HINT})")
            return 0
        # uvx itself failed (offline, version not on PyPI yet): fall through to the hint.

    print(f"sniff CLI not found; {INSTALL_HINT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
