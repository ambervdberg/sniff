"""
evals/runner.py -- Prompt-sim eval runner for the sniff LLM eval harness.

Simulates an IDE coding agent context: loads the appropriate surface docs,
asks the model to return the *first* shell command it would run as structured
JSON, then writes results to a JSONL file for the scorer.

Usage:
    # Run all cases (default model: gpt-5.4-nano):
    python evals/runner.py

    # Specific model:
    python evals/runner.py --model gpt-5.4-mini

    # Specific cases:
    python evals/runner.py --cases case-001,case-007

    # Custom output file:
    python evals/runner.py --output evals/results/run-001.jsonl

    # Dry run (no API calls, prints prompts):
    python evals/runner.py --dry-run

After the run, score the results:
    python evals/scorer.py --results <output_file>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_EVALS_DIR = Path(__file__).parent
_SKILLS_DIR = _EVALS_DIR.parent / "skills"
_CASES_FILE = _EVALS_DIR / "cases.jsonl"


def _default_output(model: str) -> Path:
    """Timestamped output path so runs never overwrite each other."""
    ts = int(time.time())
    safe_model = model.replace("/", "-").replace(":", "-")
    return _EVALS_DIR / "results" / f"{ts}-{safe_model}.jsonl"

# ---------------------------------------------------------------------------
# Surface context builders
#
# Each function returns a string that will become the "available context"
# block in the system prompt, mirroring what an IDE coding agent sees.
# ---------------------------------------------------------------------------

def _surface_discovery() -> str:
    """Discovery surface: only the one-line skill summary, no full docs."""
    skill_md = _SKILLS_DIR / "sniff" / "SKILL.md"
    # Extract the `description:` field from YAML frontmatter.
    text = skill_md.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("description:"):
            # Inline description (single line after the colon).
            desc = line[len("description:"):].strip()
            if desc and desc != ">-":
                return f"Available skill: sniff — {desc}"
        # Multi-line block scalar: grab first non-empty continuation line.
        if line and not line.startswith("---") and not line.startswith("name:") and not line.startswith("description:"):
            # Heuristic: first indented content line after `description: >-`
            # is already yielded by the loop; just return it.
            return f"Available skill: sniff — {line}"
    return "Available skill: sniff — code-smell detector"


def _surface_skill_md() -> str:
    """Full SKILL.md verbatim — source of truth for what agents actually see."""
    skill_md = _SKILLS_DIR / "sniff" / "SKILL.md"
    return skill_md.read_text(encoding="utf-8")


def _surface_help() -> str:
    """sniff --help output."""
    result = subprocess.run(
        [sys.executable, "-m", "skills.sniff.scripts.run", "--help"],
        capture_output=True,
        text=True,
        cwd=_EVALS_DIR.parent,
    )
    # Strip ANSI colour codes for the model.
    import re
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    return ansi.sub("", result.stdout or result.stderr)


def _surface_list() -> str:
    """sniff --list output."""
    result = subprocess.run(
        [sys.executable, "-m", "skills.sniff.scripts.run", "--list"],
        capture_output=True,
        text=True,
        cwd=_EVALS_DIR.parent,
    )
    import re
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    return ansi.sub("", result.stdout or result.stderr)


_SURFACE_BUILDERS = {
    "discovery": _surface_discovery,
    "skill_md": _surface_skill_md,
    "help": _surface_help,
    "list": _surface_list,
}

# Cache surface content so we call --help/--list only once per run.
_surface_cache: dict[str, str] = {}


def get_surface_content(surface: str) -> str:
    if surface not in _surface_cache:
        builder = _SURFACE_BUILDERS.get(surface)
        if builder is None:
            raise ValueError(f"Unknown surface: {surface!r}")
        _surface_cache[surface] = builder()
    return _surface_cache[surface]


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an IDE coding agent. The user has asked you a question about their codebase.
You have access to a shell and the tools/skills listed below.

Your task: decide the SINGLE first shell command you would run to answer the user's request.
Reply with ONLY a JSON object in this exact format — no prose, no markdown fences:

{"command": "<the shell command>"}

Rules:
- Output exactly one JSON object, nothing else.
- The command must be a real shell command you would actually run.
- Do not use flags that do not exist (e.g. there is no --verbose or --format flag for sniff).
- If you need to explore before committing to a specific scan, output an exploration command.
"""

_CONTEXT_HEADER = {
    "discovery": "## Available skill\n\n",
    "skill_md": "## sniff skill documentation\n\n",
    "help": "## sniff --help output\n\n```\n",
    "list": "## sniff --list output\n\n```\n",
}

_CONTEXT_FOOTER = {
    "discovery": "",
    "skill_md": "",
    "help": "\n```",
    "list": "\n```",
}


def build_user_message(case: dict[str, Any]) -> str:
    surface = case["surface"]
    context = get_surface_content(surface)
    header = _CONTEXT_HEADER.get(surface, "")
    footer = _CONTEXT_FOOTER.get(surface, "")
    return (
        f"{header}{context}{footer}\n\n"
        f"## User request\n\n{case['prompt']}"
    )


# ---------------------------------------------------------------------------
# OpenAI call
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-5.4-nano"


def call_model(system: str, user: str, model: str) -> str:
    """Call the appropriate API based on model name prefix.

    - Models starting with "claude-" use the Anthropic Messages API.
    - All others use the OpenAI Responses API.
    """
    if model.startswith("claude-"):
        return _call_anthropic(system, user, model)
    return _call_openai(system, user, model)


def _call_openai(system: str, user: str, model: str) -> str:
    from openai import OpenAI, APIError

    client = OpenAI()
    try:
        response = client.responses.create(
            model=model,
            instructions=system,
            input=user,
        )
        return response.output_text.strip()
    except APIError as exc:
        raise RuntimeError(f"OpenAI API error: {exc}") from exc


def _call_anthropic(system: str, user: str, model: str) -> str:
    from anthropic import Anthropic, APIError

    client = Anthropic()
    try:
        message = client.messages.create(
            model=model,
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return message.content[0].text.strip()
    except APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc}") from exc


def parse_command(raw: str) -> str:
    """Extract the command string from the model's JSON response.

    Handles:
    - Clean JSON:  {"command": "sniff --only largest-files"}
    - JSON wrapped in markdown fences (model ignored instructions)
    - Fallback: return the raw string for the scorer to judge
    """
    import re

    # Strip markdown fences if present.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)

    # Try to parse as JSON.
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and "command" in obj:
            return str(obj["command"]).strip()
    except json.JSONDecodeError:
        pass

    # Last resort: return raw (scorer will likely flag as prose).
    return raw


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def load_cases(case_ids: list[str] | None = None) -> list[dict[str, Any]]:
    cases = []
    with _CASES_FILE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if case_ids is None or case["id"] in case_ids:
                cases.append(case)
    return cases


def run_eval(
    model: str,
    case_ids: list[str] | None,
    output_path: Path,
    dry_run: bool,
) -> None:
    cases = load_cases(case_ids)
    if not cases:
        print("No cases found.", file=sys.stderr)
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(cases)} cases with model={model!r} -> {output_path}")

    with output_path.open("w", encoding="utf-8") as out:
        for i, case in enumerate(cases, 1):
            user_msg = build_user_message(case)

            if dry_run:
                print(f"\n{'='*60}")
                print(f"[{i}/{len(cases)}] {case['id']} (surface={case['surface']})")
                print("--- USER MESSAGE ---")
                print(user_msg)
                print("--- END ---")
                continue

            print(f"  [{i}/{len(cases)}] {case['id']} ...", end=" ", flush=True)
            try:
                raw = call_model(_SYSTEM_PROMPT, user_msg, model)
                command = parse_command(raw)
                status = "ok"
                error = None
            except Exception as exc:
                command = ""
                raw = ""
                status = "error"
                error = str(exc)

            result = {
                "id": case["id"],
                "actual": command,
                "model": model,
                "surface": case["surface"],
                "raw": raw,
                "status": status,
                "error": error,
            }
            out.write(json.dumps(result) + "\n")
            out.flush()

            if status == "error":
                print(f"ERROR: {error}")
            else:
                print(f"-> {command!r}")

    if not dry_run:
        # Also write a copy to latest.jsonl for convenience.
        import shutil
        latest = output_path.parent / "latest.jsonl"
        shutil.copy2(output_path, latest)

        print(f"\nDone.")
        print(f"  Saved : {output_path}")
        print(f"  Latest: {latest}")
        print(f"  Score : python evals/scorer.py --results {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prompt-sim eval runner for the sniff LLM eval harness."
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--cases",
        help="Comma-separated case IDs to run (default: all)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSONL file (default: evals/results/<timestamp>-<model>.jsonl)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompts without making API calls",
    )
    args = parser.parse_args()

    case_ids = [c.strip() for c in args.cases.split(",")] if args.cases else None
    output_path = Path(args.output) if args.output else _default_output(args.model)

    run_eval(
        model=args.model,
        case_ids=case_ids,
        output_path=output_path,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
