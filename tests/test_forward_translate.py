import tempfile
import unittest
from pathlib import Path

from st2fb import export_forte, fbt, translate
from st2fb.st import parse_statements

REPO = Path(__file__).resolve().parent.parent


def program(body: str, decls: str) -> str:
    return f"""FUNCTION_BLOCK F
VAR_INPUT i : BOOL; END_VAR
VAR_OUTPUT o : BOOL; c : INT; e : TIME; END_VAR
VAR {decls} END_VAR
{body}
END_FUNCTION_BLOCK"""


def scan_body(fb: fbt.FBType) -> str:
    return fb.algorithms[0].st


class LatchTests(unittest.TestCase):
    def setUp(self):
        self.fb = translate.translate_source((REPO / "corpus/00_latch/program.st").read_text())
        self.expected = fbt.read_fbt(REPO / "corpus/00_latch/expected.fbt")

    def test_same_structure_as_expected(self):
        for attribute in ("name", "event_inputs", "event_outputs", "input_vars", "output_vars",
                          "internal_vars", "states", "transitions"):
            self.assertEqual(getattr(self.fb, attribute), getattr(self.expected, attribute), attribute)

    def test_same_algorithm_semantics_as_expected(self):
        self.assertEqual(parse_statements(self.fb.algorithms[0].st),
                         parse_statements(self.expected.algorithms[0].st))

    def test_write_read_round_trip(self):
        self.assertEqual(fbt.parse_fbt(fbt.write_fbt(self.fb)).algorithms[0].st.strip(),
                         self.fb.algorithms[0].st.strip())
        self.assertEqual(fbt.parse_fbt(fbt.write_fbt(self.fb)).transitions, self.fb.transitions)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sub" / "LATCH.fbt"
            code = translate.main([str(REPO / "corpus/00_latch/program.st"), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(fbt.read_fbt(out).name, "LATCH")


class LoweringTests(unittest.TestCase):
    def lower(self, body: str, decls: str) -> fbt.FBType:
        return translate.translate_source(program(body, decls))

    def internal_names(self, fb: fbt.FBType) -> set[str]:
        return {v.name for v in fb.internal_vars}

    def test_no_timer_means_no_scan_dt(self):
        fb = self.lower("r(CLK := i); o := r.Q;", "r : R_TRIG;")
        self.assertNotIn("SCAN_DT", [v.name for v in fb.input_vars])
        self.assertNotIn(translate.SCAN_CLOCK, self.internal_names(fb))

    def test_timers_add_scan_dt_on_req(self):
        for kind in ("TON", "TOF", "TP"):
            fb = self.lower("t(IN := i, PT := T#100ms); o := t.Q; e := t.ET;", f"t : {kind};")
            self.assertEqual(fb.input_vars[-1], fbt.VarDeclaration("SCAN_DT", "TIME"), kind)
            self.assertIn("SCAN_DT", fb.event_inputs[0].with_vars)
            self.assertTrue(scan_body(fb).startswith("ST2FB_NOW := ST2FB_NOW + SCAN_DT;\n"), kind)

    def test_ton_body_matches_matiec(self):
        fb = self.lower("t(IN := i, PT := T#100ms); o := t.Q;", "t : TON;")
        expected = parse_statements("""
            ST2FB_NOW := ST2FB_NOW + SCAN_DT;
            t_IN := i;
            t_PT := T#100ms;
            IF t_STATE = 0 AND NOT t_PREV_IN AND t_IN THEN
              t_STATE := 1;
              t_Q := FALSE;
              t_START_TIME := ST2FB_NOW;
            ELSE
              IF NOT t_IN THEN
                t_ET := T#0s;
                t_Q := FALSE;
                t_STATE := 0;
              ELSIF t_STATE = 1 THEN
                IF t_START_TIME + t_PT <= ST2FB_NOW THEN
                  t_STATE := 2;
                  t_Q := TRUE;
                  t_ET := t_PT;
                ELSE
                  t_ET := ST2FB_NOW - t_START_TIME;
                END_IF;
              END_IF;
            END_IF;
            t_PREV_IN := t_IN;
            o := t_Q;
        """)
        self.assertEqual(parse_statements(scan_body(fb)), expected)

    def test_edges_and_bistables_match_matiec(self):
        cases = {
            "R_TRIG": ("CLK", "x_Q := x_CLK AND NOT x_M; x_M := x_CLK;"),
            "F_TRIG": ("CLK", "x_Q := NOT x_CLK AND NOT x_M; x_M := NOT x_CLK;"),
        }
        for kind, (arg, body) in cases.items():
            fb = self.lower(f"x({arg} := i);", f"x : {kind};")
            self.assertEqual(parse_statements(scan_body(fb)),
                             parse_statements(f"x_{arg} := i; {body}"), kind)
        fb = self.lower("x(S1 := i, R := FALSE);", "x : SR;")
        self.assertEqual(parse_statements(scan_body(fb)), parse_statements(
            "x_S1 := i; x_R := FALSE; x_Q1 := x_S1 OR (NOT x_R AND x_Q1);"))
        fb = self.lower("x(S := i, R1 := FALSE);", "x : RS;")
        self.assertEqual(parse_statements(scan_body(fb)), parse_statements(
            "x_S := i; x_R1 := FALSE; x_Q1 := NOT x_R1 AND (x_S OR x_Q1);"))

    def test_counters_match_matiec(self):
        fb = self.lower("x(CU := i, R := FALSE, PV := 3);", "x : CTU;")
        self.assertEqual(parse_statements(scan_body(fb)), parse_statements("""
            x_CU := i; x_R := FALSE; x_PV := 3;
            x_CU_T_Q := x_CU AND NOT x_CU_T_M;
            x_CU_T_M := x_CU;
            IF x_R THEN x_CV := 0;
            ELSIF x_CU_T_Q AND x_CV < x_PV THEN x_CV := x_CV + 1;
            END_IF;
            x_Q := x_CV >= x_PV;
        """))
        fb = self.lower("x(CD := i, LD := FALSE, PV := 3);", "x : CTD;")
        self.assertEqual(parse_statements(scan_body(fb)), parse_statements("""
            x_CD := i; x_LD := FALSE; x_PV := 3;
            x_CD_T_Q := x_CD AND NOT x_CD_T_M;
            x_CD_T_M := x_CD;
            IF x_LD THEN x_CV := x_PV;
            ELSIF x_CD_T_Q AND x_CV > 0 THEN x_CV := x_CV - 1;
            END_IF;
            x_Q := x_CV <= 0;
        """))

    def test_positional_and_output_arguments(self):
        fb = self.lower("x(i, T#5ms, Q => o, ET => e);", "x : TP;")
        statements = parse_statements(scan_body(fb))
        self.assertEqual(parse_statements("x_IN := i; x_PT := T#5ms;"), statements[1:3])
        self.assertEqual(parse_statements("o := x_Q; e := x_ET;"), statements[-2:])

    def test_call_inside_control_flow_and_member_write(self):
        fb = self.lower("x.PT := T#1s; IF i THEN x(IN := i); END_IF; c := 1;", "x : TON;")
        self.assertIn("  x_IN := i;", scan_body(fb))
        self.assertIn("x_PT := T#1s;", scan_body(fb))

    def test_case_insensitive_names(self):
        fb = self.lower("X(CLK := I); O := x.q;", "x : R_TRIG;")
        self.assertIn("x_CLK := i;", scan_body(fb))
        self.assertIn("o := x_Q;", scan_body(fb))

    def test_every_lowering_exports_cleanly(self):
        for kind, call in {
            "TON": "x(IN := i, PT := T#10ms);", "TOF": "x(IN := i, PT := T#10ms);",
            "TP": "x(IN := i, PT := T#10ms);", "R_TRIG": "x(CLK := i);", "F_TRIG": "x(CLK := i);",
            "CTU": "x(CU := i, R := FALSE, PV := 3);", "CTD": "x(CD := i, LD := FALSE, PV := 3);",
            "SR": "x(S1 := i, R := FALSE);", "RS": "x(S := i, R1 := FALSE);",
        }.items():
            files = export_forte.export_fb(self.lower(call, f"x : {kind};"))
            self.assertIn("alg_scan", files["F_fbt.cpp"], kind)

    def test_errors(self):
        bad = [
            ("x(FOO := i);", "x : TON;"),
            ("o := x.FOO;", "x : TON;"),
            ("o := y;", ""),
            ("o := x;", "x : TON;"),
            ("x(i);", "x : INT;"),
            ("", "x : LREAL;"),
            ("", "SCAN_DT : INT; x : TON;"),
            ("", "x : TON; x_Q : BOOL;"),
            ("", "ST2FB_NOW : TIME; x : TOF;"),
        ]
        for body, decls in bad:
            with self.assertRaises(translate.TranslateError, msg=f"{body} / {decls}"):
                self.lower(body, decls)


class ExporterTests(unittest.TestCase):
    """C++ text checks. Whether g++ accepts it is covered by tests/test_forward_e2e.py."""

    def fb_with(self, algorithm: str, condition: str = "REQ") -> fbt.FBType:
        latch = fbt.read_fbt(REPO / "corpus/00_latch/expected.fbt")
        return fbt.FBType(
            name=latch.name, event_inputs=latch.event_inputs, event_outputs=latch.event_outputs,
            input_vars=latch.input_vars, output_vars=latch.output_vars,
            internal_vars=latch.internal_vars + (fbt.VarDeclaration("X", "DINT"), fbt.VarDeclaration("T", "TIME")),
            states=latch.states,
            transitions=(fbt.ECTransition("START", "RUN", condition), latch.transitions[1]),
            algorithms=(fbt.Algorithm("scan", algorithm),),
        )

    def cpp(self, algorithm: str = "Q := TRUE;", condition: str = "REQ") -> str:
        return export_forte.export_fb(self.fb_with(algorithm, condition))["LATCH_fbt.cpp"]

    def test_generated_style(self):
        cpp = self.cpp("COUNT := COUNT + 1;")
        self.assertIn('DEFINE_FIRMWARE_FB(FORTE_LATCH, "st2fb::LATCH"_STRID)', cpp)
        self.assertIn("var_COUNT = func_ADD<CIEC_INT>(var_COUNT, 1_INT);", cpp)
        self.assertIn('#include "forte/iec61131_functions/func_ADD.h"', cpp)

    def test_guard_forms(self):
        self.assertIn("if ((scmEventREQID == paEIID) && (func_GT(var_COUNT, 3_INT)))", self.cpp(condition="REQ[COUNT > 3]"))
        self.assertIn("if (func_GT(var_COUNT, 3_INT))", self.cpp(condition="[COUNT > 3]"))
        self.assertIn("if (1)", self.cpp(condition="1"))
        self.assertIn("if (scmEventREQID == paEIID)", self.cpp(condition="REQ"))

    def test_guard_errors(self):
        for condition in ("NOPE[COUNT > 3]", "[COUNT]", "[UNKNOWN > 1]", "", "REQ["):
            with self.assertRaises(ValueError, msg=condition):
                self.cpp(condition=condition)

    def test_literal_typing(self):
        self.assertIn("var_X = func_ADD<CIEC_DINT>(var_X, 2_DINT);", self.cpp("X := X + 2;"))
        self.assertIn("func_GT(var_X, 2_DINT)", self.cpp("Q := X > 2;"))
        self.assertIn("var_T = 1500000000_TIME;", self.cpp("T := T#1.5s;"))
        self.assertIn("var_COUNT = (-5_INT);", self.cpp("COUNT := -5;"))

    def test_for_follows_matiec_shape(self):
        self.assertIn("for (var_COUNT = 1_INT; func_LE(var_COUNT, 3_INT); "
                      "var_COUNT = func_ADD<CIEC_INT>(var_COUNT, 1_INT)) {",
                      self.cpp("FOR COUNT := 1 TO 3 DO Q := TRUE; END_FOR;"))
        self.assertIn("func_GE(var_COUNT, 1_INT)", self.cpp("FOR COUNT := 3 TO 1 BY -1 DO Q := TRUE; END_FOR;"))
        self.assertIn("func_GT(var_COUNT, 0_INT) ? ", self.cpp("FOR COUNT := 1 TO 3 BY COUNT DO Q := TRUE; END_FOR;"))

    def test_widening_is_allowed_and_narrowing_rejected(self):
        self.assertIn("var_X = var_COUNT;", self.cpp("X := COUNT;"))
        with self.assertRaises(export_forte.ExportError):
            self.cpp("COUNT := X;")

    def test_type_errors(self):
        for algorithm in ("Q := 1 + T;", "T := T + 1;", "IF COUNT THEN Q := TRUE; END_IF;", "Q := T > 1;",
                          "T := 5;", "NOPE := 1;", "COUNT := FOO(1);", "t1(IN := Q);", "Q := t1.Q;"):
            with self.assertRaises(export_forte.ExportError, msg=algorithm):
                self.cpp(algorithm)

    def test_bad_ecc_is_rejected(self):
        latch = self.fb_with("Q := TRUE;")
        bad_transition = fbt.FBType(**{**latch.__dict__, "transitions": (fbt.ECTransition("START", "NOWHERE", "REQ"),)})
        with self.assertRaises(export_forte.ExportError):
            export_forte.export_fb(bad_transition)
        bad_action = fbt.FBType(**{**latch.__dict__, "states": (fbt.ECState("START", (fbt.ECAction("nope"),)),), "transitions": ()})
        with self.assertRaises(export_forte.ExportError):
            export_forte.export_fb(bad_action)

    def test_start_state_gets_index_zero(self):
        latch = self.fb_with("Q := TRUE;")
        swapped = fbt.FBType(**{**latch.__dict__, "states": tuple(reversed(latch.states))})
        header = export_forte.export_fb(swapped)["LATCH_fbt.h"]
        self.assertIn("scmStateSTART = 0;", header)
        self.assertIn("scmStateRUN = 1;", header)


if __name__ == "__main__":
    unittest.main()
