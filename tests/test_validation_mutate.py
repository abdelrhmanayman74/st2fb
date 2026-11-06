"""Tests for st2fb.mutate. The last class runs real matiec and needs Docker."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from st2fb.compare import compare_traces
from st2fb.mutate import (
    all_mutants,
    fbt_mutants,
    main,
    select_mutants,
    st_mutants,
    tokenize,
)
from st2fb.reference_run import ensure_image, run_reference

ROOT = Path(__file__).resolve().parent.parent
LATCH = ROOT / "corpus" / "00_latch"


def texts(source: str, kind: str) -> set[str]:
    return {m.text for m in all_mutants(source) if m.kind == kind}


class Operators(unittest.TestCase):
    def test_operator_swaps(self) -> None:
        self.assertEqual(texts("X := A AND B;", "operator"), {"X := A OR B;"})
        self.assertEqual(texts("X := A + B;", "operator"), {"X := A - B;"})
        self.assertEqual(texts("X := A * B;", "operator"), {"X := A / B;"})

    def test_unary_minus_is_not_an_operator_swap(self) -> None:
        self.assertEqual(texts("X := -A;", "operator"), set())
        self.assertEqual(texts("IF X < -1.0 THEN Y := 1; END_IF;", "operator"), set())

    def test_comparison_boundaries(self) -> None:
        self.assertEqual(texts("X := A < B;", "boundary"), {"X := A <= B;"})
        self.assertEqual(texts("X := A >= B;", "boundary"), {"X := A > B;"})
        self.assertEqual(texts("X := A = B;", "boundary"), {"X := A <> B;"})

    def test_assignment_is_not_a_comparison(self) -> None:
        self.assertEqual(texts("X := A;", "boundary"), set())


class Constants(unittest.TestCase):
    def test_integer(self) -> None:
        self.assertEqual(texts("X := 5;", "constant"), {"X := 6;", "X := 4;"})

    def test_real(self) -> None:
        self.assertEqual(texts("X := 2.5;", "constant"), {"X := 3.5;", "X := 1.5;"})

    def test_time_steps_by_one_scan(self) -> None:
        self.assertEqual(texts("T(PT := T#50ms);", "constant"), {"T(PT := T#60ms);", "T(PT := T#40ms);"})
        self.assertEqual(texts("T(PT := T#2s);", "constant"), {"T(PT := T#2010ms);", "T(PT := T#1990ms);"})

    def test_bool(self) -> None:
        self.assertEqual(texts("X := TRUE;", "constant"), {"X := FALSE;"})

    def test_range_labels_are_not_real_numbers(self) -> None:
        self.assertEqual(
            [t.text for t in tokenize("4..6:")],
            ["4", "..", "6", ":"],
        )


class Structure(unittest.TestCase):
    def test_negated_conditions(self) -> None:
        self.assertEqual(texts("IF A THEN X := 1; END_IF;", "negate"), {"IF NOT (A) THEN X := 1; END_IF;"})
        self.assertEqual(texts("WHILE A DO X := 1; END_WHILE;", "negate"), {"WHILE NOT (A) DO X := 1; END_WHILE;"})

    def test_swapped_branches(self) -> None:
        self.assertEqual(
            texts("IF A THEN X := 1; ELSE X := 2; END_IF;", "swap"),
            {"IF A THEN X := 2; ELSE X := 1; END_IF;"},
        )
        self.assertEqual(
            texts("IF A THEN X := 1; ELSIF B THEN X := 2; END_IF;", "swap"),
            {"IF A THEN X := 2; ELSIF B THEN X := 1; END_IF;"},
        )

    def test_if_without_else_has_nothing_to_swap(self) -> None:
        self.assertEqual(texts("IF A THEN X := 1; END_IF;", "swap"), set())

    def test_case_else_is_not_an_if_branch(self) -> None:
        source = "IF A THEN CASE S OF 1: X := 1; ELSE X := 2; END_CASE; END_IF;"
        self.assertEqual(texts(source, "swap"), set())

    def test_removed_statements(self) -> None:
        source = "X := 1; T(IN := A, PT := B); IF A THEN Y := 2; END_IF;"
        self.assertEqual(
            texts(source, "remove"),
            {
                " T(IN := A, PT := B); IF A THEN Y := 2; END_IF;",
                "X := 1;  IF A THEN Y := 2; END_IF;",
                "X := 1; T(IN := A, PT := B); IF A THEN  END_IF;",
            },
        )

    def test_for_header_and_case_labels_are_not_statements(self) -> None:
        source = "FOR I := 1 TO 3 DO X := I; END_FOR; CASE S OF 1: Y := 1; END_CASE;"
        removed = {t for t in texts(source, "remove")}
        self.assertEqual(
            removed,
            {"FOR I := 1 TO 3 DO  END_FOR; CASE S OF 1: Y := 1; END_CASE;", "FOR I := 1 TO 3 DO X := I; END_FOR; CASE S OF 1:  END_CASE;"},
        )

    def test_comments_are_not_mutated(self) -> None:
        self.assertEqual(all_mutants("(* A AND 1 < 2 *) X := Y;")[0].kind, "remove")
        self.assertEqual(len(all_mutants("(* A AND 1 < 2 *) X := Y;")), 1)


class Selection(unittest.TestCase):
    def setUp(self) -> None:
        self.mutants = st_mutants((ROOT / "corpus" / "20_pump_station_supervisor" / "program.st").read_text())

    def test_same_seed_same_selection(self) -> None:
        self.assertEqual(select_mutants(self.mutants, 10, 7), select_mutants(self.mutants, 10, 7))

    def test_different_seed_different_selection(self) -> None:
        self.assertNotEqual(select_mutants(self.mutants, 10, 7), select_mutants(self.mutants, 10, 8))

    def test_every_kind_is_represented(self) -> None:
        kinds = {m.kind for m in select_mutants(self.mutants, 6, 7)}
        self.assertEqual(kinds, {"boundary", "constant", "negate", "operator", "remove", "swap"})

    def test_descriptions_are_unique(self) -> None:
        descriptions = [m.description for m in self.mutants]
        self.assertEqual(len(descriptions), len(set(descriptions)))

    def test_count_larger_than_available_returns_all(self) -> None:
        self.assertEqual(len(select_mutants(self.mutants, 100000, 7)), len(self.mutants))


class FileModes(unittest.TestCase):
    def test_st_mode_only_touches_the_body(self) -> None:
        source = (LATCH / "program.st").read_text()
        head = source[: source.rindex("END_VAR")]
        for mutant in st_mutants(source):
            self.assertTrue(mutant.text.startswith(head), mutant.description)
            self.assertNotEqual(mutant.text, source)

    def test_st_mode_reports_source_lines(self) -> None:
        source = (LATCH / "program.st").read_text()
        self.assertTrue(any(m.description.startswith("line 14:") for m in st_mutants(source)))

    def test_fbt_mode_only_touches_the_algorithm(self) -> None:
        source = (LATCH / "expected.fbt").read_text()
        head = source[: source.index("<![CDATA[")]
        mutants = fbt_mutants(source)
        self.assertGreater(len(mutants), 5)
        for mutant in mutants:
            self.assertTrue(mutant.text.startswith(head))
            self.assertIn("</ST>", mutant.text)

    def test_fbt_without_cdata_is_handled(self) -> None:
        source = '<FBType><Algorithm Name="a"><ST>IF A &lt; B THEN X := 1; END_IF;</ST></Algorithm></FBType>'
        kinds = {m.kind for m in fbt_mutants(source)}
        self.assertIn("boundary", kinds)

    def test_fbt_with_no_algorithm_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            fbt_mutants("<FBType/>")

    def test_cli_writes_mutants_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "m"
            status = main(["fbt", str(LATCH / "expected.fbt"), "--count", "5", "--seed", "1", "--out-dir", str(out)])
            self.assertEqual(status, 0)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(len(manifest), 5)
            self.assertTrue((out / manifest[0]["file"]).exists())


class CatchesRealBugs(unittest.TestCase):
    """End to end against matiec: a known bug must be caught, and the original must not be."""

    @classmethod
    def setUpClass(cls) -> None:
        ensure_image()
        cls.source = (LATCH / "program.st").read_text()
        cls.stimulus = json.loads((LATCH / "stimulus.json").read_text())
        cls.baseline = run_reference(cls.source, cls.stimulus)

    def test_flipped_priority_is_caught_at_the_right_scan(self) -> None:
        # At scan 4 both S and R are true: with S first, Q would be set, not reset.
        mutated = self.source.replace("IF R THEN\n    Q := FALSE;\n  ELSIF S THEN\n    Q := TRUE;", "IF S THEN\n    Q := TRUE;\n  ELSIF R THEN\n    Q := FALSE;")
        self.assertNotEqual(mutated, self.source)
        report = compare_traces(self.baseline, run_reference(mutated, self.stimulus))
        self.assertFalse(report["equal"])
        self.assertEqual(report["first_divergence"], {"scan": 4, "t_ms": 40, "output": "Q", "expected": False, "actual": True})

    def test_unchanged_program_is_equal(self) -> None:
        self.assertTrue(compare_traces(self.baseline, run_reference(self.source, self.stimulus))["equal"])


if __name__ == "__main__":
    unittest.main()
