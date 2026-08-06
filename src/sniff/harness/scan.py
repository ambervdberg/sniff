"""Running ast-grep and turning its JSON into Matches."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence

from sniff.harness.files import _in_ignored_dir, detect_languages, is_test_file
from sniff.harness.model import NAME_PATTERNS, Match, RuleSpec, _NAME_STOPWORDS

def find_ast_grep() -> str | None:
    """Resolve the ast-grep binary, falling back to the interpreter's own bin dir.

    `pip install ast-grep-cli` drops the `ast-grep` binary next to whatever
    interpreter ran the install, in the same directory as `python` itself
    (Scripts\\ on Windows, bin/ elsewhere). shutil.which only sees it there if
    that directory happens to be on PATH, which is not guaranteed: `uv tool
    install sniff-smells` shims only the `sniff` entry point onto PATH, and an
    agent invoking sniff by absolute path (e.g. a CI smoke test calling
    `/tmp/smoke/bin/sniff` directly) never puts its own venv's bin dir on PATH
    either. sys.executable is reliable in both cases, so check its sibling
    before giving up."""
    found = shutil.which("ast-grep")
    if found:
        return found
    exe_name = "ast-grep.exe" if os.name == "nt" else "ast-grep"
    sibling = os.path.join(os.path.dirname(sys.executable), exe_name)
    return sibling if os.path.isfile(sibling) else None


def ast_grep_exe() -> str:
    """Absolute path to ast-grep, resolving Windows .cmd/.exe shims; bare name if not found.

    Windows CreateProcess does not resolve the `.cmd` shim npm installs for a bare
    "ast-grep" argv[0], so passing the bare name to subprocess raises WinError 2.
    shutil.which does apply PATHEXT, so the resolved path works on every platform.
    find_ast_grep also catches the interpreter-sibling case pip installs use; the
    bare name is the last-resort fallback so a subprocess call still gets a name
    to fail on instead of a None."""
    return find_ast_grep() or "ast-grep"


def _require_ast_grep() -> None:
    """Fail fast with a clear message if the ast-grep binary is missing."""
    if find_ast_grep() is None:
        sys.exit("error: ast-grep is not installed or not on PATH. Install it with: pip install ast-grep-cli")


def _kinds_rule(lang: str, kinds: Sequence[str]) -> str:
    """Build an inline ast-grep rule matching any of the given node kinds."""
    any_block = "\n".join(f"    - kind: {k}" for k in kinds)
    return f"id: h\nlanguage: {lang}\nrule:\n  any:\n{any_block}"


def _pattern_rule(lang: str, pattern: str) -> str:
    """Build an inline ast-grep rule from a single pattern string."""
    return f"id: h\nlanguage: {lang}\nrule:\n  pattern: {json.dumps(pattern)}"


def _rule_for(spec: RuleSpec, lang: str) -> "str | None":
    """Resolve `rule_or_pattern` into a concrete inline rule YAML for one language.

    Returns None when the spec does not apply to this language (so the caller
    skips scanning it)."""
    if callable(spec):
        return spec(lang)

    if isinstance(spec, str):
        return _pattern_rule(lang, spec)

    # Mapping of language -> node kinds.
    kinds = spec.get(lang)
    if not kinds:
        return None
    return _kinds_rule(lang, list(kinds))


def _write_rule_file(rule_yaml: str) -> str:
    """Write a rule YAML to a temp file and return its forward-slashed path.

    The caller is responsible for deleting it (see `_scan`)."""
    tmp = tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8")
    try:
        tmp.write(rule_yaml)
    finally:
        tmp.close()
    return tmp.name.replace("\\", "/")


def _scan(root: str, lang: str, rule_yaml: str) -> list[dict]:
    """Run one rule over the tree and return ast-grep's raw match dicts.

    The rule goes to a temp file rather than `--inline-rules`: a rule YAML is
    multi-line, and when argv[0] is a Windows `.cmd` shim (how npm installs
    ast-grep, which is what CI uses) the command line is re-parsed by cmd.exe,
    which mangles embedded newlines and quotes. ast-grep then exits nonzero with
    "Cannot parse rule INLINE_RULES" and every detector silently reports nothing.
    A file path is a single plain token, so it survives any shim."""
    rule_file = _write_rule_file(rule_yaml)
    try:
        proc = subprocess.run(
            [ast_grep_exe(), "scan", "--rule", rule_file, "--json=compact", root],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        _require_ast_grep()
        return []
    finally:
        try:
            os.unlink(rule_file)
        except OSError:
            pass

    # Never crash on a failed scan (an empty result stays the fallback), but do not
    # hide it either: a silent miss looks exactly like "this repo is clean".
    if proc.returncode != 0:
        first = next((ln for ln in proc.stderr.splitlines() if ln.strip()), "")
        print(f"warning: ast-grep scan failed for {lang} (exit {proc.returncode}): {first}",
              file=sys.stderr)

    if not proc.stdout.strip():
        return []

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []


def _line_name(path: str, start_line: int) -> str:
    """Best-effort name by reading only the definition's first line from disk."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i == start_line:
                    text = line.strip()
                    break
            else:
                return "(anon)"
    except OSError:
        return "(anon)"

    for pat in NAME_PATTERNS:
        m = pat.search(text)
        if m and m.group(1) not in _NAME_STOPWORDS:
            return m.group(1)

    return "(anon)"


def _to_match(raw: dict, with_name: bool) -> Match:
    """Convert one ast-grep JSON match into a Match, resolving its name lazily."""
    rng = raw["range"]
    file = raw["file"]
    start_line = rng["start"]["line"]

    return Match(
        file=file.replace("\\", "/"),
        start_line=start_line,
        end_line=rng["end"]["line"],
        byte_start=rng["byteOffset"]["start"],
        byte_end=rng["byteOffset"]["end"],
        name=_line_name(file, start_line) if with_name else "(anon)",
        text=raw.get("text", ""),
    )


def run(
    rule_or_pattern: RuleSpec,
    path: str = ".",
    lang: "str | Sequence[str] | None" = None,
    include_tests: bool = False,
    with_name: bool = True,
    extra_ignores: "list[str] | None" = None,
) -> list[Match]:
    """Scan `path` for a structural pattern and return the matches.

    Languages are auto-detected from file extensions unless `lang` is given
    (a single id or a sequence). Test files are excluded unless `include_tests`.
    `extra_ignores`, when given, is the caller's parsed `--extra-ignore` globs and
    wins over SNIFF_EXTRA_IGNORE (see `_extra_ignore_patterns`). See module
    docstring for the three accepted shapes of `rule_or_pattern`."""
    _require_ast_grep()

    if lang is None:
        langs = detect_languages(path, extra_ignores)
    elif isinstance(lang, str):
        langs = {lang}
    else:
        langs = set(lang)

    if not langs:
        return []

    raw: list[dict] = []
    for one in sorted(langs):
        rule_yaml = _rule_for(rule_or_pattern, one)
        if rule_yaml is None:
            continue
        raw.extend(_scan(path, one, rule_yaml))

    # Drop vendored/build dirs explicitly: ast-grep only skips them when they are
    # gitignored, which is not guaranteed (e.g. a tree with no .gitignore).
    raw = [m for m in raw if not _in_ignored_dir(m["file"], path, extra_ignores)]

    if not include_tests:
        raw = [m for m in raw if not is_test_file(m["file"])]

    return [_to_match(m, with_name) for m in raw]
