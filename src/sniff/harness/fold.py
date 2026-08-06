"""Collapsing nested matches so a function that contains a closure reports once."""

from __future__ import annotations

from sniff.harness.model import Match

def fold_nested(matches: list[Match]) -> list[Match]:
    """Keep only the outermost match per overlapping region in each file.

    A 200-line function that contains a 150-line closure should report once, as
    200, not twice. Sorting by start byte ascending then end byte descending puts
    each outer match before the inner ones it contains, so we drop anything that
    starts before the current outer match ends."""
    by_file: dict[str, list[Match]] = {}
    for m in matches:
        by_file.setdefault(m.file, []).append(m)

    kept: list[Match] = []
    for items in by_file.values():
        items.sort(key=lambda m: (m.byte_start, -m.byte_end))

        open_end = -1
        for m in items:
            if m.byte_start < open_end:
                continue  # nested inside an already-kept outer match
            kept.append(m)
            open_end = m.byte_end

    return kept
