"""Core ast-grep rule catalog and its formatter.

`rules_dir()` uses a plain `__file__` lookup rather than `importlib.resources`:
hatchling installs this package as real files on disk (not a zip), so a path
join is enough and avoids the extra ceremony resource-traversal APIs need.
"""
import os


def rules_dir() -> str:
    """Absolute path to the bundled core rules directory."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")
