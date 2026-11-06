"""Compare two trace.json files and write report.json.

    python3 -m st2fb.compare build/X/matiec.json build/X/forte.json --out build/X/report.json

The first trace is the reference ("expected"), the second the candidate ("actual").
Exit status: 0 traces equal, 1 traces differ (including shape mismatches), 2 a trace could not
be read at all. The report is written in all three cases.

Value rules, chosen so that a bug cannot hide behind JSON's loose typing:
- A JSON bool only equals the same JSON bool. Python's True == 1 must not pass.
- If the expected value is a JSON float it is a REAL, compared with a relative tolerance and no
  absolute floor, so expected 0.0 needs exactly 0.0. reference_run always writes REAL with a
  decimal point, so it decides the type even if the candidate wrote 5 for 5.0.
- Any other number (INT, DINT, UINT, TIME in ms) must be numerically exact.

report.json holds the contract fields plus one addition, "shape_errors": a list of structural
problems. Invariant: equal <=> divergences == 0 <=> first_divergence is None.
`divergences` counts value mismatches plus shape errors.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

DEFAULT_REAL_TOLERANCE = 1e-5


class TraceError(Exception):
    """A trace file is unreadable or is not a trace at all."""


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not a JSON number")


def load_trace(path: str | Path) -> dict[str, Any]:
    try:
        trace = json.loads(Path(path).read_text(), parse_constant=_reject_constant)
    except (OSError, ValueError) as exc:
        raise TraceError(f"{path}: {exc}") from exc
    if not isinstance(trace, dict):
        raise TraceError(f"{path}: top level is not an object")
    for key, kind in (("scan_ms", int), ("outputs", list), ("scans", list)):
        if not isinstance(trace.get(key), kind):
            raise TraceError(f"{path}: missing or invalid '{key}'")
    if not all(isinstance(scan, dict) for scan in trace["scans"]):
        raise TraceError(f"{path}: every entry of 'scans' must be an object")
    return trace


def values_equal(expected: Any, actual: Any, tolerance: float = DEFAULT_REAL_TOLERANCE) -> bool:
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        return math.isclose(expected, actual, rel_tol=tolerance, abs_tol=0.0)
    if isinstance(expected, int) and isinstance(actual, (int, float)):
        return expected == actual
    return False


def _divergence(scan: int, t_ms: Any, output: str | None, expected: Any, actual: Any) -> dict[str, Any]:
    return {"scan": scan, "t_ms": t_ms, "output": output, "expected": expected, "actual": actual}


def compare_traces(
    expected: dict[str, Any], actual: dict[str, Any], tolerance: float = DEFAULT_REAL_TOLERANCE
) -> dict[str, Any]:
    shape_errors: list[str] = []
    shape_first: list[dict[str, Any]] = []  # divergence record for each shape error
    scan_ms = expected["scan_ms"]

    if expected["scan_ms"] != actual["scan_ms"]:
        shape_errors.append(f"scan_ms differs: expected {expected['scan_ms']}, actual {actual['scan_ms']}")
        shape_first.append(_divergence(0, 0, None, f"scan_ms={expected['scan_ms']}", f"scan_ms={actual['scan_ms']}"))

    only_expected = [name for name in expected["outputs"] if name not in actual["outputs"]]
    only_actual = [name for name in actual["outputs"] if name not in expected["outputs"]]
    for name in only_expected:
        shape_errors.append(f"output '{name}' is missing from the actual trace")
        shape_first.append(_divergence(0, 0, name, "output declared", "output missing"))
    for name in only_actual:
        shape_errors.append(f"output '{name}' is not in the expected trace")
        shape_first.append(_divergence(0, 0, name, "output missing", "output declared"))

    n_expected, n_actual = len(expected["scans"]), len(actual["scans"])
    scans_compared = min(n_expected, n_actual)
    if n_expected != n_actual:
        shape_errors.append(f"scan count differs: expected {n_expected}, actual {n_actual}")
        shape_first.append(
            _divergence(scans_compared, scans_compared * scan_ms, None, f"{n_expected} scans", f"{n_actual} scans")
        )

    # Common outputs and scans are still compared, so a shape error does not hide an earlier
    # value divergence.
    common = [name for name in expected["outputs"] if name in actual["outputs"]]
    value_divergences = 0
    first_value: dict[str, Any] | None = None
    for i in range(scans_compared):
        exp_scan, act_scan = expected["scans"][i], actual["scans"][i]
        t_ms = i * scan_ms
        # The contract fixes t_ms, and there is no time tolerance. A wrong stamp in either
        # trace is reported, against the value the contract requires.
        for stamp in (exp_scan.get("t_ms"), act_scan.get("t_ms")):
            if stamp != t_ms or isinstance(stamp, (bool, float)):
                value_divergences += 1
                if first_value is None:
                    first_value = _divergence(i, t_ms, "t_ms", t_ms, stamp)
        for name in common:
            exp_value, act_value = exp_scan.get(name), act_scan.get(name)
            if name not in exp_scan or name not in act_scan or not values_equal(exp_value, act_value, tolerance):
                value_divergences += 1
                if first_value is None:
                    first_value = _divergence(i, t_ms, name, exp_value, act_value)

    first = first_value
    if first is None and shape_first:
        first = shape_first[0]
    divergences = value_divergences + len(shape_errors)
    return {
        "equal": divergences == 0,
        "scans_compared": scans_compared,
        "first_divergence": first,
        "divergences": divergences,
        "real_tolerance": tolerance,
        "shape_errors": shape_errors,
    }


def compare_files(
    expected_path: str | Path, actual_path: str | Path, tolerance: float = DEFAULT_REAL_TOLERANCE
) -> dict[str, Any]:
    """Compare two files. Raises TraceError if either is unreadable."""
    return compare_traces(load_trace(expected_path), load_trace(actual_path), tolerance)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a reference trace with a candidate trace.")
    parser.add_argument("expected", help="reference trace.json (matiec)")
    parser.add_argument("actual", help="candidate trace.json (FORTE)")
    parser.add_argument("--out", required=True, help="report.json to write")
    parser.add_argument("--real-tolerance", type=float, default=DEFAULT_REAL_TOLERANCE)
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = compare_files(args.expected, args.actual, args.real_tolerance)
    except TraceError as exc:
        report = {
            "equal": False,
            "scans_compared": 0,
            "first_divergence": _divergence(0, 0, None, "readable trace", str(exc)),
            "divergences": 1,
            "real_tolerance": args.real_tolerance,
            "shape_errors": [str(exc)],
        }
        out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"compare: unreadable trace: {exc}", file=sys.stderr)
        return 2

    out.write_text(json.dumps(report, indent=2) + "\n")
    if report["equal"]:
        print(f"EQUAL: {report['scans_compared']} scans compared")
        return 0
    print(f"DIFFERENT: {report['divergences']} divergences, first: {report['first_divergence']}", file=sys.stderr)
    for error in report["shape_errors"]:
        print(f"shape error: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
