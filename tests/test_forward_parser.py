import unittest
from pathlib import Path

from st2fb.st import (
    Assign, Binary, BoolLit, Case, CaseLabel, FBCall, For, If, IntLit, Member, RealLit, STParseError,
    TimeLit, Unary, Var, While, parse_expression, parse_program, parse_statements, print_expr,
    print_statements,
)
from st2fb.st.parser import parse_time_ns

REPO = Path(__file__).resolve().parent.parent


class TerminatorTests(unittest.TestCase):
    """matiec rejects a block without its semicolon, so the parser must too."""

    def test_block_without_semicolon_is_rejected(self):
        for text in (
            "IF a THEN x := 1; END_IF",
            "CASE a OF 1: x := 1; END_CASE",
            "FOR i := 1 TO 2 DO x := 1; END_FOR",
            "WHILE a DO x := 1; END_WHILE",
        ):
            with self.subTest(text), self.assertRaises(STParseError):
                parse_statements(text)

    def test_block_with_semicolon_is_accepted(self):
        self.assertEqual(len(parse_statements("IF a THEN x := 1; END_IF; y := 2;")), 2)


class ExpressionTests(unittest.TestCase):
    def test_precedence(self):
        self.assertEqual(
            parse_expression("a OR b AND NOT c"),
            Binary("OR", Var("a"), Binary("AND", Var("b"), Unary("NOT", Var("c")))),
        )
        self.assertEqual(
            parse_expression("1 + 2 * 3"),
            Binary("+", IntLit(1), Binary("*", IntLit(2), IntLit(3))),
        )
        self.assertEqual(
            parse_expression("a = b < c"),
            Binary("=", Var("a"), Binary("<", Var("b"), Var("c"))),
        )

    def test_unary_binds_tighter_than_power_as_in_matiec(self):
        self.assertEqual(
            parse_expression("-2 ** 2"),
            Binary("**", Unary("-", IntLit(2)), IntLit(2)),
        )

    def test_left_associative(self):
        self.assertEqual(
            parse_expression("a - b - c"),
            Binary("-", Binary("-", Var("a"), Var("b")), Var("c")),
        )

    def test_literals(self):
        self.assertEqual(parse_expression("16#FF"), IntLit(255))
        self.assertEqual(parse_expression("INT#-5"), IntLit(-5, "INT"))
        self.assertEqual(parse_expression("1_000"), IntLit(1000))
        self.assertEqual(parse_expression("1.5e3"), RealLit(1500.0))
        self.assertEqual(parse_expression("true"), BoolLit(True))
        self.assertEqual(parse_expression("T#100ms"), TimeLit(100_000_000))
        self.assertEqual(parse_expression("TIME#1m"), TimeLit(60_000_000_000))

    def test_time_is_exact(self):
        self.assertEqual(parse_time_ns("1h2m3.5s"), 3_723_500_000_000)
        self.assertEqual(parse_time_ns("-1ms"), -1_000_000)
        with self.assertRaises(ValueError):
            parse_time_ns("5parsecs")

    def test_member_access(self):
        self.assertEqual(parse_expression("T1.Q"), Member("T1", "Q"))

    def test_print_round_trip(self):
        for text in ("(a + b) * c", "a - (b - c)", "NOT (a AND b)", "-(a + 1)", "T#1h500ms",
                     "a AND (b OR c)", "ABS(x - 1) > 2.5", "(a = b) AND (c <> d)"):
            first = parse_expression(text)
            self.assertEqual(parse_expression(print_expr(first)), first, text)


class StatementTests(unittest.TestCase):
    def test_if_elsif_else(self):
        stmt, = parse_statements("IF a THEN x := 1; ELSIF b THEN x := 2; ELSE x := 3; END_IF;")
        self.assertIsInstance(stmt, If)
        self.assertEqual(len(stmt.branches), 2)
        self.assertEqual(stmt.else_body, (Assign(Var("x"), IntLit(3)),))

    def test_case_labels(self):
        stmt, = parse_statements("CASE s OF 1: x := 1; 2, 3: x := 2; 4..6: x := 3; -1: x := 4; ELSE x := 5; END_CASE;")
        self.assertIsInstance(stmt, Case)
        self.assertEqual([b.labels for b in stmt.branches], [
            (CaseLabel(1, 1),), (CaseLabel(2, 2), CaseLabel(3, 3)), (CaseLabel(4, 6),), (CaseLabel(-1, -1),),
        ])
        self.assertEqual(len(stmt.else_body), 1)

    def test_case_branch_with_several_statements(self):
        stmt, = parse_statements("CASE s OF 1: x := 1; y := 2; 2: z := 3; END_CASE;")
        self.assertEqual([len(b.body) for b in stmt.branches], [2, 1])

    def test_loops(self):
        loop, wait = parse_statements("FOR i := 0 TO 9 BY 2 DO x := i; END_FOR; WHILE a DO a := FALSE; END_WHILE;")
        self.assertIsInstance(loop, For)
        self.assertEqual((loop.var, loop.step), ("i", IntLit(2)))
        self.assertIsInstance(wait, While)

    def test_fb_call(self):
        stmt, = parse_statements("T1(IN := a, PT := T#1s, Q => b);")
        self.assertIsInstance(stmt, FBCall)
        self.assertEqual([(a.name, a.is_output) for a in stmt.args],
                         [("IN", False), ("PT", False), ("Q", True)])

    def test_keywords_are_case_insensitive(self):
        self.assertEqual(parse_statements("if a then x := 1; end_if;"),
                         parse_statements("IF a THEN x := 1; END_IF;"))

    def test_comments(self):
        self.assertEqual(parse_statements("(* a\nb *) x := 1; // end\n"),
                         (Assign(Var("x"), IntLit(1)),))

    def test_line_numbers_are_ignored_in_equality_but_kept(self):
        stmt, = parse_statements("\n\nx := 1;")
        self.assertEqual(stmt.line, 3)
        self.assertEqual(stmt, Assign(Var("x"), IntLit(1)))

    def test_print_round_trip(self):
        source = """
        IF a AND b THEN x := 1; ELSIF c THEN y := 2.5; ELSE z := T#1s; END_IF;
        CASE s OF 1: x := 1; 2, 3: x := 2; 4..6: x := 3; ELSE x := 4; END_CASE;
        FOR i := 0 TO 9 BY 2 DO x := i; END_FOR;
        WHILE a DO a := NOT a; END_WHILE;
        T1(IN := a, PT := T#1s, Q => b);
        """
        first = parse_statements(source)
        self.assertEqual(parse_statements(print_statements(first)), first)

    def test_errors_carry_a_position(self):
        with self.assertRaises(STParseError) as caught:
            parse_statements("x := ;\n")
        self.assertEqual(caught.exception.line, 1)
        with self.assertRaises(STParseError) as caught:
            parse_statements("x := 1;\ny = 2;")
        self.assertEqual(caught.exception.line, 2)

    def test_out_of_subset_statements_are_rejected(self):
        for text in ("RETURN;", "EXIT;", "REPEAT x := 1; UNTIL a END_REPEAT;"):
            with self.assertRaises(STParseError, msg=text):
                parse_statements(text)


class ProgramTests(unittest.TestCase):
    def test_latch(self):
        fb = parse_program((REPO / "corpus/00_latch/program.st").read_text())
        self.assertEqual(fb.name, "LATCH")
        self.assertEqual([d.name for d in fb.inputs], ["S", "R"])
        self.assertEqual([(d.name, d.type) for d in fb.outputs], [("Q", "BOOL"), ("COUNT", "INT")])
        self.assertEqual([d.name for d in fb.locals], ["PREV"])
        self.assertEqual(len(fb.body), 3)

    def test_multiple_names_and_initial_values(self):
        fb = parse_program("""
            FUNCTION_BLOCK F
            VAR A, B : INT := 3; T : time := T#5ms; END_VAR
            END_FUNCTION_BLOCK
        """)
        self.assertEqual([(d.name, d.type, d.initial) for d in fb.locals], [
            ("A", "INT", IntLit(3)), ("B", "INT", IntLit(3)), ("T", "TIME", TimeLit(5_000_000)),
        ])

    def test_trailing_text_is_rejected(self):
        with self.assertRaises(STParseError):
            parse_program("FUNCTION_BLOCK F END_FUNCTION_BLOCK FUNCTION_BLOCK G END_FUNCTION_BLOCK")


if __name__ == "__main__":
    unittest.main()
