"""
evals/test_scorer.py -- pytest suite for the deterministic scorer.

Run:
    pytest evals/test_scorer.py -v
"""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from scorer import (
    score_case,
    _commands_equivalent,
    _extract_flag_values,
    _has_flag,
    _is_runnable_command,
    _normalise_flag_values,
    _tokens,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_case(
    surface="skill_md",
    route="sniff",
    acceptable_actions=None,
    acceptable_routes=None,
    forbidden_flags=None,
    detector_names_exact=False,
    requires_dir=False,
    efficiency="full",
    scoring_categories=None,
):
    """Build a minimal case dict for testing."""
    expected = {
        "route": route,
        "acceptable_actions": acceptable_actions,
        "forbidden_flags": forbidden_flags or ["--all"],
        "detector_names_exact": detector_names_exact,
        "requires_dir": requires_dir,
        "efficiency": efficiency,
    }
    if acceptable_routes is not None:
        expected["acceptable_routes"] = acceptable_routes
    return {
        "id": "test-case",
        "surface": surface,
        "prompt": "test prompt",
        "expected": expected,
        "scoring_categories": scoring_categories or [
            "routing", "efficiency", "anti_hallucination", "real_agent_behavior"
        ],
    }


def passes(case, actual):
    return score_case(case, actual)["overall"] == "PASS"


def fails(case, actual):
    return score_case(case, actual)["overall"] == "FAIL"


def notes(case, actual):
    return score_case(case, actual)["notes"]


# ---------------------------------------------------------------------------
# _commands_equivalent
# ---------------------------------------------------------------------------

class TestCommandsEquivalent:
    def test_identical(self):
        assert _commands_equivalent("sniff", "sniff")

    def test_extra_whitespace(self):
        assert _commands_equivalent("sniff  --only  largest-files", "sniff --only largest-files")

    def test_quoting(self):
        assert _commands_equivalent('sniff --only "largest-files"', "sniff --only largest-files")

    def test_detector_order_space_form(self):
        # a,b and b,a must be equivalent
        assert _commands_equivalent(
            "sniff --only cyclomatic-complexity,no-duplicate-string",
            "sniff --only no-duplicate-string,cyclomatic-complexity",
        )

    def test_detector_order_equals_form(self):
        assert _commands_equivalent(
            "sniff --only=cyclomatic-complexity,no-duplicate-string",
            "sniff --only=no-duplicate-string,cyclomatic-complexity",
        )

    def test_different_commands_not_equal(self):
        assert not _commands_equivalent("sniff", "sniff --only largest-files")

    def test_all_alias_equals_bare_sniff(self):
        # --all is a no-op alias; must be equivalent to bare sniff
        assert _commands_equivalent("sniff --all", "sniff")
        assert _commands_equivalent("sniff --all .", "sniff")

    def test_skip_order(self):
        assert _commands_equivalent(
            "sniff --skip a,b", "sniff --skip b,a"
        )


# ---------------------------------------------------------------------------
# _extract_flag_values
# ---------------------------------------------------------------------------

class TestExtractFlagValues:
    def test_space_form_single(self):
        assert _extract_flag_values("sniff --only largest-files", "--only") == ["largest-files"]

    def test_space_form_multi(self):
        assert sorted(_extract_flag_values("sniff --only a,b,c", "--only")) == ["a", "b", "c"]

    def test_equals_form(self):
        assert sorted(_extract_flag_values("sniff --only=a,b", "--only")) == ["a", "b"]

    def test_absent_flag(self):
        assert _extract_flag_values("sniff", "--only") == []


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

class TestRouting:
    def test_exact_match(self):
        case = make_case(route="sniff")
        assert passes(case, "sniff")

    def test_wrong_command(self):
        case = make_case(route="sniff")
        assert fails(case, "sniff --only largest-files")

    def test_acceptable_routes_first(self):
        case = make_case(
            route=None,
            acceptable_routes=[
                "sniff --only cyclomatic-complexity,no-duplicate-string",
                "sniff --only cognitive-complexity,no-duplicate-string",
            ],
            efficiency="single",
        )
        assert passes(case, "sniff --only no-duplicate-string,cyclomatic-complexity")

    def test_acceptable_routes_second(self):
        case = make_case(
            route=None,
            acceptable_routes=[
                "sniff --only cyclomatic-complexity,no-duplicate-string",
                "sniff --only cognitive-complexity,no-duplicate-string",
            ],
            efficiency="single",
        )
        assert passes(case, "sniff --only cognitive-complexity,no-duplicate-string")

    def test_acceptable_routes_miss(self):
        case = make_case(
            route=None,
            acceptable_routes=["sniff --only cyclomatic-complexity,no-duplicate-string"],
            efficiency="single",
        )
        assert fails(case, "sniff --only largest-files")

    def test_discovery_surface_acceptable_action(self):
        case = make_case(
            surface="discovery",
            route=None,
            acceptable_actions=["sniff --list", "sniff --help"],
        )
        assert passes(case, "sniff --list")

    def test_discovery_surface_wrong_action(self):
        case = make_case(
            surface="discovery",
            route=None,
            acceptable_actions=["sniff --list", "sniff --help"],
        )
        assert fails(case, "sniff --only largest-files")


# ---------------------------------------------------------------------------
# Anti-hallucination
# ---------------------------------------------------------------------------

class TestAntiHallucination:
    def test_forbidden_flag_fails(self):
        case = make_case(route="sniff", forbidden_flags=["--all"])
        assert fails(case, "sniff --all")
        assert "--all" in notes(case, "sniff --all")[0]

    def test_no_forbidden_flag_passes(self):
        case = make_case(route="sniff")
        assert passes(case, "sniff")

    def test_unknown_detector_fails(self):
        case = make_case(
            route="sniff --only complexity-score",
            detector_names_exact=True,
            efficiency="single",
        )
        assert fails(case, "sniff --only complexity-score")

    def test_known_detector_passes(self):
        case = make_case(
            route="sniff --only cyclomatic-complexity",
            detector_names_exact=True,
            efficiency="single",
        )
        assert passes(case, "sniff --only cyclomatic-complexity")


# ---------------------------------------------------------------------------
# Efficiency
# ---------------------------------------------------------------------------

class TestEfficiency:
    def test_single_requires_only(self):
        case = make_case(route="sniff --only largest-files", efficiency="single")
        assert passes(case, "sniff --only largest-files")

    def test_single_fails_without_only(self):
        case = make_case(route="sniff", efficiency="single")
        result = score_case(case, "sniff")
        assert result["scores"]["efficiency"] == "FAIL"

    def test_full_forbids_only(self):
        case = make_case(route="sniff", efficiency="full")
        result = score_case(case, "sniff --only largest-files")
        assert result["scores"]["efficiency"] == "FAIL"

    def test_full_passes_plain_sniff(self):
        case = make_case(route="sniff", efficiency="full")
        assert passes(case, "sniff")

    def test_discovery_efficiency_always_passes(self):
        case = make_case(
            surface="discovery",
            route=None,
            acceptable_actions=["sniff --list"],
            efficiency="discovery",
        )
        result = score_case(case, "sniff --list")
        assert result["scores"]["efficiency"] == "PASS"


# ---------------------------------------------------------------------------
# Real-agent behavior
# ---------------------------------------------------------------------------

class TestRealAgentBehavior:
    def test_runnable_command_passes(self):
        case = make_case(route="sniff")
        result = score_case(case, "sniff")
        assert result["scores"]["real_agent_behavior"] == "PASS"

    def test_prose_fails(self):
        case = make_case(route="sniff")
        result = score_case(case, "You should run the sniff command to scan your repo.")
        assert result["scores"]["real_agent_behavior"] == "FAIL"

    def test_multiline_fails(self):
        case = make_case(route="sniff")
        result = score_case(case, "sniff\nsniff --list")
        assert result["scores"]["real_agent_behavior"] == "FAIL"

    def test_discovery_explore_passes(self):
        case = make_case(
            surface="discovery",
            route=None,
            acceptable_actions=["sniff --list"],
            efficiency="discovery",
        )
        result = score_case(case, "sniff --list")
        assert result["scores"]["real_agent_behavior"] == "PASS"

    def test_discovery_no_explore_fails(self):
        case = make_case(
            surface="discovery",
            route=None,
            acceptable_actions=["sniff --list", "sniff --help"],
            efficiency="discovery",
        )
        result = score_case(case, "sniff --only cyclomatic-complexity")
        assert result["scores"]["real_agent_behavior"] == "FAIL"


# ---------------------------------------------------------------------------
# Cases from cases.jsonl (regression)
# ---------------------------------------------------------------------------

CASES_FILE = Path(__file__).parent / "cases.jsonl"

def _load_cases():
    if not CASES_FILE.exists():
        return {}
    return {
        json.loads(l)["id"]: json.loads(l)
        for l in CASES_FILE.read_text(encoding="utf-8").splitlines()
        if l.strip()
    }


CASES = _load_cases()


@pytest.mark.parametrize("case_id,actual,expect_pass", [
    # Full scan: plain sniff must pass
    ("case-006", "sniff", True),
    # --all is valid alias for sniff: must pass
    ("case-010", "sniff --all", True),
    # Single detector: must use --only
    ("case-007", "sniff --only cyclomatic-complexity", True),
    ("case-007", "sniff", False),  # full scan for single-detector ask fails efficiency
    # case-027: either complexity detector acceptable
    ("case-027", "sniff --only no-duplicate-string,cyclomatic-complexity", True),
    ("case-027", "sniff --only cognitive-complexity,no-duplicate-string", True),
    ("case-027", "sniff --only no-duplicate-string,complexity-score", False),  # hallucinated
    # case-028: largest-methods + large-classes, order-invariant
    ("case-028", "sniff --only largest-methods,large-classes", True),
    ("case-028", "sniff --only large-classes,largest-methods", True),
    # Broad asks (025, 026): full scan expected
    ("case-025", "sniff", True),
    ("case-025", "sniff --only largest-files", False),  # too narrow for broad ask
    ("case-026", "sniff", True),
])
def test_cases_jsonl_regression(case_id, actual, expect_pass):
    if case_id not in CASES:
        pytest.skip(f"{case_id} not in cases.jsonl")
    result = score_case(CASES[case_id], actual)
    assert (result["overall"] == "PASS") == expect_pass, (
        f"{case_id} actual={actual!r} expected_pass={expect_pass} "
        f"got={result['overall']} notes={result['notes']}"
    )
