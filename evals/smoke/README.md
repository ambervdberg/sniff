# Real-agent smoke process

`evals/runner.py` simulates an agent: one API call, synthetic system prompt,
JSON-only reply. It can't catch everything a real Claude Code / Codex session
does differently (multi-turn reasoning, actually reading SKILL.md, tool use).
This is the cheap real-agent complement: a handful of prompts run by hand in
an actual session, scored with the same `evals/scorer.py` the simulated
harness uses.

## Process

1. Pick the case ids in `smoke_set.json` (8 ids spanning discovery / full
   scan / single-detector / skip / help / list / open-ended surfaces — see
   `evals/cases.jsonl` for the full prompt text of each id).
2. Open a fresh Claude Code or Codex session in this repo (no prior sniff
   context loaded). For each prompt, paste it verbatim and record the first
   shell command the agent actually runs — not what it should run.
3. Append one line per case to a results file under `evals/smoke/results/<date>-<agent>.jsonl`
   (gitignored scratch space for ad-hoc runs):
   `{"id": "case-001", "actual": "sniff", "agent": "claude", "model": "claude-sonnet-5", "date": "2026-06-30"}`
4. Score it: `python evals/scorer.py --results evals/smoke/results/<file>.jsonl`
5. A routing or anti_hallucination FAIL here is a real regression signal
   (the simulated harness can pass while a real session fails, since it sees
   more context) — treat it as one and investigate before the prompt-sim
   numbers are trusted.

`verification.jsonl` (tracked, not gitignored) is the last run proving this
process actually works end-to-end — see `test_smoke.py`. Update it when the
CLI surface changes meaningfully; don't confuse it with scratch runs in
`results/`.

No markdown plan, no new scoring code — this reuses `cases.jsonl` and
`scorer.py` as-is. The only new thing is *how* `actual` gets filled in: a real
session instead of an API call.
