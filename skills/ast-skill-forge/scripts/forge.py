#!/usr/bin/env python3
"""Scaffold a new ast-search skill, or a new ast-lint rule, from resolved inputs.

This is the mechanical half of ast-skill-forge. The conversational half (gather
intent, draft the ast-grep rule, validate it on the current repo) lives in the
forge SKILL.md and is driven by the agent. Once the rule is confirmed, the agent
calls this script to write the files.

Two modes:

    forge.py standalone --name large-classes --noun classes \\
        --title "Largest classes by line count" \\
        --description "Find the largest classes ... returns a small ranked table." \\
        --langs typescript,tsx --kinds class_declaration

    forge.py standalone --name big-switches --noun "switch statements" \\
        --title "Largest switch statements" --description "..." \\
        --langs typescript --pattern 'switch ($X) { $$$ }'

    forge.py rule --name no-nested-ternary --language typescript \\
        --severity warning --message "Nested ternary; extract for readability." \\
        --title "Nested ternary expressions" \\
        --pattern '$A ? $B : ($C ? $D : $E)'

Use --dry-run to print what would be written without touching disk.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

# Resolve repo paths relative to this file: scripts/ -> ast-skill-forge/ -> skills/ -> repo.
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "..", "templates")
SKILLS_DIR = os.path.normpath(os.path.join(HERE, "..", ".."))
RULES_DIR = os.path.join(SKILLS_DIR, "ast-lint", "rules")


def _load_template(name: str) -> str:
    with open(os.path.join(TEMPLATES, name), "r", encoding="utf-8") as fh:
        return fh.read()


def _fill(template: str, tokens: dict) -> str:
    """Substitute every @@TOKEN@@ placeholder. Fails loudly on any left behind."""
    out = template
    for key, value in tokens.items():
        out = out.replace(f"@@{key}@@", value)

    leftover = [seg.split("@@")[0] for seg in out.split("@@")[1::2]]
    if leftover:
        sys.exit(f"error: template still has unfilled placeholders: {sorted(set(leftover))}")
    return out


def _write(path: str, content: str, dry_run: bool) -> None:
    if dry_run:
        print(f"--- would write {path} ---\n{content}")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    print(f"wrote {path}")


def _rule_literal(langs: list[str], kinds: "list[str] | None", pattern: "str | None") -> tuple[str, str]:
    """Return (python_literal_for_RULE, human_match_summary)."""
    if pattern is not None:
        return json.dumps(pattern), f"ast-grep pattern {pattern!r}"

    # kinds map: every language gets the same node kinds.
    rule_map = {lang: kinds for lang in langs}
    summary = f"node kinds {kinds} in {', '.join(langs)}"
    return repr(rule_map), summary


def cmd_standalone(args: argparse.Namespace) -> None:
    if not args.kinds and not args.pattern:
        sys.exit("error: provide either --kinds or --pattern")
    if args.kinds and args.pattern:
        sys.exit("error: --kinds and --pattern are mutually exclusive")

    langs = [s.strip() for s in args.langs.split(",") if s.strip()]
    kinds = [s.strip() for s in args.kinds.split(",") if s.strip()] if args.kinds else None
    rule_literal, match_summary = _rule_literal(langs, kinds, args.pattern)

    common = {
        "NAME": args.name,
        "TITLE": args.title,
        "DESCRIPTION": args.description,
        "ONE_LINE": args.one_line or args.title,
        "NOUN": args.noun,
        "LANGS": ", ".join(langs),
        "MATCH_SUMMARY": match_summary,
        "RULE_LITERAL": rule_literal,
    }

    skill_dir = os.path.join(SKILLS_DIR, args.name)
    _write(os.path.join(skill_dir, "SKILL.md"),
           _fill(_load_template("standalone_SKILL.md.tmpl"), common), args.dry_run)
    _write(os.path.join(skill_dir, "scripts", f"{args.name}.py"),
           _fill(_load_template("standalone_script.py.tmpl"), common), args.dry_run)

    if not args.dry_run:
        print(f"\nNext: validate it, then make it live.\n"
              f"  python \"{skill_dir}/scripts/{args.name}.py\" <some-repo> --top 10\n"
              f"  git -C \"{SKILLS_DIR}/..\" add skills/{args.name} && git commit -m \"feat: add {args.name} skill\"\n"
              f"  /plugin update ast-skills   (to make the new skill live on this PC)")


def cmd_rule(args: argparse.Namespace) -> None:
    if not args.pattern and not args.rule_body_file:
        sys.exit("error: provide either --pattern or --rule-body-file")

    if args.pattern:
        rule_body = f"  pattern: {json.dumps(args.pattern)}"
    else:
        with open(args.rule_body_file, "r", encoding="utf-8") as fh:
            # Indent each line by two spaces to sit under `rule:`.
            rule_body = "\n".join("  " + line.rstrip("\n") for line in fh)

    tokens = {
        "NAME": args.name,
        "TITLE": args.title,
        "LANGUAGE": args.language,
        "SEVERITY": args.severity,
        "MESSAGE": json.dumps(args.message),
        "RULE_BODY": rule_body,
    }

    _write(os.path.join(RULES_DIR, f"{args.name}.yml"),
           _fill(_load_template("rule.yml.tmpl"), tokens), args.dry_run)

    if not args.dry_run:
        print("\nNext: run the ast-lint skill to see it in the catalog scan.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scaffold an ast-search skill or an ast-lint rule.")
    parser.add_argument("--dry-run", action="store_true", help="print what would be written, touch nothing")
    sub = parser.add_subparsers(dest="mode", required=True)

    s = sub.add_parser("standalone", help="scaffold a standalone search skill")
    s.add_argument("--name", required=True, help="kebab-case skill name (also the dir + script name)")
    s.add_argument("--title", required=True, help="one-line human title")
    s.add_argument("--description", required=True, help="skill description (drives triggering)")
    s.add_argument("--one-line", help="one-line summary under the heading (defaults to title)")
    s.add_argument("--noun", required=True, help="plural noun for the header, e.g. 'classes'")
    s.add_argument("--langs", required=True, help="comma-separated ast-grep language ids")
    s.add_argument("--kinds", help="comma-separated tree-sitter node kinds (applied to every --lang)")
    s.add_argument("--pattern", help="ast-grep pattern string (alternative to --kinds)")
    s.set_defaults(func=cmd_standalone)

    r = sub.add_parser("rule", help="scaffold an ast-lint catalog rule")
    r.add_argument("--name", required=True, help="kebab-case rule id (also the file name)")
    r.add_argument("--title", required=True, help="one-line human title (comment header)")
    r.add_argument("--language", required=True, help="ast-grep language id")
    r.add_argument("--severity", default="warning", help="error|warning|info|hint (default warning)")
    r.add_argument("--message", required=True, help="finding message shown to the user")
    r.add_argument("--pattern", help="ast-grep pattern string")
    r.add_argument("--rule-body-file", help="file with raw rule YAML body (alternative to --pattern)")
    r.set_defaults(func=cmd_rule)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
