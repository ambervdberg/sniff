"""Language identity: which extensions map to which ast-grep language id.

Pure data and pure functions, so this is the bottom of the harness package and
imports nothing from its siblings."""

from __future__ import annotations

from typing import Sequence

# Map source extensions to ast-grep language ids.
EXT_LANG = {
    ".ts": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".py": "python",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin",
    ".swift": "swift",
    ".scala": "scala",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
}

# Every language the file walk recognizes. Detectors that read files rather than
# parse them (line counts, string literals) support all of them, so they declare
# their LANGUAGES as this list instead of repeating it.
ALL_LANGUAGES = sorted(set(EXT_LANG.values()))


def covered_languages(present: "Sequence[str]", supported: "Sequence[str]") -> "list[str]":
    """The languages a detector can actually match out of the ones in the repo.

    Every detector declares a LANGUAGES list: the languages it has rules for.
    Narrowing the detected languages against that list before scanning is what
    keeps a header from claiming a detector examined Java when it has no Java
    rules at all."""
    return sorted(lang for lang in set(present) if lang in set(supported))


def not_applicable(present: "Sequence[str]", supported: "Sequence[str]") -> str:
    """The one line a detector prints when it covers none of the repo's languages.

    Says what the detector does cover, so the reader can tell "nothing to report"
    apart from "this tool cannot see your code"."""
    found = ", ".join(sorted(set(present))) or "none"
    covers = ", ".join(sorted(set(supported))) or "no languages"
    return f"Not applicable: this detector covers {covers}; the files here are {found}."
