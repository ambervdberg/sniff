"""The types every other harness module speaks in: a match, a rule spec, and
the optional findings sink `sniff baseline` / `sniff diff` install."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence, Union

# Best-effort name extraction, tried in order against a definition's first line.
# Reading the single line from disk costs the calling agent nothing.
NAME_PATTERNS = [
    re.compile(r"\b(?:def|fn|func|function|fun)\s+([A-Za-z0-9_$]+)"),
    re.compile(r"\b(?:class|interface|enum|struct|trait|type|namespace|module)\s+([A-Za-z0-9_$]+)"),
    re.compile(r"\b(?:get|set)\s+([A-Za-z0-9_$]+)\s*\("),
    re.compile(r"([A-Za-z0-9_$#]+)\s*[:=]\s*(?:async\s+)?(?:function\b|\(?[^)=]*\)?\s*=>)"),
    re.compile(r"\b([A-Za-z0-9_$#~]+)\s*\("),
]

_NAME_STOPWORDS = {"function", "async", "return", "if", "for", "while", "switch"}

# Type of the `rule_or_pattern` argument accepted by run().
RuleSpec = Union[Mapping[str, Sequence[str]], str, Callable[[str], "str | None"]]


@dataclass
class Match:
    """One structural hit. Line fields are 0-based (as ast-grep reports them);
    use `.line` for a 1-based number suitable for display and editor jumps."""

    file: str                       # normalized to forward slashes
    start_line: int                 # 0-based
    end_line: int                   # 0-based
    byte_start: int
    byte_end: int
    name: str = "(anon)"
    text: str = ""                  # the matched node's source (as ast-grep reports it)
    metrics: dict = field(default_factory=dict)  # skill-specific extras (e.g. params, depth)

    @property
    def lines(self) -> int:
        """Physical line span of the match (inclusive)."""
        return self.end_line - self.start_line + 1

    @property
    def line(self) -> int:
        """1-based start line, for display and `file:line` jump targets."""
        return self.start_line + 1

    @property
    def location(self) -> str:
        """Authoritative `file:line` pointer."""
        return f"{self.file}:{self.line}"
