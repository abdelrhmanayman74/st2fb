"""The small syntax front-end: its rules on small inputs, and that it never sees the reference."""
import ast
import unittest
from pathlib import Path

from st2fb import vendor_frontend
from st2fb.llm import benchmark
from st2fb.translate import translate_source
from st2fb.vendor_frontend import FrontendError, iec_to_st, l5k_to_st, scl_to_st, to_plain_st

REPO = Path(__file__).resolve().parent.parent
HARD = REPO / "corpus_hard"

SCL_HEAD = """FUNCTION_BLOCK "FB_X"
TITLE = 'A title'
{ S7_Optimized_Access := 'TRUE' }
AUTHOR : someone
VERSION : 1.0
//A comment
   VAR_INPUT
      i_a : Bool;   // A note
      i_n : Int;
      i_r : Real;
   END_VAR
   VAR_OUTPUT
      o_b : Bool;
      o_r : Real;
      o_i : DInt;
      o_w : UInt;
   END_VAR
   VAR
      statT {InstructionName := 'IEC_TIMER'; LibVersion := '1.0'} : IEC_TIMER;
      statU {InstructionName := 'TON_TIME'; LibVersion := '1.0'} : TON_TIME;
   END_VAR
   VAR_TEMP
      tempW : Word;
   END_VAR
   VAR CONSTANT
      C_MAX : Int := 100;
   END_VAR
BEGIN
"""
SCL_TAIL = "\nEND_FUNCTION_BLOCK\n"


def scl(body: str) -> str:
    return scl_to_st(SCL_HEAD + body + SCL_TAIL)


class Scl(unittest.TestCase):
    def test_layout_goes_and_the_translator_can_read_what_is_left(self):
        text = scl("REGION Part\n  #o_b := #i_a;\nEND_REGION\n")
        for word in ("TITLE", "AUTHOR", "REGION", "BEGIN", "S7_Optimized", "#", '"', "//", "VAR CONSTANT", "VAR_TEMP", "IEC_TIMER", "TON_TIME", "Word"):
            self.assertNotIn(word, text)
        self.assertIn("FUNCTION_BLOCK FB_X", text)
        self.assertIn("o_b := i_a;", text)
        translate_source(text)

    def test_constants_are_inlined(self):
        self.assertIn("i_n = 100", scl("#o_b := #i_n = #C_MAX;\n"))

    def test_named_calls_become_what_the_dialect_says(self):
        self.assertIn("((INT_TO_REAL(i_n) - 0.0) / (100.0 - 0.0))", scl("#o_r := NORM_X(MIN := 0, VALUE := #i_n, MAX := #C_MAX);\n"))
        self.assertIn("(i_r * (2.0 - 1.0) + 1.0)", scl("#o_r := SCALE_X(MIN := 1.0, VALUE := #i_r, MAX := 2.0);\n"))
        self.assertIn("LIMIT(0.0, i_r, 1.0)", scl("#o_r := LIMIT(MN := 0.0, IN := #i_r, MX := 1.0);\n"))
        self.assertIn("MIN(i_r, 1.0)", scl("#o_r := MIN(IN1 := #i_r, IN2 := 1.0);\n"))
        self.assertIn("SEL(i_a, i_r, 0.0)", scl("#o_r := SEL(G := #i_a, IN0 := #i_r, IN1 := 0.0);\n"))
        self.assertIn("REAL_TO_DINT(i_r)", scl("#o_i := ROUND(#i_r);\n"))
        self.assertIn("((i_r) * (i_r))", scl("#o_r := SQR(#i_r);\n"))

    def test_nested_named_calls(self):
        self.assertIn("LIMIT(0.0, MAX(i_r, 2.0), 1.0)", scl("#o_r := LIMIT(MN := 0.0, IN := MAX(IN1 := #i_r, IN2 := 2.0), MX := 1.0);\n"))

    def test_timer_call_and_compound_assignment(self):
        text = scl("#statT.TON(IN := #i_a, PT := T#30ms);\n#o_i += 1;\n")
        self.assertIn("statT(IN := i_a, PT := T#30ms);", text)
        self.assertIn("o_i := o_i + 1;", text)

    def test_bits_read_and_written(self):
        text = scl("#tempW := 16#0000;\n#tempW.%X3 := #i_a;\n#o_b := #tempW.%X7;\n")
        self.assertIn("tempW := 0;", text)
        self.assertIn("IF i_a THEN tempW := tempW + 8; END_IF;", text)
        self.assertIn("((tempW / 128) MOD 2 = 1)", text)

    def test_return_at_the_top_becomes_an_else(self):
        text = scl("IF #i_a THEN\n  #o_b := TRUE;\n  RETURN;\nEND_IF;\n#o_i := 1;\n")
        self.assertNotIn("RETURN", text)
        self.assertLess(text.index("ELSE"), text.index("o_i := 1;"))
        translate_source(text)

    def test_a_return_it_cannot_rewrite_is_refused(self):
        with self.assertRaisesRegex(FrontendError, "RETURN"):
            scl("IF #i_a THEN\n  IF #i_n > 1 THEN\n    RETURN;\n  END_IF;\n#o_i := 1;\nELSE\n  #o_i := 2;\nEND_IF;\n")

    def test_arrays_of_structures_stay_arrays(self):
        text = scl_to_st(SCL_HEAD.replace("   VAR_TEMP", "   VAR\n      p : Array[1..3] of Struct\n         a : Bool;\n         b : DInt;\n      END_STRUCT;\n   END_VAR\n   VAR_TEMP") + "#o_b := #p[#i_n].a;\n" + SCL_TAIL)
        self.assertIn("p_a : ARRAY[1..3] OF BOOL;", text)
        self.assertIn("p_b : ARRAY[1..3] OF DINT;", text)
        self.assertIn("p_a[i_n]", text)
        with self.assertRaises(ValueError):
            translate_source(text)


L5K_HEAD = """ADD_ON_INSTRUCTION_DEFINITION Thing_AOI (Description := "A thing",
                                             Vendor := "someone")
	PARAMETERS
		Go : BOOL (Usage := Input);
		Rate : REAL (Usage := Input);
		TaskPeriodMs : DINT (Usage := Input);
		Word : DINT (Usage := Output);
		Out : BOOL (Usage := Output);
		Total : REAL (Usage := Output);
	END_PARAMETERS
	LOCAL_TAGS
		T : FBD_TIMER;
		C : FBD_COUNTER;
		S : FBD_ONESHOT;
		Latch : BOOL;
	END_LOCAL_TAGS
	ST_ROUTINE Logic
"""
L5K_TAIL = "\n	END_ST_ROUTINE\nEND_ADD_ON_INSTRUCTION_DEFINITION\n"


def l5k(body: str) -> str:
    return l5k_to_st(L5K_HEAD + body + L5K_TAIL)


class Logix(unittest.TestCase):
    def test_interface_and_members(self):
        text = l5k("// A comment\n/* Another */\nT.TimerEnable := Go;\nOut := T.DN;\n")
        self.assertIn("FUNCTION_BLOCK Thing_AOI", text)
        self.assertIn("VAR_INPUT\n  Go : BOOL;", text)
        self.assertIn("VAR_OUTPUT\n  Word : DINT;", text)
        self.assertIn("T_TimerEnable := Go;", text)
        self.assertIn("Out := T_DN;", text)
        self.assertNotIn("comment", text)
        translate_source(text)

    def test_instructions_follow_the_dialect_file(self):
        text = l5k("TONR(T);\nCTUD(C);\nOSRI(S);\n")
        self.assertIn("IF T_PREV AND NOT T_DN THEN", text)
        self.assertIn("T_ACC := T_ACC + TaskPeriodMs;", text)
        self.assertIn("IF C_CUEnable AND NOT C_PREV THEN", text)
        self.assertIn("C_DN := C_ACC >= C_PRE;", text)
        self.assertIn("S_OutputBit := S_InputBit AND NOT S_PREV;", text)

    def test_res_is_different_on_a_timer_and_a_counter(self):
        timer, counter = l5k("RES(T);\n"), l5k("RES(C);\n")
        self.assertIn("T_PREV := FALSE;", timer)
        self.assertNotIn("C_PREV := FALSE;", counter)
        self.assertIn("C_ACC := 0;", counter)

    def test_bits_and_boolean_literals(self):
        text = l5k("Word := 0;\nWord.2 := Go;\nOut := Word.5;\nLatch := 1;\nWord [:= 1;\n")
        self.assertIn("IF Go THEN Word := Word + 4; END_IF;", text)
        self.assertIn("((Word / 32) MOD 2 = 1)", text)
        self.assertIn("Latch := TRUE;", text)
        self.assertIn("Word := 1;", text)

    def test_implicit_conversion_only_inside_a_real_assignment(self):
        text = l5k("Total := Total + Rate * TaskPeriodMs / 1000.0;\nWord := TaskPeriodMs;\n")
        self.assertIn("DINT_TO_REAL(TaskPeriodMs)", text)
        self.assertIn("Word := TaskPeriodMs;", text)

    def test_not_an_add_on_instruction(self):
        with self.assertRaises(FrontendError):
            l5k_to_st("FUNCTION_BLOCK F\nEND_FUNCTION_BLOCK\n")


class Plain(unittest.TestCase):
    def test_usint_only(self):
        self.assertEqual(iec_to_st("x : USINT := 3;\ny : INT;\n"), "x : UINT := 3;\ny : INT;\n")

    def test_unknown_dialect(self):
        with self.assertRaises(FrontendError):
            to_plain_st("x", "ladder")


class Honesty(unittest.TestCase):
    def test_it_never_opens_a_file_or_names_the_reference(self):
        """It is a function of the source text alone, apart from its command line."""
        tree = ast.parse(Path(vendor_frontend.__file__).read_text(encoding="utf-8"))
        rewriting = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name != "main"]
        for function in rewriting:
            names = {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)} | {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
            self.assertFalse(names & {"open", "read_text", "Path", "glob"}, function.name)
        self.assertNotIn("reference.st\"", Path(vendor_frontend.__file__).read_text(encoding="utf-8"))

    def test_it_stays_small(self):
        self.assertLess(len(Path(vendor_frontend.__file__).read_text(encoding="utf-8").splitlines()), 320)

    def test_what_it_leaves_for_the_translator_to_reject(self):
        """It gets 11 of 12 vendor programs and one public one past the translator. It does not flatten or inline, so these stay rejected."""
        rejected = {}
        for name in ("unsupported_st", "siemens_scl", "rockwell_st", "stress", "public_st"):
            for case in benchmark.load_set(HARD / name):
                try:
                    translate_source(to_plain_st(case.source, case.dialect))
                except ValueError as exc:
                    rejected[case.name] = str(exc)
        self.assertEqual(sorted(rejected), [
            "p02_pi_controller", "s05_lead_lag_array", "u01_sensor_voting", "u02_valve_manifold", "u03_tank_strapping", "u04_alarm_ring", "u05_pump_duty_records", "u06_cascade_nested", "x01_pump_station",
        ])


if __name__ == "__main__":
    unittest.main()
