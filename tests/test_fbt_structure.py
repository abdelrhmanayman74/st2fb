"""A misplaced InternalVars must be named as such, not reported later as undeclared variables."""
import unittest
from pathlib import Path

from st2fb import fbt
from st2fb.st import lexer
from st2fb.st.lexer import STParseError

REPO = Path(__file__).resolve().parent.parent
CANDIDATES = REPO / "results" / "benchmark_2026-11-06" / "candidates"
PROGRAM = "18_pump_station_rotation"


class MisplacedInternalVars(unittest.TestCase):
    def test_saved_sonnet_candidate_gets_the_real_reason(self):
        path = CANDIDATES / "claude-sonnet-5-5" / PROGRAM / "llm_only_r0.fbt"
        with self.assertRaisesRegex(fbt.FbtError, r"<InternalVars> must be inside <BasicFB>, not inside <InterfaceList>"):
            fbt.read_fbt(path)

    def test_block_in_both_places_is_rejected(self):
        path = CANDIDATES / "claude-sonnet-5-5" / PROGRAM / "llm_repair_r2.fbt"
        with self.assertRaisesRegex(fbt.FbtError, "InternalVars"):
            fbt.read_fbt(path)

    def test_correct_placement_is_accepted(self):
        parsed = fbt.read_fbt(CANDIDATES / "claude-opus-5-5" / PROGRAM / "llm_only_r0.fbt")
        self.assertTrue(parsed.internal_vars)


class ArrayMessage(unittest.TestCase):
    def test_array_says_it_is_out_of_scope(self):
        source = "FUNCTION_BLOCK T\nVAR A : ARRAY[0..1] OF BOOL; END_VAR\nEND_FUNCTION_BLOCK\n"
        tokenize = next(getattr(lexer, name) for name in ("tokenize", "lex", "tokens") if hasattr(lexer, name))
        with self.assertRaisesRegex(STParseError, "arrays are outside the v1 subset"):
            tokenize(source)


if __name__ == "__main__":
    unittest.main()
