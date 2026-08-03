"""
evals/scorer.py -- Deterministic scorer for the sniff LLM eval harness.

Takes a case (from cases.jsonl) and the model's actual shell command output,
returns a structured PASS/FAIL result across four scoring dimensions.

No API calls. No external deps. Python 3.9+, stdlib only.

Usage:
    # Score a single case:
    python evals/scorer.py --case '<case_json>' --actual 'sniff --only cyclomatic-complexity src/'

    # Score a batch (results JSONL matched against cases.jsonl):
    python evals/scorer.py --results results.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Known detector names -- exact, case-sensitive.
# Any --only/--skip value not in this set is a hallucinated detector name.
# ---------------------------------------------------------------------------
KNOWN_DETECTORS: frozenset[str] = frozenset(
    [
        "largest-files",
        "largest-methods",
        "large-classes",
        "cyclomatic-complexity",
        "cognitive-complexity",
        "deepest-nesting",
        "most-parameters",
        "most-imports",
        "no-duplicate-string",
        "duplicate-code",
        "sniff-patterns",
        "large-inline-templates",
    ]
)

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def _normalise_command(cmd: str) -> str:
    """Collapse runs of whitespace; strip leading/trailing space.

    We intentionally do NOT normalise quoting differences here because the
    routing check compares token-by-token (see _commands_equivalent), so
    quoting only matters there where we strip quotes from individual tokens.
    """
    return re.sub(r"\s+", " ", cmd.strip())


def _tokens(cmd: str) -> list[str]:
    """Split a shell command into tokens, stripping surrounding quotes from each."""
    raw = _normalise_command(cmd).split()
    return [t.strip("\"'") for t in raw]


def _normalise_flag_values(tokens: list[str]) -> list[str]:
    """Normalise tokens for semantic comparison.

    Two normalisation steps:
    1. Sort comma-separated detector lists in --only/--skip so a,b == b,a.
    2. Drop a trailing positional `.` (current directory) — `sniff .` and
       `sniff` are equivalent because `.` is the default scan path.
    """
    result: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # --all is a no-op alias for bare sniff; drop it so sniff --all == sniff.
        if tok == "--all":
            i += 1
        # Space form: --only <values>  ->  consume next token too.
        elif tok in ("--only", "--skip") and i + 1 < len(tokens):
            result.append(tok)
            values = sorted(tokens[i + 1].split(","))
            result.append(",".join(values))
            i += 2
        # Equals form: --only=<values>
        elif tok.startswith("--only=") or tok.startswith("--skip="):
            flag, _, raw = tok.partition("=")
            values = sorted(raw.split(","))
            result.append(f"{flag}={','.join(values)}")
            i += 1
        else:
            result.append(tok)
            i += 1

    # Drop a lone trailing "." — it means current directory, same as no DIR.
    if result and result[-1] == ".":
        result = result[:-1]

    # Strip trailing "/" from path tokens — `src/` and `src` are equivalent.
    result = [t.rstrip("/") if not t.startswith("-") else t for t in result]

    return result


def _commands_equivalent(a: str, b: str) -> bool:
    """Return True when two commands are semantically equivalent after normalisation.

    Handles:
    - extra whitespace
    - equivalent single vs double quoting around individual tokens
    - detector-list ordering in --only/--skip (a,b == b,a)
    """
    return _normalise_flag_values(_tokens(a)) == _normalise_flag_values(_tokens(b))


def _is_runnable_command(cmd: str) -> bool:
    """Heuristic: reject pure prose.

    A runnable shell command must start with a word that looks like a
    program/script name (no spaces before, no sentence-ending punctuation).
    We also reject strings that contain no whitespace-free leading token
    starting with a letter/digit/dot/slash.
    """
    stripped = cmd.strip()
    if not stripped:
        return False
    # If the string contains a newline it's probably prose / multi-line output
    if "\n" in stripped:
        return False
    first_token = stripped.split()[0]
    # Prose sentences start with an uppercase letter; shell commands don't.
    if first_token[0].isupper():
        return False
    # Accept if the first token looks like a CLI program name or path.
    return bool(re.match(r"^[\w./\\-]+$", first_token))


def _extract_flag_values(cmd: str, flag: str) -> list[str]:
    """Return values passed to *flag* in *cmd*.

    Handles both:
      --only foo          (space-separated)
      --only=foo          (equals-separated)
    and comma-separated lists:
      --only foo,bar
      --only=foo,bar
    """
    tokens = _tokens(cmd)
    values: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == flag and i + 1 < len(tokens):
            # --only foo  or  --only foo,bar
            values.extend(tokens[i + 1].split(","))
            i += 2
        elif tok.startswith(flag + "="):
            # --only=foo  or  --only=foo,bar
            values.extend(tok[len(flag) + 1 :].split(","))
            i += 1
        else:
            i += 1
    return [v.strip() for v in values if v.strip()]


def _has_flag(cmd: str, flag: str) -> bool:
    """Return True if *flag* (e.g. '--only') appears in *cmd*."""
    tokens = _tokens(cmd)
    return any(t == flag or t.startswith(flag + "=") for t in tokens)


# ---------------------------------------------------------------------------
# Scoring dimensions
# ---------------------------------------------------------------------------


def score_routing(case: dict[str, Any], actual: str) -> tuple[str, str | None]:
    """Dimension 1 -- routing.

    For non-discovery surfaces (or discovery with a non-null route):
      Does the actual command match expected.route?

    For discovery surface with null route:
      Does the actual command appear in acceptable_actions?

    Returns (verdict, note_or_None).
    """
    expected = case.get("expected", {})
    route = expected.get("route")
    surface = case.get("surface", "")
    acceptable = expected.get("acceptable_actions", [])

    if surface == "discovery" and route is None:
        # Discovery surface: any acceptable action counts as a correct route.
        for action in acceptable:
            if _commands_equivalent(actual, action):
                return "PASS", None
        return (
            "FAIL",
            f"routing: command not in acceptable_actions {acceptable!r}",
        )

    # Non-discovery (or discovery with an explicit route): exact match required.
    # If neither route nor acceptable_routes is set, nothing to check.
    explicit_routes: list[str] | None = expected.get("acceptable_routes")
    if not explicit_routes and route is None:
        return "PASS", None

    # acceptable_routes wins when set; otherwise fall back to the single route.
    candidates: list[str] = explicit_routes if explicit_routes else [route]  # type: ignore[list-item]

    for candidate in candidates:
        if _commands_equivalent(actual, candidate):
            return "PASS", None

    return "FAIL", f"routing: expected one of {candidates!r}, got {actual!r}"


def score_anti_hallucination(
    case: dict[str, Any], actual: str
) -> tuple[str, str | None]:
    """Dimension 2 -- anti-hallucination.

    Two sub-checks; either failure causes FAIL:
      a) forbidden_flags: the actual command must not contain any listed flag.
      b) detector_names_exact: if True, every value passed to --only or --skip
         must be a known detector name.
    """
    expected = case.get("expected", {})
    forbidden_flags: list[str] = expected.get("forbidden_flags", [])
    detector_names_exact: bool = expected.get("detector_names_exact", False)

    # (a) Forbidden-flag check.
    for flag in forbidden_flags:
        if _has_flag(actual, flag):
            return "FAIL", f"anti_hallucination: forbidden flag {flag!r} present"

    # (b) Detector-name validation when exact names are required.
    if detector_names_exact:
        for flag in ("--only", "--skip"):
            values = _extract_flag_values(actual, flag)
            for name in values:
                if name not in KNOWN_DETECTORS:
                    return (
                        "FAIL",
                        f"anti_hallucination: unknown detector {name!r} in {flag}",
                    )

    return "PASS", None


_EXPLORATION_COMMANDS: frozenset[str] = frozenset(
    ["sniff --list", "sniff --help", "sniff --list-patterns", "sniff -h"]
)


def score_efficiency(case: dict[str, Any], actual: str) -> tuple[str, str | None]:
    """Dimension 3 -- efficiency.

    "single"    -> must use --only (targeted scan, not full run)
    "full"      -> must NOT use --only (full scan requested)
    "discovery" -> any acceptable action passes (no --only constraint)

    Exploration commands (sniff --list, sniff --help, sniff --list-patterns)
    are never an efficiency violation — the model chose to explore rather than
    run the wrong scan width, so efficiency is not the right signal to fail.
    """
    expected = case.get("expected", {})
    efficiency = expected.get("efficiency", "")

    # Exploration is neutral on efficiency — not wrong, just an extra step.
    normalised = _normalise_command(actual)
    if normalised in _EXPLORATION_COMMANDS:
        return "PASS", None

    if efficiency == "single":
        if _has_flag(actual, "--only"):
            return "PASS", None
        return "FAIL", "efficiency: expected --only for single-detector run"

    if efficiency == "full":
        if not _has_flag(actual, "--only"):
            return "PASS", None
        return "FAIL", "efficiency: --only should not be used for a full scan"

    if efficiency == "discovery":
        # Any action is acceptable from an efficiency standpoint.
        return "PASS", None

    # Unknown/missing efficiency value -- treat as not applicable.
    return "PASS", None


def score_real_agent_behavior(
    case: dict[str, Any], actual: str
) -> tuple[str, str | None]:
    """Dimension 4 -- real agent behaviour.

    For discovery surface:
      The model must explore before committing, i.e. it should produce one of
      the acceptable_actions (e.g. sniff --list or sniff --help) rather than
      guessing a specific smell command cold.

    For non-discovery surface:
      The model must produce a runnable shell command, not prose.
    """
    surface = case.get("surface", "")
    expected = case.get("expected", {})
    acceptable = expected.get("acceptable_actions", [])

    if surface == "discovery":
        # Check the model explored rather than guessing.
        for action in acceptable:
            if _commands_equivalent(actual, action):
                return "PASS", None
        return (
            "FAIL",
            "real_agent_behavior: discovery surface -- model should explore first "
            f"(acceptable_actions={acceptable!r})",
        )

    # Non-discovery: must look like a shell command, not prose.
    if _is_runnable_command(actual):
        return "PASS", None

    return "FAIL", "real_agent_behavior: output looks like prose, not a shell command"


# ---------------------------------------------------------------------------
# Per-case scoring
# ---------------------------------------------------------------------------

# Map dimension name -> scoring function.
_SCORERS = {
    "routing": score_routing,
    "anti_hallucination": score_anti_hallucination,
    "efficiency": score_efficiency,
    "real_agent_behavior": score_real_agent_behavior,
}


def score_case(case: dict[str, Any], actual: str) -> dict[str, Any]:
    """Score *actual* against *case* and return the result dict."""
    # Only score the categories listed in the case; default to all four.
    categories: list[str] = case.get(
        "scoring_categories",
        list(_SCORERS.keys()),
    )

    scores: dict[str, str] = {}
    notes: list[str] = []

    for cat in categories:
        fn = _SCORERS.get(cat)
        if fn is None:
            # Unknown category -- skip gracefully.
            continue
        verdict, note = fn(case, actual)
        scores[cat] = verdict
        if note:
            notes.append(note)

    overall = "PASS" if all(v == "PASS" for v in scores.values()) else "FAIL"

    return {
        "id": case.get("id", ""),
        "actual": actual,
        "scores": scores,
        "overall": overall,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# Batch mode: load cases.jsonl, match with results JSONL, print summary
# ---------------------------------------------------------------------------

# Default location of the cases file, relative to this script's directory.
_DEFAULT_CASES_FILE = Path(__file__).parent / "cases.jsonl"


def _load_cases(cases_file: Path) -> dict[str, dict[str, Any]]:
    """Return a dict mapping case id -> case dict."""
    cases: dict[str, dict[str, Any]] = {}
    with cases_file.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    f"WARNING: cases.jsonl line {lineno} is not valid JSON: {exc}",
                    file=sys.stderr,
                )
                continue
            case_id = obj.get("id")
            if not case_id:
                print(
                    f"WARNING: cases.jsonl line {lineno} missing 'id' field, skipping",
                    file=sys.stderr,
                )
                continue
            cases[case_id] = obj
    return cases


def run_batch(results_jsonl: str) -> None:
    """Read {id, actual} pairs from *results_jsonl*, score each, print summary."""
    cases = _load_cases(_DEFAULT_CASES_FILE)

    results: list[dict[str, Any]] = []
    with open(results_jsonl, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                print(
                    f"WARNING: results JSONL line {lineno} invalid JSON: {exc}",
                    file=sys.stderr,
                )
                continue
            case_id = obj.get("id")
            actual = obj.get("actual", "")
            if case_id not in cases:
                print(
                    f"WARNING: result id {case_id!r} not found in cases.jsonl, skipping",
                    file=sys.stderr,
                )
                continue
            result = score_case(cases[case_id], actual)
            results.append(result)

    # Aggregate summary.
    total = len(results)
    passed = sum(1 for r in results if r["overall"] == "PASS")
    failed = total - passed

    # Per-category counts -- initialise from the union of all categories seen.
    all_cats: set[str] = set()
    for r in results:
        all_cats.update(r["scores"].keys())

    by_category: dict[str, dict[str, int]] = {
        cat: {"pass": 0, "fail": 0} for cat in sorted(all_cats)
    }
    for r in results:
        for cat, verdict in r["scores"].items():
            if verdict == "PASS":
                by_category[cat]["pass"] += 1
            else:
                by_category[cat]["fail"] += 1

    failures = [r for r in results if r["overall"] == "FAIL"]

    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "by_category": by_category,
        "failures": failures,
    }
    print(json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic scorer for the sniff LLM eval harness."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--case",
        metavar="CASE_JSON",
        help="JSON string of a single case from cases.jsonl",
    )
    mode.add_argument(
        "--results",
        metavar="RESULTS_JSONL",
        help="Path to a JSONL file of {id, actual} pairs; prints aggregate summary",
    )
    parser.add_argument(
        "--actual",
        metavar="COMMAND",
        help="The model's actual shell command output (required with --case)",
    )
    args = parser.parse_args()

    if args.case is not None:
        # Single-case mode.
        if args.actual is None:
            parser.error("--actual is required when using --case")
        try:
            case = json.loads(args.case)
        except json.JSONDecodeError as exc:
            print(f"ERROR: --case value is not valid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        result = score_case(case, args.actual)
        print(json.dumps(result, indent=2))

    else:
        # Batch mode.
        if not Path(args.results).exists():
            print(f"ERROR: results file not found: {args.results}", file=sys.stderr)
            sys.exit(1)
        run_batch(args.results)


if __name__ == "__main__":
    main()
