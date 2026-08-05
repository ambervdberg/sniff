"""Printing the one small table the calling agent sees, and recording every row
into the findings sink when one is installed."""

from __future__ import annotations

from typing import Callable, Sequence

from sniff.harness.model import Match


def _findings_sink() -> "list | None":
    """The sink currently installed on the package, or None.

    Read through the package rather than imported by value: callers install one
    with `harness.FINDINGS_SINK = []`, which rebinds the package attribute only.
    A module-level `from ... import FINDINGS_SINK` here would keep pointing at
    the original None and silently record nothing."""
    from sniff import harness  # local: the package imports this module

    return harness.FINDINGS_SINK

# A column is a (header, accessor) pair. The accessor maps a Match to a cell value.
Column = tuple[str, Callable[[Match], object]]


def _sink_row_file(row: object) -> str:
    """Which file a printed row belongs to.

    Every row type but one names its file directly. duplicate-code's clone is a
    group of copies rather than a single site, so its file is the set of files it
    spans: an identity that survives edits elsewhere in those files."""
    file = getattr(row, "file", None)
    if file:
        return str(file)

    occurrences = getattr(row, "occurrences", None) or []
    return "+".join(sorted({o.file for o in occurrences if getattr(o, "file", None)}))


def _sink_row_name(row: object) -> str:
    """What a printed row is called, for fingerprinting.

    A Match carries the resolved definition name. no-duplicate-string's row has
    no name at all, because the duplicated literal is what identifies it."""
    for attr in ("name", "string"):
        value = getattr(row, attr, None)
        if value:
            return str(value)
    return "(anon)"


def _sink_entry(row: object) -> dict:
    """One findings-sink record for a printed row.

    print_table is handed Matches by the AST detectors and a detector-local
    dataclass by the rest (FileStat, Clone, DuplicateString, DebtFile), so
    nothing beyond the row's own columns is guaranteed and every field is read
    defensively. `lines` and `count` are recorded because that is where the
    line-count and per-file-count detectors keep their ranking value; the AST
    detectors keep theirs in `metrics`."""
    return {
        "file": _sink_row_file(row),
        "line": int(getattr(row, "line", 0) or 0),
        "name": _sink_row_name(row),
        "lines": int(getattr(row, "lines", 0) or 0),
        "count": int(getattr(row, "count", 0) or 0),
        "metrics": dict(getattr(row, "metrics", None) or {}),
    }


def print_table(
    matches: Sequence[Match],
    columns: Sequence[Column],
    sort_key: "Callable[[Match], object] | None" = None,
    top: "int | None" = None,
    header: "str | None" = None,
) -> None:
    """Print matches as a compact markdown table and nothing else.

    This is the only thing the calling agent should ever see. Never print raw
    matches or AST JSON alongside it. Cells are not column-aligned or padded:
    each row is a plain '| a | b |' line, left for a markdown renderer (or the
    calling agent, when relaying it as-is) to lay out."""
    sink = _findings_sink()
    if sink is not None:
        sink.extend(_sink_entry(m) for m in matches)
    rows = list(matches)
    if sort_key is not None:
        rows.sort(key=sort_key, reverse=True)
    if top is not None:
        rows = rows[:top]

    if not rows:
        print("No matches.")
        return

    headers = [c[0] for c in columns]
    cells = [[_fmt(c[1](m)) for c in columns] for m in rows]

    if header:
        print(header + "\n")

    # Markdown table: renders as a real table when the agent relays it in a reply
    # (space-aligned text collapses there). Plain `---` separators only, no `:`
    # alignment markers, which some strict renderers reject and fall back to raw.
    def _row(values: Sequence[str]) -> str:
        return "| " + " | ".join(v.replace("|", "\\|") for v in values) + " |"

    print(_row(headers))
    print(_row(["---"] * len(headers)))
    for row in cells:
        print(_row(row))


def _fmt(value: object) -> str:
    return str(value)
