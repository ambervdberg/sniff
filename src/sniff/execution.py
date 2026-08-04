"""Run a single detector and shape its result: in-process or subprocess, JSON
or markdown.

Every detector, whether it is a built-in module or an external manifest-based
script, ends up funnelled through `run_detector_json`, so both the `--json`
scan output and the markdown scan section render from the same structured
result. `_render_detector_result` and `_detector_failed` are the two ways that
result gets interpreted afterward: one turns it into the text a markdown scan
section prints, the other decides whether it should flip the process exit
code.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys

from sniff import discovery


def _run_module_detector(detector: discovery.Detector, path: str) -> "tuple[str, int, str | None]":
    """Run a built-in detector's module.main() in-process, capturing its stdout.

    Mirrors what the subprocess path gets from a script: (stdout text, exit code,
    error message). Detectors call `sys.exit("some message")` on a usage error
    (e.g. no supported source files); in-process that raises SystemExit with a
    string `.code` instead of printing to stderr and exiting, so it is caught
    here and folded into the same shape run_detector_json already expects."""
    buf = io.StringIO()
    error: "str | None" = None
    try:
        with contextlib.redirect_stdout(buf):
            result = detector.module.main([path, *detector.args])
        code = result if isinstance(result, int) else 0
    except SystemExit as exc:
        if isinstance(exc.code, int):
            code = exc.code
        elif exc.code is None:
            code = 0
        else:
            code = 1
            error = str(exc.code)
    return buf.getvalue(), code, error


def run_detector_json(detector: discovery.Detector, path: str) -> dict:
    """Run one detector over `path`, return a JSON-serializable result.

    Runs in-process for built-ins, subprocess for external detectors, and
    keeps stdout/stderr/exit_code structured instead of folding them into a
    markdown string, so `--json` output stays machine-parseable (e.g. by
    evals/scorer.py). `_render_detector_result` folds this same structured
    result into the markdown scan's per-detector section text."""
    if detector.module is not None:
        out, code, error = _run_module_detector(detector, path)
        return {
            "detector": detector.name,
            "title": detector.title,
            "exit_code": code,
            "output": out.strip(),
            "error": error,
        }

    cmd = [sys.executable, detector.script, path, *detector.args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        return {
            "detector": detector.name,
            "title": detector.title,
            "exit_code": None,
            "output": None,
            "error": str(exc),
        }
    return {
        "detector": detector.name,
        "title": detector.title,
        "exit_code": proc.returncode,
        "output": proc.stdout.strip(),
        "error": proc.stderr.strip() or None,
    }


def _render_detector_result(result: dict) -> str:
    """Render a `run_detector_json` result as the markdown scan section body.

    Mirrors the text the old in-process `run_detector` produced byte-for-byte,
    so switching the markdown render path onto the same JSON results the
    `--json` branch already computes cannot change what a plain `sniff` scan
    prints. A detector that never launched (`exit_code` is None, external
    detectors only) gets the "failed to launch" note; a detector that ran but
    exited non-zero gets the "exited non-zero" note; a clean run prints its
    output, or a placeholder when it produced none."""
    if result["exit_code"] is None:
        return f"_detector failed to launch: {result['error']}_"

    out = (result["output"] or "").strip()
    if result["exit_code"] != 0:
        err = result["error"] or f"exit code {result['exit_code']}"
        return f"{out}\n\n_detector exited non-zero: {err}_".strip()
    return out or "_no output_"


def _detector_failed(result: dict) -> bool:
    """True when `result` (a `run_detector_json` dict) represents a detector
    that failed to run, not one that merely reported findings.

    Exit code is the sole authority: a non-zero `exit_code` is a failure, and
    so is a launch failure (`exit_code` None with `error` set, external
    detectors only). An external detector that exits 0 while writing
    incidental text to stderr is NOT a failure, even though `error` is set on
    its result: `_render_detector_result` renders that case as a clean
    section, so the exit code must agree with what got printed."""
    exit_code = result["exit_code"]
    if exit_code is None:
        return bool(result["error"])
    return exit_code != 0
