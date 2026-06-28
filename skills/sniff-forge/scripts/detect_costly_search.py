#!/usr/bin/env python3
"""Stop-hook detection heuristic: did this turn do a costly structural search?

Phase 4 of the suggest-forge hook. This module is the *detection* half only: it
decides whether the last turn looks like an expensive, repeatable structural
search that the agent should have turned into a forged skill. The nudge wording
and the off-switch live in a sibling task; here we only answer yes/no and expose
the signals behind that answer so the wiring layer can act on it.

The heuristic fires when BOTH hold for the most recent user turn:

  1. The turn made at least --min-calls (default 6) read/grep/glob tool calls.
  2. The user's prompt is structural: it pairs a lookup word
     (which / where / how many / largest / find all / list all) with a code
     noun (function / method / class / usage / ...).

Both thresholds are tunable via flags or the SNIFF_MIN_CALLS env var so a noisy
project can dial them up without editing the script.

Usage:
    # As a Stop hook: hook JSON is read from stdin, exit 0 = fire, 1 = silent.
    echo "$HOOK_JSON" | python detect_costly_search.py

    # Standalone, against a transcript file:
    python detect_costly_search.py --transcript path/to/transcript.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

# Tool names that count as a structural-search read. These are the cheap-but-
# repeated calls whose accumulation is the whole signal we are watching for.
SEARCH_TOOLS = frozenset({"Read", "Grep", "Glob"})

# Default trip point: six search calls in one turn is enough scanning that a
# forged skill would have paid for itself. Overridable per project.
DEFAULT_MIN_CALLS = 6

# A structural prompt pairs a lookup word with a code noun. Kept as two separate
# alternations so "which" alone or "class" alone does not trip the heuristic;
# we need one of each in the same prompt.
LOOKUP_WORDS = re.compile(
    r"\b(which|where|how[ -]?many|largest|biggest|find[ -]all|list[ -]all|all the)\b",
    re.IGNORECASE,
)
CODE_NOUNS = re.compile(
    r"\b(functions?|methods?|class(?:es)?|usages?|imports?|components?|services?|calls?)\b",
    re.IGNORECASE,
)

# The single suggest-only line printed when the heuristic fires. One line, never
# more: this is a nudge, not a wall of text, and it must never block the Stop
# event. It points at the sniff-forge skill, which turns a repeated structural
# query into a token-cheap skill.
NUDGE = (
    "[sniff-forge] That looked like a repeated structural search. "
    "Run the sniff-forge skill to turn it into a token-cheap skill. "
    "(silence: SNIFF_FORGE_NUDGE=0)"
)

# Env values that switch the nudge off. The hook is opt-out: on by default,
# silenced by setting SNIFF_FORGE_NUDGE to any of these.
OFF_VALUES = frozenset({"0", "off", "false", "no"})


def nudge_enabled(env: dict | None = None) -> bool:
    """False when SNIFF_FORGE_NUDGE is set to an off value (opt-out switch)."""

    env = os.environ if env is None else env

    return env.get("SNIFF_FORGE_NUDGE", "").strip().lower() not in OFF_VALUES


@dataclass
class Detection:
    """Outcome of the heuristic plus the raw signals that produced it."""

    fired: bool
    search_calls: int
    structural_prompt: bool
    prompt: str


def is_structural_prompt(prompt: str) -> bool:
    """True when the prompt pairs a lookup word with a code noun."""

    return bool(LOOKUP_WORDS.search(prompt) and CODE_NOUNS.search(prompt))


def _content_items(message: dict) -> list:
    """Return the content array of a transcript message, tolerating shapes.

    Claude Code transcript lines wrap the real payload in a "message" object,
    but older/forged lines sometimes put "content" at the top level. Accept
    either, and a bare string, so the heuristic never crashes on a malformed
    line mid-turn.
    """

    payload = message.get("message", message)

    content = payload.get("content", [])

    if isinstance(content, str):
        return [{"type": "text", "text": content}]

    return content if isinstance(content, list) else []


def _is_user_prompt(line: dict) -> bool:
    """True when a transcript line is a genuine user prompt, not a tool result.

    Tool results come back on lines also typed "user", so we must look inside the
    content: a real prompt carries plain text, a tool result carries a
    tool_result block. Only the former opens a new turn.
    """

    if line.get("type") != "user":
        return False

    for item in _content_items(line):
        if isinstance(item, dict) and item.get("type") == "tool_result":
            return False

    return True


def _prompt_text(line: dict) -> str:
    """Flatten the text blocks of a user prompt line into one string."""

    parts = []

    for item in _content_items(line):
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))

    return " ".join(p for p in parts if p).strip()


def _count_search_calls(line: dict) -> int:
    """Count Read/Grep/Glob tool_use blocks in one assistant line."""

    count = 0

    for item in _content_items(line):
        if (
            isinstance(item, dict)
            and item.get("type") == "tool_use"
            and item.get("name") in SEARCH_TOOLS
        ):
            count += 1

    return count


def analyze_turn(lines: list[dict]) -> tuple[int, str]:
    """Reduce a transcript to the last turn's search-call count and prompt.

    Walks the transcript and resets the running count every time a fresh user
    prompt opens a new turn, so the result reflects only the most recent turn
    (the one the Stop hook just finished).
    """

    search_calls = 0
    prompt = ""

    for line in lines:
        if _is_user_prompt(line):
            # New turn starts: drop the previous turn's tally.
            search_calls = 0
            prompt = _prompt_text(line)
            continue

        if line.get("type") == "assistant":
            search_calls += _count_search_calls(line)

    return search_calls, prompt


def detect(lines: list[dict], min_calls: int = DEFAULT_MIN_CALLS) -> Detection:
    """Run the heuristic over a parsed transcript."""

    search_calls, prompt = analyze_turn(lines)

    structural = is_structural_prompt(prompt)

    fired = search_calls >= min_calls and structural

    return Detection(
        fired=fired,
        search_calls=search_calls,
        structural_prompt=structural,
        prompt=prompt,
    )


def _read_transcript(path: str) -> list[dict]:
    """Parse a JSONL transcript, skipping any unparseable lines."""

    lines = []

    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()

            if not raw:
                continue

            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                # A single bad line should not blind the whole heuristic.
                continue

    return lines


def _resolve_transcript_path(args: argparse.Namespace) -> str | None:
    """Find the transcript: explicit flag wins, else the Stop-hook JSON stdin."""

    if args.transcript:
        return args.transcript

    if sys.stdin.isatty():
        return None

    try:
        hook = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return None

    return hook.get("transcript_path")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Detect a costly structural search in the last turn (Stop-hook heuristic)."
    )
    parser.add_argument(
        "--transcript",
        help="path to a JSONL transcript (default: read transcript_path from Stop-hook JSON on stdin)",
    )
    parser.add_argument(
        "--min-calls",
        type=int,
        default=int(os.environ.get("SNIFF_MIN_CALLS", DEFAULT_MIN_CALLS)),
        help=f"read/grep/glob calls needed to trip (default: {DEFAULT_MIN_CALLS}, or $SNIFF_MIN_CALLS)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the full detection signals as JSON instead of just the exit code",
    )
    args = parser.parse_args()

    path = _resolve_transcript_path(args)

    if not path or not os.path.exists(path):
        # No transcript to judge: stay silent, never block the Stop event.
        if args.json:
            print(json.dumps({"fired": False, "reason": "no transcript"}))
        sys.exit(0)

    result = detect(_read_transcript(path), min_calls=args.min_calls)

    enabled = nudge_enabled()

    if args.json:
        print(
            json.dumps(
                {
                    "fired": result.fired,
                    "search_calls": result.search_calls,
                    "structural_prompt": result.structural_prompt,
                    "prompt": result.prompt,
                    "nudge_enabled": enabled,
                }
            )
        )

    # Emit the one-line nudge only when the heuristic fired AND the user has not
    # opted out. Suggest-only: never auto-create a skill, never block the Stop
    # event (a non-zero exit here is just a signal, the line is the payload).
    if result.fired and enabled:
        print(NUDGE)

    # Always exit 0: this hook is suggest-only and must never look like a failed
    # Stop hook. The nudge line is the only payload; a non-zero exit gains nothing
    # and surfaces a spurious "non-blocking status code" error after every turn.
    sys.exit(0)


if __name__ == "__main__":
    main()
