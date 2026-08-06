#!/usr/bin/env python3
"""Render the rule catalog and its findings as markdown, for both the CLI and the README.

Two audiences, one set of helpers: `print_rule_table` / `print_rules_ran` /
`print_list_rules` print straight to stdout for `format.main`, while
`render_catalog_table` returns a string for `scripts/update_docs.py` to splice
into README.md. Both group by severity or language using the same
`SEVERITY_ORDER`, so the CLI's `--list-rules` view and the generated docs read
the same way.
"""

from __future__ import annotations

from sniff.patterns.expand import rule_languages

# ast-grep severity ordering, worst first, for sorting the table.
SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2, "hint": 3}


def print_rule_table(rows: list[tuple[str, str, int, list[str]]]) -> None:
    """Print ONE TABLE PER RULE: a heading carries the rule id, severity and count
    once, and a single-column table lists only the locations.

    Repeating the rule id and severity on every location row (the prior layout)
    wastes tokens when a rule has many hits. Hoisting them into a per-rule heading
    removes that repetition while keeping each section self-contained: the agent
    reads the heading for rule+severity, then every row underneath is a location for
    that rule. Narrow single-column rows always render (no viewport overflow).
    `rows` is already sorted worst-severity first; each is
    (rule_id, severity, count, locs), where `count` is the true total and `locs`
    may be a --top-locs-capped prefix of it."""
    if not rows:
        return

    # Escape any pipe in a cell so it does not break the markdown column split.
    def cell(value: str) -> str:
        return value.replace("|", "\\|")

    for rule_id, severity, count, locs in rows:
        print(f"### {rule_id} ({severity}): {count}\n")
        print("| LOCATION |")
        print("| --- |")
        if not locs:
            print("| (none) |")
        for loc in locs:
            print(f"| {cell(loc)} |")

        # The list is capped by --top-locs, so say how many hits are not shown.
        # Without this row the table silently reads as the complete set even
        # though the heading count disagrees with the number of rows.
        hidden = count - len(locs)
        if hidden > 0:
            print(f"| +{hidden} more (raise --top-locs to list them) |")
        print()


def print_rules_ran(ran: list[tuple[str, str, str, str, str]], cap: int = 30) -> None:
    """Print a one-line roster of every rule that ran this invocation.

    The findings table only lists rules that matched, so without this a reader
    cannot tell whether 1 of 2 rules ran or 1 of 200. Names are listed up to
    `cap`; beyond that only the count is shown to keep the line bounded as the
    catalog grows."""
    if not ran:
        return

    ids = [rid for rid, *_rest in sorted(ran)]
    if len(ids) <= cap:
        print(f"\nRan {len(ids)} rules: {', '.join(ids)}")
    else:
        print(f"\nRan {len(ids)} rules ({', '.join(ids[:cap])}, +{len(ids) - cap} more)")


def print_list_rules(rules: list[tuple[str, str, str, str, str]],
                     scan_path: "str | None" = None) -> None:
    """Print a catalog table grouped by language, one ### heading + RULE/SEVERITY/
    ORIGIN/MESSAGE table per language.

    Used by --list-rules so an agent can discover rule IDs and their intent
    without running a scan. ORIGIN ('core' vs 'local') tells the agent whether a
    rule comes from the shared catalog or a consumer-local .sniff/rules override.
    Grouping by language keeps a multi-language catalog (e.g. typescript + python)
    scannable instead of one long mixed table."""
    also = rule_languages(scan_path)
    languages = sorted({language for *_rest, language in rules})
    for language in languages:
        print(f"### {language}\n")
        print("| RULE | SEVERITY | ORIGIN | ALSO RUNS ON | MESSAGE |")
        print("| --- | --- | --- | --- | --- |")
        group = [r for r in rules if r[4] == language]
        for rule_id, severity, message, origin, _language in sorted(
                group, key=lambda r: (SEVERITY_ORDER.get(r[1], 9), r[0])):
            extra = ", ".join(lang for lang in also.get(rule_id, []) if lang != language) or "-"
            # Escape pipes so the markdown table stays valid.
            safe_msg = message.replace("|", "\\|")
            print(f"| {rule_id} | {severity} | {origin} | {extra} | {safe_msg} |")
        print()


def render_catalog_table(rules: list[tuple[str, str, str, str, str]]) -> str:
    """The rule catalog as one markdown table per language, worst severity first.

    Half the catalog cannot apply to any one reader, so the language is a heading
    rather than a column: it splits the list before the reader has to filter it.
    Severity leads each table so the ordering inside a block is visible instead of
    having to be inferred. The CLI's --list-rules view has the same shape and adds
    an ORIGIN column, which only matters once a repo has local rules."""
    also = rule_languages()
    lines: list[str] = []

    for language in sorted({language for *_rest, language in rules}):
        lines.append(f"### {language}\n")
        lines.append("| SEVERITY | RULE | ALSO RUNS ON | MESSAGE |")
        lines.append("| --- | --- | --- | --- |")

        group = [r for r in rules if r[4] == language]
        for rule_id, severity, message, _origin, _language in sorted(
                group, key=lambda r: (SEVERITY_ORDER.get(r[1], 9), r[0])):
            extra = ", ".join(lang for lang in also.get(rule_id, []) if lang != language) or "-"
            # Escape pipes so the markdown table stays valid.
            safe_msg = _unquoted(message).replace("|", "\\|")
            lines.append(f"| {severity} | {rule_id} | {extra} | {safe_msg} |")

        lines.append("")

    return "\n".join(lines).strip()


def _unquoted(message: str) -> str:
    """Drop the quotes a YAML `message:` scalar carries, if it has a matching pair.

    The rule files quote their messages; a docs table reading `"Bare except: ..."`
    with the quotes still on looks like the quotes are part of the message."""
    text = message.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text
