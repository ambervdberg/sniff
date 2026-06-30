"""
evals/smoke/test_smoke.py -- the real-agent smoke set stays wired to cases.jsonl
and the verification snapshot keeps scoring clean.

Run:
    pytest evals/smoke/test_smoke.py -v
"""

import json
from pathlib import Path

_HERE = Path(__file__).parent
_EVALS_DIR = _HERE.parent
_SMOKE_SET = _HERE / "smoke_set.json"
_CASES_FILE = _EVALS_DIR / "cases.jsonl"
_VERIFICATION_RESULTS = _HERE / "verification.jsonl"


def _load_case_ids() -> set[str]:
    ids = set()
    with _CASES_FILE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                ids.add(json.loads(line)["id"])
    return ids


def test_smoke_set_has_five_to_ten_ids():
    ids = json.loads(_SMOKE_SET.read_text(encoding="utf-8"))
    assert 5 <= len(ids) <= 10


def test_smoke_set_ids_all_exist_in_cases_jsonl():
    smoke_ids = json.loads(_SMOKE_SET.read_text(encoding="utf-8"))
    known_ids = _load_case_ids()
    missing = [i for i in smoke_ids if i not in known_ids]
    assert not missing, f"smoke_set.json references unknown case ids: {missing}"


def test_verification_run_covers_every_smoke_id():
    smoke_ids = set(json.loads(_SMOKE_SET.read_text(encoding="utf-8")))
    result_ids = set()
    with _VERIFICATION_RESULTS.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                result_ids.add(json.loads(line)["id"])
    assert result_ids == smoke_ids
