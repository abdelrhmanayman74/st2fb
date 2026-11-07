"""Recursive-descent parser for the v1 ST subset (see docs/DESIGN.md).

Expression precedence follows matiec's grammar, since matiec is the reference: a unary operator
applies to a primary and binds tighter than `**`, so `-2 ** 2` is `(-2) ** 2`.
"""
from __future__ import annotations

import re
from fractions import Fraction

from .ast import (
    Assign, Binary, BoolLit, Call, CallArg, Case, CaseBranch, CaseLabel, Expr, FBCall, For,
    FunctionBlock, If, IntLit, Member, RealLit, Stmt, TimeLit, Unary, Var, VarDecl, While,
)
from .lexer import STParseError, Token, tokenize

__all__ = ["STParseError", "parse_program", "parse_statements", "parse_expression", "parse_time_ns"]

_RESERVED = {
    "IF", "THEN", "ELSIF", "ELSE", "END_IF", "CASE", "OF", "END_CASE", "FOR", "TO", "BY", "DO",
    "END_FOR", "WHILE", "END_WHILE", "REPEAT", "UNTIL", "END_REPEAT", "EXIT", "RETURN", "AND",
    "OR", "XOR", "NOT", "MOD", "TRUE", "FALSE", "FUNCTION_BLOCK", "END_FUNCTION_BLOCK",
    "VAR_INPUT", "VAR_OUTPUT", "VAR", "END_VAR",
}
_UNSUPPORTED_STATEMENTS = {"REPEAT", "EXIT", "RETURN"}

_TIME_UNITS_NS = {
    "d": 86_400_000_000_000, "h": 3_600_000_000_000, "m": 60_000_000_000, "s": 1_000_000_000,
    "ms": 1_000_000, "us": 1_000, "ns": 1,
}
_TIME_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|us|ns|d|h|m|s)", re.IGNORECASE)


def parse_time_ns(body: str) -> int:
    """`1h2m3.5s` to integer nanoseconds. Exact (Fraction), because no time tolerance is allowed."""
    text = body.replace("_", "")
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    total = Fraction(0)
    pos = 0
    for match in _TIME_PART.finditer(text):
        if match.start() != pos:
            break
        total += Fraction(match.group(1)) * _TIME_UNITS_NS[match.group(2).lower()]
        pos = match.end()
    if pos != len(text) or not text:
        raise ValueError(f"bad TIME literal {body!r}")
    if total.denominator != 1:
        raise ValueError(f"TIME literal {body!r} is finer than a nanosecond")
    return sign * int(total)


def _int_value(text: str) -> int:
    clean = text.replace("_", "")
    if "#" in clean:
        base, digits = clean.split("#", 1)
        return int(digits, int(base))
    return int(clean)


class _Parser:
    def __init__(self, source: str):
        self.tokens = tokenize(source)
        self.pos = 0

    @property
    def tok(self) -> Token:
        return self.tokens[self.pos]

    def error(self, message: str) -> STParseError:
        return STParseError(message, self.tok.line, self.tok.column)

    def advance(self) -> Token:
        tok = self.tok
        self.pos += 1
        return tok

    def at_op(self, *ops: str) -> bool:
        return self.tok.kind == "OP" and self.tok.text in ops

    def at_kw(self, *words: str) -> bool:
        return self.tok.kind == "IDENT" and self.tok.upper in words

    def expect_op(self, op: str) -> Token:
        if not self.at_op(op):
            raise self.error(f"expected {op!r}, found {self.tok.text or 'end of input'!r}")
        return self.advance()

    def expect_kw(self, word: str) -> Token:
        if not self.at_kw(word):
            raise self.error(f"expected {word}, found {self.tok.text or 'end of input'!r}")
        return self.advance()

    def expect_name(self) -> str:
        if self.tok.kind != "IDENT" or self.tok.upper in _RESERVED:
            raise self.error(f"expected a name, found {self.tok.text or 'end of input'!r}")
        return self.advance().text

    def expect_end(self) -> None:
        if self.tok.kind != "END":
            raise self.error(f"unexpected {self.tok.text!r}")

    # Declarations

    def function_block(self) -> FunctionBlock:
        self.expect_kw("FUNCTION_BLOCK")
        name = self.expect_name()
        sections: dict[str, list[VarDecl]] = {"VAR_INPUT": [], "VAR_OUTPUT": [], "VAR": []}
        while self.at_kw(*sections):
            kind = self.advance().upper
            sections[kind].extend(self.var_section())
        if self.at_kw("VAR_IN_OUT", "VAR_TEMP", "VAR_EXTERNAL"):
            raise self.error(f"{self.tok.text} is outside the v1 subset")
        body = self.statements()
        self.expect_kw("END_FUNCTION_BLOCK")
        self.expect_end()
        return FunctionBlock(
            name, tuple(sections["VAR_INPUT"]), tuple(sections["VAR_OUTPUT"]),
            tuple(sections["VAR"]), body,
        )

    def var_section(self) -> list[VarDecl]:
        decls: list[VarDecl] = []
        while not self.at_kw("END_VAR"):
            names = [self.expect_name()]
            while self.at_op(","):
                self.advance()
                names.append(self.expect_name())
            self.expect_op(":")
            type_name = self.expect_name().upper()
            initial = None
            if self.at_op(":="):
                self.advance()
                initial = self.expression()
            self.expect_op(";")
            decls.extend(VarDecl(name, type_name, initial) for name in names)
        self.expect_kw("END_VAR")
        return decls

    # Statements

    def statements(self) -> tuple[Stmt, ...]:
        result: list[Stmt] = []
        while True:
            if self.at_op(";"):
                self.advance()
            elif self.at_kw(*_UNSUPPORTED_STATEMENTS):
                raise self.error(f"{self.tok.upper} is outside the v1 subset")
            elif self.at_kw("IF"):
                result.append(self.if_statement())
            elif self.at_kw("CASE"):
                result.append(self.case_statement())
            elif self.at_kw("FOR"):
                result.append(self.for_statement())
            elif self.at_kw("WHILE"):
                result.append(self.while_statement())
            elif self.tok.kind == "IDENT" and self.tok.upper not in _RESERVED:
                result.append(self.name_statement())
            else:
                return tuple(result)

    def name_statement(self) -> Stmt:
        line = self.tok.line
        name = self.expect_name()
        if self.at_op("("):
            args = self.fb_call_args()
            self.expect_op(";")
            return FBCall(name, args, line)
        target: Var | Member = Var(name)
        if self.at_op("."):
            self.advance()
            target = Member(name, self.expect_name())
        self.expect_op(":=")
        value = self.expression()
        self.expect_op(";")
        return Assign(target, value, line)

    def fb_call_args(self) -> tuple[CallArg, ...]:
        self.expect_op("(")
        args: list[CallArg] = []
        while not self.at_op(")"):
            ahead = self.tokens[self.pos + 1]
            if self.tok.kind == "IDENT" and ahead.kind == "OP" and ahead.text in (":=", "=>"):
                name = self.advance().text
                is_output = self.advance().text == "=>"
                args.append(CallArg(name, self.expression(), is_output))
            else:
                args.append(CallArg(None, self.expression()))
            if not self.at_op(")"):
                self.expect_op(",")
        self.expect_op(")")
        return tuple(args)

    def if_statement(self) -> If:
        line = self.expect_kw("IF").line
        branches = [self.if_branch()]
        else_body: tuple[Stmt, ...] = ()
        while self.at_kw("ELSIF"):
            self.advance()
            branches.append(self.if_branch())
        if self.at_kw("ELSE"):
            self.advance()
            else_body = self.statements()
        self.expect_kw("END_IF")
        self.expect_op(";")
        return If(tuple(branches), else_body, line)

    def if_branch(self) -> tuple[Expr, tuple[Stmt, ...]]:
        condition = self.expression()
        self.expect_kw("THEN")
        return condition, self.statements()

    def case_statement(self) -> Case:
        line = self.expect_kw("CASE").line
        selector = self.expression()
        self.expect_kw("OF")
        branches: list[CaseBranch] = []
        while not self.at_kw("ELSE", "END_CASE"):
            labels = [self.case_label()]
            while self.at_op(","):
                self.advance()
                labels.append(self.case_label())
            self.expect_op(":")
            branches.append(CaseBranch(tuple(labels), self.statements()))
        else_body: tuple[Stmt, ...] = ()
        if self.at_kw("ELSE"):
            self.advance()
            else_body = self.statements()
        self.expect_kw("END_CASE")
        self.expect_op(";")
        return Case(selector, tuple(branches), else_body, line)

    def case_label(self) -> CaseLabel:
        low, type_name = self.case_constant()
        if self.at_op(".."):
            self.advance()
            high, _ = self.case_constant()
            return CaseLabel(low, high, type_name)
        return CaseLabel(low, low, type_name)

    def case_constant(self) -> tuple[int, str | None]:
        sign = 1
        if self.at_op("-"):
            self.advance()
            sign = -1
        expr = self.primary()
        if not isinstance(expr, IntLit):
            raise self.error("a CASE label must be an integer constant")
        return sign * expr.value, expr.type

    def for_statement(self) -> For:
        line = self.expect_kw("FOR").line
        var = self.expect_name()
        self.expect_op(":=")
        start = self.expression()
        self.expect_kw("TO")
        stop = self.expression()
        step = None
        if self.at_kw("BY"):
            self.advance()
            step = self.expression()
        self.expect_kw("DO")
        body = self.statements()
        self.expect_kw("END_FOR")
        self.expect_op(";")
        return For(var, start, stop, step, body, line)

    def while_statement(self) -> While:
        line = self.expect_kw("WHILE").line
        condition = self.expression()
        self.expect_kw("DO")
        body = self.statements()
        self.expect_kw("END_WHILE")
        self.expect_op(";")
        return While(condition, body, line)

    # Expressions, lowest precedence first

    def expression(self) -> Expr:
        return self.binary_level(0)

    _LEVELS = (
        ("OR",), ("XOR",), ("AND", "&"), ("=", "<>"), ("<", ">", "<=", ">="), ("+", "-"),
        ("*", "/", "MOD"), ("**",),
    )

    def binary_level(self, level: int) -> Expr:
        if level == len(self._LEVELS):
            return self.unary()
        ops = self._LEVELS[level]
        left = self.binary_level(level + 1)
        while (self.tok.kind == "OP" and self.tok.text in ops) or (
            self.tok.kind == "IDENT" and self.tok.upper in ops
        ):
            op = self.advance().upper
            left = Binary("AND" if op == "&" else op, left, self.binary_level(level + 1))
        return left

    def unary(self) -> Expr:
        if self.at_op("-"):
            self.advance()
            return Unary("-", self.unary())
        if self.at_op("+"):
            self.advance()
            return self.unary()
        if self.at_kw("NOT"):
            self.advance()
            return Unary("NOT", self.unary())
        return self.primary()

    def primary(self) -> Expr:
        tok = self.tok
        if tok.kind == "INT" or tok.kind == "BASED":
            self.advance()
            return IntLit(_int_value(tok.text))
        if tok.kind == "REAL":
            self.advance()
            return RealLit(float(tok.text.replace("_", "")))
        if tok.kind == "TIME":
            self.advance()
            try:
                return TimeLit(parse_time_ns(tok.text.split("#", 1)[1]))
            except ValueError as exc:
                raise STParseError(str(exc), tok.line, tok.column) from exc
        if tok.kind == "TYPED":
            self.advance()
            return self.typed_literal(tok)
        if self.at_op("("):
            self.advance()
            inner = self.expression()
            self.expect_op(")")
            return inner
        if self.at_kw("TRUE", "FALSE"):
            return BoolLit(self.advance().upper == "TRUE")
        name = self.expect_name()
        if self.at_op("("):
            return Call(name.upper(), self.call_args())
        if self.at_op("."):
            self.advance()
            return Member(name, self.expect_name())
        return Var(name)

    def call_args(self) -> tuple[Expr, ...]:
        args = []
        for arg in self.fb_call_args():
            if arg.name is not None:
                raise self.error("named arguments in function calls are outside the v1 subset")
            args.append(arg.value)
        return tuple(args)

    def typed_literal(self, tok: Token) -> Expr:
        type_name, body = tok.text.split("#", 1)
        type_name = type_name.upper()
        clean = body.replace("_", "")
        try:
            if type_name == "BOOL":
                if clean.upper() in ("TRUE", "1"):
                    return BoolLit(True)
                if clean.upper() in ("FALSE", "0"):
                    return BoolLit(False)
                raise ValueError(f"bad BOOL literal {tok.text!r}")
            if type_name in ("REAL", "LREAL"):
                return RealLit(float(clean), type_name)
            return IntLit(_int_value(clean), type_name)
        except ValueError as exc:
            raise STParseError(f"bad literal {tok.text!r}", tok.line, tok.column) from exc


def parse_program(source: str) -> FunctionBlock:
    return _Parser(source).function_block()


def parse_statements(source: str) -> tuple[Stmt, ...]:
    parser = _Parser(source)
    result = parser.statements()
    parser.expect_end()
    return result


def parse_expression(source: str) -> Expr:
    parser = _Parser(source)
    result = parser.expression()
    parser.expect_end()
    return result
