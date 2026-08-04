"""Tests for the gate fingerprint/threshold logic."""

import os
import tempfile
import unittest
from unittest import mock

from sniff import discovery, gate, harness


def finding(file="src/a.py", name="fn", **metrics):
    return {"file": file, "line": 3, "name": name, "metrics": dict(metrics)}


def fake_detector(name, builtin=True):
    """A stand-in for discovery.Detector: only `.name` and `.module` are read."""
    detector = mock.Mock()
    detector.name = name
    detector.module = object() if builtin else None
    return detector


def ok_result(name):
    return {"detector": name, "title": "t", "exit_code": 0, "output": "", "error": None}


class ThresholdKeyTest(unittest.TestCase):
    """GATE_THRESHOLDS keys are detector-name string literals.

    Renaming a detector without touching this table silently un-gates it, so the
    keys must always name detectors discovery actually finds.
    """

    def test_gate_thresholds_reference_real_detectors(self):
        detectors, _ = discovery.discover()
        names = {d.name for d in detectors}
        self.assertLessEqual(set(gate.GATE_THRESHOLDS), names)
        self.assertLessEqual(gate._FILE_LEVEL, set(gate.GATE_THRESHOLDS))


class FingerprintTest(unittest.TestCase):
    def test_node_metric_below_gate_threshold_is_dropped(self):
        fps = gate.fingerprint_findings(
            "cyclomatic-complexity", [finding(cyclomatic=3)])
        self.assertEqual(fps, {})

    def test_node_metric_at_threshold_is_kept_with_value(self):
        fps = gate.fingerprint_findings(
            "cyclomatic-complexity", [finding(cyclomatic=10)])
        self.assertEqual(fps, {"src/a.py|fn": 10})

    def test_file_metric_fingerprint_is_file_only(self):
        fps = gate.fingerprint_findings(
            "largest-files", [finding(file="big.py", name="(anon)", lines=999)])
        self.assertEqual(fps, {"big.py": 999})

    def test_patterns_fingerprint_counts_per_rule_and_file(self):
        rows = [
            finding(file="a.py", name="py-print-statement",
                    rule="py-print-statement", severity="warning"),
            finding(file="a.py", name="py-print-statement",
                    rule="py-print-statement", severity="warning"),
        ]
        fps = gate.fingerprint_findings("sniff-patterns", rows)
        self.assertEqual(fps, {"py-print-statement|a.py": 2})

    def test_unknown_detector_counts_every_finding(self):
        # New detectors added later must be gated, not silently ignored.
        fps = gate.fingerprint_findings("brand-new-detector", [finding()])
        self.assertEqual(fps, {"src/a.py|fn": 1})

    def test_metric_outside_metrics_dict_is_read_from_the_entry(self):
        # largest-files/largest-methods/most-imports keep their ranking value in
        # a top-level sink field, not in `metrics` (see gate module docstring).
        entry = {"file": "big.py", "line": 1, "name": "(anon)",
                 "metrics": {}, "lines": 500}
        fps = gate.fingerprint_findings("largest-files", [entry])
        self.assertEqual(fps, {"big.py": 500})

    def test_most_imports_reads_its_count_field(self):
        entry = {"file": "hub.py", "line": 1, "name": "(anon)",
                 "metrics": {}, "count": 25}
        fps = gate.fingerprint_findings("most-imports", [entry])
        self.assertEqual(fps, {"hub.py": 25})

    def test_clone_groups_sharing_a_file_set_do_not_collapse(self):
        """Two unrelated duplicated blocks in one file share a fingerprint.

        A clone group is identified by the files it spans, so a second block
        duplicated inside a file that already had one lands on the same key. If
        both flattened to 1 the gate would see no change and wave it through."""
        one = [finding(file="a.py", name="(anon)")]
        two = one + [finding(file="a.py", name="(anon)")]

        self.assertEqual(
            gate.fingerprint_findings("duplicate-code", one), {"a.py|(anon)": 1})
        self.assertEqual(
            gate.fingerprint_findings("duplicate-code", two), {"a.py|(anon)": 2})

    def test_unknown_detector_findings_sharing_a_fingerprint_accumulate(self):
        rows = [finding(), finding(), finding()]
        fps = gate.fingerprint_findings("brand-new-detector", rows)
        self.assertEqual(fps, {"src/a.py|fn": 3})

    def test_worst_value_wins_for_a_repeated_fingerprint(self):
        rows = [finding(cyclomatic=12), finding(cyclomatic=20)]
        fps = gate.fingerprint_findings("cyclomatic-complexity", rows)
        self.assertEqual(fps, {"src/a.py|fn": 20})


class ScanFailClosedTest(unittest.TestCase):
    def tearDown(self):
        harness.FINDINGS_SINK = None

    def test_detector_error_raises(self):
        bad = {"detector": "largest-methods", "title": "t",
               "exit_code": 1, "output": "", "error": "ast-grep exploded"}
        det = fake_detector("largest-methods")
        with mock.patch("sniff.gate._run_one", return_value=bad):
            with self.assertRaises(gate.DetectorFailure) as ctx:
                gate.scan_fingerprints([det], ".")
        self.assertIn("largest-methods", str(ctx.exception))
        self.assertIn("ast-grep exploded", str(ctx.exception))

    def test_nonzero_exit_without_stderr_reports_the_code(self):
        bad = {"detector": "most-imports", "title": "t",
               "exit_code": 2, "output": "", "error": None}
        det = fake_detector("most-imports")
        with mock.patch("sniff.gate._run_one", return_value=bad):
            with self.assertRaises(gate.DetectorFailure) as ctx:
                gate.scan_fingerprints([det], ".")
        self.assertIn("exit code 2", str(ctx.exception))

    def test_external_detectors_are_skipped(self):
        det = fake_detector("shell-detector", builtin=False)
        with mock.patch("sniff.gate._run_one") as run:
            self.assertEqual(gate.scan_fingerprints([det], "."), {})
        run.assert_not_called()

    def test_findings_are_collected_per_detector(self):
        det = fake_detector("most-parameters")

        def run(_detector, _path):
            harness.FINDINGS_SINK.append(finding(name="wide", params=9))
            return ok_result("most-parameters")

        with mock.patch("sniff.gate._run_one", side_effect=run):
            results = gate.scan_fingerprints([det], ".")
        self.assertEqual(results, {"most-parameters": {"src/a.py|wide": 9}})

    def test_sink_is_uninstalled_after_a_successful_scan(self):
        det = fake_detector("most-parameters")
        with mock.patch("sniff.gate._run_one",
                        return_value=ok_result("most-parameters")):
            gate.scan_fingerprints([det], ".")
        self.assertIsNone(harness.FINDINGS_SINK)

    def test_sink_is_uninstalled_after_a_detector_crashes(self):
        # A leaked sink would keep growing through every later print_table call.
        det = fake_detector("most-parameters")
        with mock.patch("sniff.gate._run_one", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                gate.scan_fingerprints([det], ".")
        self.assertIsNone(harness.FINDINGS_SINK)


class ScanRealDetectorsTest(unittest.TestCase):
    """Every built-in detector must survive a gated scan.

    Five detectors hand `print_table` their own row dataclass rather than a
    `Match` (largest-files, most-imports, duplicate-code, no-duplicate-string,
    self-admitted-debt); the sink has to record those too, or the gate raises
    DetectorFailure on a perfectly healthy repo."""

    def tearDown(self):
        harness.FINDINGS_SINK = None
        harness.reset_git_ignore_cache()

    def test_scan_over_a_real_tree_names_every_builtin_detector(self):
        from sniff import discovery

        detectors = discovery.discover()[0]
        builtins = [d for d in detectors if d.module is not None]

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "app.py"), "w", encoding="utf-8") as fh:
                fh.write("import os\n\n\ndef main():\n    print(os)  # TODO: fix\n")

            results = gate.scan_fingerprints(builtins, tmp)

        self.assertEqual(sorted(results), sorted(d.name for d in builtins))

    def test_a_second_duplicated_block_registers_as_a_change(self):
        """The same scenario, through the real duplicate-code detector.

        One file, two structurally unrelated blocks, each duplicated. Both clone
        groups span the same single file, so both carry the same fingerprint;
        only the value tells the gate that the file got worse."""
        from sniff import discovery

        detectors = [d for d in discovery.discover()[0] if d.name == "duplicate-code"]

        before = self._duplicate_code_values(_ALPHA_BLOCK.format(n=1)
                                             + _ALPHA_BLOCK.format(n=2))
        after = self._duplicate_code_values(_ALPHA_BLOCK.format(n=1)
                                            + _ALPHA_BLOCK.format(n=2)
                                            + _BETA_BLOCK.format(n=1)
                                            + _BETA_BLOCK.format(n=2),
                                            detectors=detectors)

        self.assertEqual(before, [1])
        self.assertEqual(after, [2])

    def _duplicate_code_values(self, source: str, detectors=None) -> list:
        """duplicate-code's fingerprint values for a one-file tree."""
        from sniff import discovery

        if detectors is None:
            detectors = [d for d in discovery.discover()[0]
                         if d.name == "duplicate-code"]

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "dup.py"), "w", encoding="utf-8") as fh:
                fh.write(source)
            results = gate.scan_fingerprints(detectors, tmp)

        return sorted(results["duplicate-code"].values())

    def test_every_threshold_key_resolves_on_real_findings(self):
        """A threshold naming a key no detector writes drops every finding.

        `_value_of` falls back to 1 for a missing key, which is below every
        floor, so a renamed metric would turn a detector off rather than fail:
        exactly the silent pass this module exists to prevent. This scans a
        file built to trip each floor and checks the violations come back."""
        from sniff import discovery

        gated = set(gate.GATE_THRESHOLDS)
        # large-inline-templates only fires on an Angular @Component decorator,
        # which a Python fixture cannot carry.
        gated.discard("large-inline-templates")

        detectors = [d for d in discovery.discover()[0] if d.name in gated]
        self.assertEqual(len(detectors), len(gated))

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "big_module.py"), "w", encoding="utf-8") as fh:
                fh.write(_over_every_threshold())

            results = gate.scan_fingerprints(detectors, tmp)

        empty = sorted(name for name, fps in results.items() if not fps)
        self.assertEqual(empty, [], "detectors whose gate metric never resolved")


# Two duplicated blocks, long enough to clear duplicate-code's defaults (5 lines,
# 30 tokens) and shaped differently enough that they do not normalise into one
# clone group: a loop over a list versus a while over a dict.
_ALPHA_BLOCK = """\
def alpha_{n}(source):
    result = []
    for item in source:
        if item.weight is None:
            continue
        result.append(item.weight * 3 + len(source))
    result.sort(key=lambda value: -value)
    return result[:10]

"""

_BETA_BLOCK = """\
def beta_{n}(table, key):
    seen = {{}}
    index = 0
    while index < len(table):
        row = table[index]
        seen[row[key]] = seen.get(row[key], 0) + 1
        index += 1
    return sorted(seen.items())

"""


def _over_every_threshold() -> str:
    """A Python module that violates every gate threshold a Python file can.

    One 100-line, 5-parameter, deeply nested function with a dozen branches
    (methods, parameters, nesting, both complexities) plus 25 imports and a
    400-line class, all in a file long enough to trip largest-files."""
    imports = "\n".join(f"import mod{i}" for i in range(25))

    flags = "".join(f"    flag_{i} = a\n" for i in range(12))
    branches = "\n".join(
        f"    if flag_{i} == {i}:\n        total += {i}" for i in range(12))
    nested = (
        "    for i in range(10):\n"
        "        if a:\n"
        "            while b:\n"
        "                if c:\n"
        "                    for j in range(3):\n"
        "                        if d:\n"
        "                            total += j\n"
    )
    filler = "\n".join(f"    total += {i}" for i in range(60))
    function = (
        "def wide(a, b, c, d, e):\n    total = 0\n"
        f"{flags}{branches}\n{nested}{filler}\n    return total\n"
    )

    methods = "\n".join(
        f"    def method_{i}(self):\n"
        + "".join(f"        x{j} = {j}\n" for j in range(8))
        + "        return x0\n"
        for i in range(40)
    )

    return f"{imports}\n\n\n{function}\n\nclass Big:\n{methods}\n"


if __name__ == "__main__":
    unittest.main()
