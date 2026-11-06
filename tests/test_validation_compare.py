"""Tests for st2fb.compare, including every report field and the CLI exit codes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from st2fb.compare import DEFAULT_REAL_TOLERANCE, compare_traces, main, values_equal


def trace(*scans: dict[str, Any], outputs: list[str] | None = None, scan_ms: int = 10) -> dict[str, Any]:
    names = outputs if outputs is not None else [k for k in (scans[0] if scans else {}) if k != "t_ms"]
    return {"source": "test", "scan_ms": scan_ms, "outputs": names, "scans": list(scans)}


def scan(i: int, scan_ms: int = 10, **values: Any) -> dict[str, Any]:
    return {"t_ms": i * scan_ms, **values}


class ValueRules(unittest.TestCase):
    def test_bool_never_equals_a_number(self) -> None:
        self.assertFalse(values_equal(True, 1))
        self.assertFalse(values_equal(1, True))
        self.assertFalse(values_equal(False, 0))
        self.assertFalse(values_equal(False, 0.0))
        self.assertTrue(values_equal(True, True))
        self.assertFalse(values_equal(True, False))

    def test_integers_are_exact(self) -> None:
        self.assertTrue(values_equal(100000, 100000))
        self.assertFalse(values_equal(100000, 100001))
        self.assertFalse(values_equal(5, 5.000001))
        self.assertTrue(values_equal(5, 5.0))

    def test_real_uses_relative_tolerance(self) -> None:
        self.assertTrue(values_equal(100000.0, 100000.5))
        self.assertTrue(values_equal(100000.0, 100000))
        self.assertFalse(values_equal(100000.0, 100002.0))
        self.assertTrue(values_equal(-1.0, -1.000009))
        self.assertFalse(values_equal(-1.0, -1.00002))
        self.assertFalse(values_equal(1.0, -1.0))

    def test_real_zero_has_no_absolute_floor(self) -> None:
        self.assertTrue(values_equal(0.0, 0.0))
        self.assertTrue(values_equal(0.0, -0.0))
        self.assertFalse(values_equal(0.0, 1e-30))

    def test_non_numbers_are_not_equal(self) -> None:
        self.assertFalse(values_equal(1, "1"))
        self.assertFalse(values_equal(None, None))
        self.assertFalse(values_equal(1.0, None))


class Report(unittest.TestCase):
    def test_equal_report_has_every_field(self) -> None:
        reference = trace(scan(0, Q=False, X=1.5), scan(1, Q=True, X=2.5))
        self.assertEqual(
            compare_traces(reference, reference),
            {
                "equal": True,
                "scans_compared": 2,
                "first_divergence": None,
                "divergences": 0,
                "real_tolerance": DEFAULT_REAL_TOLERANCE,
                "shape_errors": [],
            },
        )

    def test_value_divergence_reports_the_first_and_counts_all(self) -> None:
        expected = trace(scan(0, Q=False, N=1), scan(1, Q=True, N=2), scan(2, Q=True, N=3))
        actual = trace(scan(0, Q=False, N=1), scan(1, Q=False, N=9), scan(2, Q=False, N=3))
        self.assertEqual(
            compare_traces(expected, actual),
            {
                "equal": False,
                "scans_compared": 3,
                "first_divergence": {"scan": 1, "t_ms": 10, "output": "Q", "expected": True, "actual": False},
                "divergences": 3,
                "real_tolerance": DEFAULT_REAL_TOLERANCE,
                "shape_errors": [],
            },
        )

    def test_real_tolerance_is_configurable_and_reported(self) -> None:
        expected, actual = trace(scan(0, X=1.0)), trace(scan(0, X=1.01))
        self.assertFalse(compare_traces(expected, actual)["equal"])
        report = compare_traces(expected, actual, tolerance=0.1)
        self.assertTrue(report["equal"])
        self.assertEqual(report["real_tolerance"], 0.1)

    def test_scan_count_mismatch(self) -> None:
        expected = trace(scan(0, Q=True), scan(1, Q=True), scan(2, Q=True))
        actual = trace(scan(0, Q=True))
        report = compare_traces(expected, actual)
        self.assertFalse(report["equal"])
        self.assertEqual(report["scans_compared"], 1)
        self.assertEqual(report["divergences"], 1)
        self.assertEqual(report["first_divergence"]["scan"], 1)
        self.assertEqual(report["first_divergence"]["t_ms"], 10)
        self.assertIsNone(report["first_divergence"]["output"])
        self.assertIn("scan count", report["shape_errors"][0])

    def test_scan_count_mismatch_reports_an_earlier_value_divergence_first(self) -> None:
        expected = trace(scan(0, Q=True), scan(1, Q=True), scan(2, Q=True))
        actual = trace(scan(0, Q=False))
        report = compare_traces(expected, actual)
        self.assertEqual(report["first_divergence"]["output"], "Q")
        self.assertEqual(report["first_divergence"]["scan"], 0)
        self.assertEqual(report["divergences"], 2)

    def test_empty_trace_against_non_empty_is_not_equal(self) -> None:
        report = compare_traces(trace(scan(0, Q=True)), trace(outputs=["Q"]))
        self.assertFalse(report["equal"])
        self.assertEqual(report["scans_compared"], 0)

    def test_output_missing_from_actual(self) -> None:
        expected = trace(scan(0, Q=True, N=1))
        actual = trace(scan(0, Q=True))
        report = compare_traces(expected, actual)
        self.assertFalse(report["equal"])
        self.assertEqual(report["first_divergence"]["output"], "N")
        self.assertEqual(report["divergences"], 1)
        self.assertIn("'N' is missing", report["shape_errors"][0])

    def test_extra_output_in_actual(self) -> None:
        report = compare_traces(trace(scan(0, Q=True)), trace(scan(0, Q=True, N=1)))
        self.assertFalse(report["equal"])
        self.assertIn("'N' is not in the expected", report["shape_errors"][0])

    def test_output_order_does_not_matter(self) -> None:
        expected = trace(scan(0, Q=True, N=1), outputs=["Q", "N"])
        actual = trace(scan(0, Q=True, N=1), outputs=["N", "Q"])
        self.assertTrue(compare_traces(expected, actual)["equal"])

    def test_declared_output_absent_from_a_record(self) -> None:
        expected = trace(scan(0, Q=True), outputs=["Q"])
        actual = trace({"t_ms": 0}, outputs=["Q"])
        report = compare_traces(expected, actual)
        self.assertFalse(report["equal"])
        self.assertEqual(report["first_divergence"]["output"], "Q")

    def test_scan_ms_mismatch(self) -> None:
        report = compare_traces(trace(scan(0, Q=True)), trace(scan(0, Q=True), scan_ms=20))
        self.assertFalse(report["equal"])
        self.assertIn("scan_ms", report["shape_errors"][0])

    def test_time_stamp_has_no_tolerance(self) -> None:
        expected = trace(scan(0, Q=True), scan(1, Q=True))
        actual = trace(scan(0, Q=True), {"t_ms": 11, "Q": True})
        report = compare_traces(expected, actual)
        self.assertFalse(report["equal"])
        self.assertEqual(
            report["first_divergence"], {"scan": 1, "t_ms": 10, "output": "t_ms", "expected": 10, "actual": 11}
        )

    def test_wrong_time_stamp_in_both_traces_is_still_caught(self) -> None:
        wrong = trace({"t_ms": 5, "Q": True})
        self.assertFalse(compare_traces(wrong, wrong)["equal"])


class CommandLine(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)

    def run_cli(self, expected: Any, actual: Any) -> tuple[int, dict[str, Any]]:
        for name, content in (("a.json", expected), ("b.json", actual)):
            text = content if isinstance(content, str) else json.dumps(content)
            (self.dir / name).write_text(text)
        out = self.dir / "sub" / "report.json"
        status = main([str(self.dir / "a.json"), str(self.dir / "b.json"), "--out", str(out)])
        return status, json.loads(out.read_text())

    def test_equal_exits_zero(self) -> None:
        reference = trace(scan(0, Q=True))
        status, report = self.run_cli(reference, reference)
        self.assertEqual(status, 0)
        self.assertTrue(report["equal"])

    def test_divergence_exits_one_and_writes_the_report(self) -> None:
        status, report = self.run_cli(trace(scan(0, Q=True)), trace(scan(0, Q=False)))
        self.assertEqual(status, 1)
        self.assertFalse(report["equal"])

    def test_shape_mismatch_exits_one(self) -> None:
        status, report = self.run_cli(trace(scan(0, Q=True)), trace(scan(0, N=1)))
        self.assertEqual(status, 1)
        self.assertEqual(len(report["shape_errors"]), 2)

    def test_unreadable_trace_exits_two_and_still_writes_the_report(self) -> None:
        status, report = self.run_cli(trace(scan(0, Q=True)), "not json")
        self.assertEqual(status, 2)
        self.assertFalse(report["equal"])
        self.assertEqual(report["divergences"], 1)

    def test_non_finite_number_is_unreadable(self) -> None:
        status, report = self.run_cli(trace(scan(0, X=1.0)), '{"scan_ms": 10, "outputs": ["X"], "scans": [{"t_ms": 0, "X": NaN}]}')
        self.assertEqual(status, 2)
        self.assertFalse(report["equal"])

    def test_trace_without_scans_is_unreadable(self) -> None:
        status, _ = self.run_cli(trace(scan(0, Q=True)), {"scan_ms": 10, "outputs": ["Q"]})
        self.assertEqual(status, 2)


if __name__ == "__main__":
    unittest.main()
