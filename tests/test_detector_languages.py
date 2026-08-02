"""Every detector declares which languages it can read, and sniff acts on it.

The bug these guard against is silent: a detector with no rules for a language
scans it, matches nothing, and prints "no findings", which reads exactly like a
clean result. So the declaration has to exist, has to be true, and has to be what
both the CLI and the README use.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from sniff import discovery
from sniff import harness as h

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
SRC = os.path.join(REPO_ROOT, "src")
RUN = [sys.executable, "-m", "sniff.cli"]
SUBPROCESS_ENV = {**os.environ, "PYTHONPATH": SRC}

# The languages sniff promises every applicable detector covers.
FIRST_CLASS = {"typescript", "tsx", "javascript", "python"}

# Angular components only exist in TypeScript, so this detector is scoped by the
# ecosystem it checks, not by a gap in its rules.
ANGULAR_ONLY = "large-inline-templates"


def _run_cli(*args: str) -> str:
    proc = subprocess.run([*RUN, *args], capture_output=True, text=True, env=SUBPROCESS_ENV)
    return proc.stdout


def test_every_builtin_declares_its_languages():
    detectors, _ = discovery.discover()
    for d in detectors:
        assert d.languages, f"{d.name} declares no languages"


def test_first_class_languages_are_covered_everywhere():
    """TS/TSX/JS and Python are the support promise; only Angular is exempt."""
    detectors, _ = discovery.discover()
    for d in detectors:
        if d.name in {ANGULAR_ONLY, "sniff-patterns"}:
            continue
        missing = FIRST_CLASS - set(d.languages)
        assert not missing, f"{d.name} does not cover {sorted(missing)}"


def test_large_classes_covers_python(tmp_path):
    """The regression that started this: scrapy reported zero classes."""
    (tmp_path / "mod.py").write_text("class Alpha:\n    x = 1\n\n\nclass Beta:\n    y = 2\n",
                                     encoding="utf-8")
    h.reset_git_ignore_cache()

    out = _run_cli("--only", "large-classes", str(tmp_path))

    assert "Alpha" in out and "Beta" in out, out


def test_most_imports_covers_python(tmp_path):
    """Python spells `from x import y` as its own node kind; both must count."""
    (tmp_path / "mod.py").write_text("import os\nfrom collections import deque\n", encoding="utf-8")
    h.reset_git_ignore_cache()

    out = _run_cli("--only", "most-imports", str(tmp_path))

    assert re.search(r"\b2\s+mod\.py|mod\.py", out), out
    assert "No import statements found" not in out


def test_detector_named_in_only_explains_itself_instead_of_reporting_zero(tmp_path):
    """`--only` on an unsupported language must not look like a clean result."""
    (tmp_path / "main.go").write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    h.reset_git_ignore_cache()

    out = _run_cli("--only", "most-imports", str(tmp_path))

    assert "Not applicable" in out, out
    assert "go" in out


def test_scan_skips_detectors_that_cannot_read_the_repo(tmp_path):
    """No `--only`: an inapplicable detector is dropped, not printed empty."""
    (tmp_path / "main.go").write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    h.reset_git_ignore_cache()

    out = _run_cli(str(tmp_path))

    assert "## most-imports" not in out
    assert f"## {ANGULAR_ONLY}" not in out
    assert "## largest-files" in out


def test_json_scan_also_omits_skipped_detectors(tmp_path):
    (tmp_path / "main.go").write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    h.reset_git_ignore_cache()

    import json
    payload = json.loads(_run_cli("--json", str(tmp_path)))

    names = {d["detector"] for d in payload["detectors"]}
    assert "most-imports" not in names
    assert "largest-files" in names


def _write_multi_language_sources(tmp_path):
    """The same smell in .ts, .tsx and .js, plus one that only .tsx can hold."""
    (tmp_path / "main.ts").write_text('console.log("ts");\n', encoding="utf-8")
    (tmp_path / "App.tsx").write_text(
        'const x: any = 1;\nconsole.log("tsx");\n', encoding="utf-8")
    (tmp_path / "plain.js").write_text('console.log("js");\n', encoding="utf-8")
    h.reset_git_ignore_cache()


def test_pattern_rules_run_on_tsx_and_javascript(tmp_path):
    """A rule declaring extra languages must fire in all of them, not just .ts."""
    _write_multi_language_sources(tmp_path)

    out = _run_cli("--only", "sniff-patterns", str(tmp_path))

    assert "main.ts:1" in out, out
    assert "App.tsx:2" in out, out
    assert "plain.js:1" in out, out


def test_expanded_rule_ids_never_reach_the_output(tmp_path):
    """Each language needs its own rule id internally; the user sees one id."""
    _write_multi_language_sources(tmp_path)

    out = _run_cli("--only", "sniff-patterns", str(tmp_path))

    assert "--lang-" not in out, out
    assert "no-console-log" in out


def test_typescript_only_rule_does_not_run_on_javascript(tmp_path):
    """`: any` is not JavaScript syntax, so that rule stays off .js files."""
    (tmp_path / "typed.tsx").write_text("const x: any = 1;\n", encoding="utf-8")
    (tmp_path / "plain.js").write_text("const y = 1;\n", encoding="utf-8")
    h.reset_git_ignore_cache()

    out = _run_cli("--only", "sniff-patterns", str(tmp_path))

    assert "typed.tsx" in out, out
    assert "plain.js" not in out, out


def test_sniff_patterns_language_list_grows_with_local_rules(tmp_path):
    """Coverage is read from the catalog, so a repo's own rule counts."""
    rules = tmp_path / ".sniff" / "rules"
    rules.mkdir(parents=True)
    (rules / "go_rule.yml").write_text(
        "id: local-go-rule\nlanguage: go\nseverity: warning\n"
        "message: local\nrule:\n  pattern: panic($$$A)\n", encoding="utf-8")

    detectors, _ = discovery.discover(str(tmp_path))
    patterns = next(d for d in detectors if d.name == "sniff-patterns")

    assert "go" in patterns.languages


REGENERATE = "run `python scripts/update_docs.py`"


def test_readme_pattern_catalog_matches_the_rules():
    """Same reason as the matrix: a stale rule list sends readers after rule ids
    that no longer exist, or hides ones that do."""
    from sniff.patterns import format as fmt

    block = _readme_block("pattern-catalog")
    assert block == fmt.render_catalog_table(fmt.catalog_rules()).strip(), REGENERATE


def test_readme_matrix_matches_the_detectors():
    """A hand-edited matrix would claim support the code does not have."""
    detectors, _ = discovery.discover()
    matrix = discovery.render_language_matrix(detectors).strip()
    assert _readme_block("language-matrix") == matrix, REGENERATE


def test_update_docs_script_agrees_with_these_tests():
    """The script must produce exactly what the drift tests demand.

    Without this, the two could disagree and leave the suite red no matter how
    many times someone runs the fix it tells them to run."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import update_docs

    assert update_docs.main(["--check"]) == 0, REGENERATE


def _readme_block(marker: str) -> str:
    """The generated section between `<!-- marker:start -->` and its end marker."""
    with open(os.path.join(REPO_ROOT, "README.md"), "r", encoding="utf-8") as fh:
        content = fh.read()

    found = re.search(rf"<!-- {marker}:start -->\n(.*?)<!-- {marker}:end -->", content, re.DOTALL)
    assert found, f"README is missing the {marker} markers"
    return found.group(1).strip()
