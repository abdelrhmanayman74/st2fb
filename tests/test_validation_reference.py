"""Tests for st2fb.reference_run against real matiec. These need Docker.

The expected values are worked out by hand from the ST source and from lib/timer.txt in matiec,
not copied from a run, so that a broken harness cannot pass by agreeing with itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from st2fb.compare import compare_traces
from st2fb.reference_run import (
    CompileFailed,
    Container,
    IMAGE,
    BadInput,
    RunFailed,
    ensure_image,
    run_reference,
    scan_interface,
)

ROOT = Path(__file__).resolve().parent.parent
LATCH = ROOT / "corpus" / "00_latch"


def setUpModule() -> None:
    ensure_image()


def timer_program(kind: str) -> str:
    return f"""FUNCTION_BLOCK PROBE
VAR_INPUT
  IN : BOOL;
  PT : TIME;
END_VAR
VAR_OUTPUT
  Q : BOOL;
  ET : TIME;
END_VAR
VAR
  T1 : {kind};
END_VAR
  T1(IN := IN, PT := PT);
  Q := T1.Q;
  ET := T1.ET;
END_FUNCTION_BLOCK
"""


def run_timer(kind: str, pattern: str, pt_ms: int = 30, scan_ms: int = 10) -> tuple[list[int], list[int]]:
    """Feed a pattern such as '0111' to the IN of a timer. Returns the Q and ET columns."""
    stimulus = {"scan_ms": scan_ms, "scans": [{"IN": c == "1", "PT": pt_ms} for c in pattern]}
    trace = run_reference(timer_program(kind), stimulus)
    return [int(s["Q"]) for s in trace["scans"]], [s["ET"] for s in trace["scans"]]


class Latch(unittest.TestCase):
    def test_hand_calculated_trace(self) -> None:
        # Stimulus (S, R) and the expected result, line by line through the ST:
        #   0: (F, F) nothing set, Q stays F. PREV=F, so COUNT stays 0.
        #   1: (T, F) ELSIF S sets Q. Q AND NOT PREV, so COUNT=1. PREV=T.
        #   2: (F, F) Q holds T. PREV=T, no count.
        #   3: (F, T) R resets Q. PREV=F.
        #   4: (T, T) R has priority, Q stays F.
        #   5: (T, F) Q set, COUNT=2. PREV=T.
        #   6: (F, F) Q holds T, COUNT=2.
        stimulus = json.loads((LATCH / "stimulus.json").read_text())
        trace = run_reference((LATCH / "program.st").read_text(), stimulus)
        self.assertEqual(
            trace,
            {
                "source": "matiec",
                "scan_ms": 10,
                "outputs": ["Q", "COUNT"],
                "scans": [
                    {"t_ms": 0, "Q": False, "COUNT": 0},
                    {"t_ms": 10, "Q": True, "COUNT": 1},
                    {"t_ms": 20, "Q": True, "COUNT": 1},
                    {"t_ms": 30, "Q": False, "COUNT": 1},
                    {"t_ms": 40, "Q": False, "COUNT": 1},
                    {"t_ms": 50, "Q": True, "COUNT": 2},
                    {"t_ms": 60, "Q": True, "COUNT": 2},
                ],
            },
        )

    def test_cli_writes_identical_files_on_two_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            outputs = []
            for name in ("a.json", "b.json"):
                out = Path(directory) / "nested" / name
                command = [
                    sys.executable, "-m", "st2fb.reference_run",
                    "--st", str(LATCH / "program.st"),
                    "--stimulus", str(LATCH / "stimulus.json"),
                    "--out", str(out),
                ]  # fmt: skip
                subprocess.run(command, check=True, cwd=ROOT, capture_output=True)
                outputs.append(out.read_bytes())
            self.assertEqual(outputs[0], outputs[1])


    def test_shared_container_gives_the_same_trace(self) -> None:
        stimulus = json.loads((LATCH / "stimulus.json").read_text())
        text = (LATCH / "program.st").read_text()
        with Container() as container:
            self.assertEqual(run_reference(text, stimulus, container), run_reference(text, stimulus))


class TimerSemantics(unittest.TestCase):
    """The behaviour the SCAN_DT lowering has to reproduce. See docs/CORPUS.md."""

    def test_ton_q_rises_when_elapsed_reaches_pt_and_et_starts_at_zero(self) -> None:
        q, et = run_timer("TON", "0111110")
        self.assertEqual(q, [0, 0, 0, 0, 1, 1, 0])
        self.assertEqual(et, [0, 0, 10, 20, 30, 30, 0])

    def test_ton_restarts_after_a_short_pulse(self) -> None:
        q, et = run_timer("TON", "110111")
        self.assertEqual(q, [0, 0, 0, 0, 0, 0])
        self.assertEqual(et, [0, 10, 0, 0, 10, 20])

    def test_ton_with_in_true_on_the_first_scan_sees_a_rising_edge(self) -> None:
        q, et = run_timer("TON", "1111")
        self.assertEqual(q, [0, 0, 0, 1])
        self.assertEqual(et, [0, 10, 20, 30])

    def test_ton_with_zero_pt_still_takes_one_scan(self) -> None:
        q, et = run_timer("TON", "0111", pt_ms=0)
        self.assertEqual(q, [0, 0, 1, 1])
        self.assertEqual(et, [0, 0, 0, 0])

    def test_ton_pt_that_is_not_a_multiple_of_the_scan_rounds_up(self) -> None:
        q, et = run_timer("TON", "11111", pt_ms=25)
        self.assertEqual(q, [0, 0, 0, 1, 1])
        self.assertEqual(et, [0, 10, 20, 25, 25])

    def test_tof_holds_q_for_pt_after_the_falling_edge(self) -> None:
        q, et = run_timer("TOF", "01100001")
        self.assertEqual(q, [0, 1, 1, 1, 1, 1, 0, 1])
        self.assertEqual(et, [0, 0, 0, 0, 10, 20, 30, 0])

    def test_tof_is_cancelled_by_in_returning(self) -> None:
        q, et = run_timer("TOF", "101000")
        self.assertEqual(q, [1, 1, 1, 1, 1, 1])
        self.assertEqual(et, [0, 0, 0, 0, 10, 20])

    def test_tp_runs_for_pt_and_ignores_in_during_the_pulse(self) -> None:
        # IN drops at scan 2 and rises again at scan 3, inside the pulse. No retrigger.
        q, et = run_timer("TP", "0101000")
        self.assertEqual(q, [0, 1, 1, 1, 0, 0, 0])
        self.assertEqual(et, [0, 0, 10, 20, 0, 0, 0])

    def test_tp_et_holds_pt_until_in_falls(self) -> None:
        q, et = run_timer("TP", "011111000")
        self.assertEqual(q, [0, 1, 1, 1, 0, 0, 0, 0, 0])
        self.assertEqual(et, [0, 0, 10, 20, 30, 30, 0, 0, 0])

    def test_tp_with_in_high_over_expiry_needs_a_new_edge_to_retrigger(self) -> None:
        q, _ = run_timer("TP", "11111011")
        self.assertEqual(q, [1, 1, 1, 0, 0, 0, 1, 1])

    def test_timer_measures_absolute_time_so_a_skipped_call_still_counts(self) -> None:
        program = """FUNCTION_BLOCK SKIP
VAR_INPUT
  IN : BOOL;
  CALL : BOOL;
END_VAR
VAR_OUTPUT
  Q : BOOL;
  ET : TIME;
END_VAR
VAR
  T1 : TON;
END_VAR
  IF CALL THEN
    T1(IN := IN, PT := T#30ms);
  END_IF;
  Q := T1.Q;
  ET := T1.ET;
END_FUNCTION_BLOCK
"""
        calls = [1, 1, 0, 0, 0, 1, 1]
        stimulus = {"scan_ms": 10, "scans": [{"IN": True, "CALL": c == 1} for c in calls]}
        trace = run_reference(program, stimulus)
        # Started at t=0. ET at t=10 is 10. No calls at 20, 30, 40, so ET holds. At t=50 the
        # 50 ms of real elapsed time is past PT, so Q is set at once and ET becomes PT.
        self.assertEqual([s["ET"] for s in trace["scans"]], [0, 10, 10, 10, 10, 30, 30])
        self.assertEqual([s["Q"] for s in trace["scans"]], [False] * 5 + [True] * 2)

    def test_f_trig_fires_on_the_first_scan_when_clk_is_low(self) -> None:
        program = """FUNCTION_BLOCK FT
VAR_INPUT
  CLK : BOOL;
END_VAR
VAR_OUTPUT
  F : BOOL;
  R : BOOL;
END_VAR
VAR
  FE : F_TRIG;
  RE : R_TRIG;
END_VAR
  FE(CLK := CLK);
  RE(CLK := CLK);
  F := FE.Q;
  R := RE.Q;
END_FUNCTION_BLOCK
"""
        stimulus = {"scan_ms": 10, "scans": [{"CLK": c == "1"} for c in "001100"]}
        trace = run_reference(program, stimulus)
        # matiec: Q := NOT CLK AND NOT M; M := NOT CLK. M starts FALSE, so scan 0 fires.
        self.assertEqual([s["F"] for s in trace["scans"]], [True, False, False, False, True, False])
        self.assertEqual([s["R"] for s in trace["scans"]], [False, False, True, False, False, False])


class Types(unittest.TestCase):
    PROGRAM = """FUNCTION_BLOCK TYPES
VAR_INPUT
  A_BOOL : BOOL;
  A_INT : INT;
  A_DINT : DINT;
  A_UINT : UINT;
  A_REAL : REAL;
  A_TIME : TIME;
END_VAR
VAR_OUTPUT
  B_BOOL : BOOL;
  B_INT : INT;
  B_DINT : DINT;
  B_UINT : UINT;
  B_REAL : REAL;
  B_TIME : TIME;
END_VAR
  B_BOOL := NOT A_BOOL;
  B_INT := A_INT - 1;
  B_DINT := A_DINT + 1;
  B_UINT := A_UINT + 1;
  B_REAL := A_REAL * 2.0;
  B_TIME := A_TIME + T#1s;
END_FUNCTION_BLOCK
"""

    def test_every_v1_type_round_trips(self) -> None:
        stimulus = {
            "scan_ms": 10,
            "scans": [
                {"A_BOOL": True, "A_INT": -32767, "A_DINT": 2147483646, "A_UINT": 65534, "A_REAL": 1.5, "A_TIME": 2500},
                {"A_BOOL": False, "A_INT": 0, "A_DINT": -1, "A_UINT": 0, "A_REAL": 0.1, "A_TIME": 0},
            ],
        }
        self.assertEqual(
            run_reference(self.PROGRAM, stimulus)["scans"],
            [
                {"t_ms": 0, "B_BOOL": False, "B_INT": -32768, "B_DINT": 2147483647, "B_UINT": 65535, "B_REAL": 3.0, "B_TIME": 3500},
                {"t_ms": 10, "B_BOOL": True, "B_INT": -1, "B_DINT": 0, "B_UINT": 1, "B_REAL": 0.200000003, "B_TIME": 1000},
            ],
        )

    def test_time_arithmetic_and_comparison_in_source(self) -> None:
        program = """FUNCTION_BLOCK TIMES
VAR_INPUT
  A : TIME;
  B : TIME;
END_VAR
VAR_OUTPUT
  TOTAL : TIME;
  DIFFERENCE : TIME;
  LONGER : BOOL;
END_VAR
  TOTAL := A + B;
  DIFFERENCE := A - B;
  LONGER := A >= B;
END_FUNCTION_BLOCK
"""
        stimulus = {"scan_ms": 10, "scans": [{"A": 1500, "B": 700}, {"A": 700, "B": 700}, {"A": 1000, "B": 1500}]}
        self.assertEqual(
            run_reference(program, stimulus)["scans"],
            [
                {"t_ms": 0, "TOTAL": 2200, "DIFFERENCE": 800, "LONGER": True},
                {"t_ms": 10, "TOTAL": 1400, "DIFFERENCE": 0, "LONGER": True},
                {"t_ms": 20, "TOTAL": 2500, "DIFFERENCE": -500, "LONGER": False},
            ],
        )

    def test_real_is_always_a_json_float(self) -> None:
        program = "FUNCTION_BLOCK F\nVAR_OUTPUT X : REAL; END_VAR\n  X := 5.0;\nEND_FUNCTION_BLOCK\n"
        trace = run_reference(program, {"scan_ms": 10, "scans": [{}]})
        self.assertIsInstance(trace["scans"][0]["X"], float)
        self.assertIn("5.0", json.dumps(trace["scans"][0]))


class Failures(unittest.TestCase):
    PROGRAM = "FUNCTION_BLOCK F\nVAR_INPUT A : BOOL; END_VAR\nVAR_OUTPUT Q : BOOL; END_VAR\n  Q := A;\nEND_FUNCTION_BLOCK\n"

    def test_syntax_error_is_a_compile_failure(self) -> None:
        with self.assertRaises(CompileFailed):
            run_reference(self.PROGRAM.replace("Q := A;", "Q := := A;"), {"scan_ms": 10, "scans": [{"A": True}]})

    def test_type_error_is_a_compile_failure(self) -> None:
        with self.assertRaises(CompileFailed):
            run_reference(self.PROGRAM.replace("Q := A;", "Q := 5;"), {"scan_ms": 10, "scans": [{"A": True}]})

    def test_stimulus_must_list_every_input(self) -> None:
        with self.assertRaisesRegex(BadInput, "do not match"):
            run_reference(self.PROGRAM, {"scan_ms": 10, "scans": [{}]})

    def test_stimulus_must_not_list_unknown_inputs(self) -> None:
        with self.assertRaisesRegex(BadInput, "do not match"):
            run_reference(self.PROGRAM, {"scan_ms": 10, "scans": [{"A": True, "B": True}]})

    def test_bool_input_must_be_a_json_bool(self) -> None:
        with self.assertRaisesRegex(BadInput, "JSON bool"):
            run_reference(self.PROGRAM, {"scan_ms": 10, "scans": [{"A": 1}]})

    def test_integer_range_is_checked(self) -> None:
        program = "FUNCTION_BLOCK F\nVAR_INPUT A : INT; END_VAR\nVAR_OUTPUT Q : INT; END_VAR\n  Q := A;\nEND_FUNCTION_BLOCK\n"
        with self.assertRaisesRegex(BadInput, "out of range"):
            run_reference(program, {"scan_ms": 10, "scans": [{"A": 40000}]})

    def test_a_hang_is_a_run_failure(self) -> None:
        program = """FUNCTION_BLOCK F
VAR_OUTPUT Q : BOOL; END_VAR
  WHILE TRUE DO
    Q := TRUE;
  END_WHILE;
END_FUNCTION_BLOCK
"""
        with self.assertRaises(RunFailed):
            run_reference(program, {"scan_ms": 10, "scans": [{}]})

    def test_non_finite_real_is_a_run_failure(self) -> None:
        program = """FUNCTION_BLOCK F
VAR_INPUT A : REAL; END_VAR
VAR_OUTPUT X : REAL; END_VAR
  X := 1.0 / A;
END_FUNCTION_BLOCK
"""
        with self.assertRaisesRegex(RunFailed, "JSON cannot represent"):
            run_reference(program, {"scan_ms": 10, "scans": [{"A": 0.0}]})


class InterfaceScanner(unittest.TestCase):
    def test_reads_lists_comments_and_initial_values(self) -> None:
        interface = scan_interface(
            """(* FUNCTION_BLOCK NOT_THIS *)
FUNCTION_BLOCK REAL_ONE
VAR_INPUT
  A, B : BOOL;  (* C : INT; *)
  D : TIME := T#1s;
END_VAR
VAR_OUTPUT Q : REAL := 1.5; END_VAR
VAR X : INT; END_VAR
  Q := 0.0;
END_FUNCTION_BLOCK
"""
        )
        self.assertEqual(interface.fb_name, "REAL_ONE")
        self.assertEqual([(v.name, v.type) for v in interface.inputs], [("A", "BOOL"), ("B", "BOOL"), ("D", "TIME")])
        self.assertEqual([(v.name, v.type) for v in interface.outputs], [("Q", "REAL")])

    def test_types_outside_the_scope_are_refused(self) -> None:
        with self.assertRaisesRegex(BadInput, "v1 scope"):
            scan_interface("FUNCTION_BLOCK F\nVAR_INPUT A : STRING; END_VAR\nEND_FUNCTION_BLOCK\n")

    def test_two_blocks_are_refused(self) -> None:
        with self.assertRaisesRegex(BadInput, "exactly one"):
            scan_interface("FUNCTION_BLOCK A\nEND_FUNCTION_BLOCK\nFUNCTION_BLOCK B\nEND_FUNCTION_BLOCK\n")


class Corpus(unittest.TestCase):
    def test_every_program_is_deterministic_and_matches_the_contract(self) -> None:
        for directory in sorted((ROOT / "corpus").glob("*/program.st")):
            program = directory.parent
            with self.subTest(program=program.name):
                stimulus: dict[str, Any] = json.loads((program / "stimulus.json").read_text())
                text = (program / "program.st").read_text()
                first = run_reference(text, stimulus)
                self.assertTrue(compare_traces(first, run_reference(text, stimulus))["equal"])
                self.assertEqual(len(first["scans"]), len(stimulus["scans"]))
                self.assertEqual([s["t_ms"] for s in first["scans"]], [i * stimulus["scan_ms"] for i in range(len(stimulus["scans"]))])


class ImageName(unittest.TestCase):
    def test_image_pins_the_contract_commit(self) -> None:
        self.assertIn("3a41303", IMAGE)


if __name__ == "__main__":
    unittest.main()
