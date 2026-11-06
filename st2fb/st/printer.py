"""AST back to ST source. Parentheses appear only where precedence needs them."""
from __future__ import annotations

from .ast import (
    Assign, Binary, BoolLit, Call, Case, CaseLabel, Expr, FBCall, For, If, IntLit, Member,
    RealLit, Stmt, TimeLit, Unary, Var, While,
)

_PRECEDENCE = {
    "OR": 1, "XOR": 2, "AND": 3, "=": 4, "<>": 4, "<": 5, ">": 5, "<=": 5, ">=": 5, "+": 6,
    "-": 6, "*": 7, "/": 7, "MOD": 7, "**": 8,
}
_UNARY_PRECEDENCE = 9
_ATOM_PRECEDENCE = 10


def print_time(nanoseconds: int) -> str:
    sign = "-" if nanoseconds < 0 else ""
    remaining = abs(nanoseconds)
    parts = []
    for unit, size in (("h", 3_600_000_000_000), ("m", 60_000_000_000), ("s", 1_000_000_000),
                       ("ms", 1_000_000), ("us", 1_000), ("ns", 1)):
        count, remaining = divmod(remaining, size)
        if count:
            parts.append(f"{count}{unit}")
    return f"T#{sign}{''.join(parts) or '0s'}"


def _precedence(expr: Expr) -> int:
    if isinstance(expr, Binary):
        return _PRECEDENCE[expr.op]
    if isinstance(expr, Unary):
        return _UNARY_PRECEDENCE
    return _ATOM_PRECEDENCE


def _wrapped(expr: Expr, minimum: int) -> str:
    text = print_expr(expr)
    return f"({text})" if _precedence(expr) < minimum else text


def print_expr(expr: Expr) -> str:
    if isinstance(expr, IntLit):
        return f"{expr.type}#{expr.value}" if expr.type else str(expr.value)
    if isinstance(expr, RealLit):
        text = repr(expr.value)
        return f"{expr.type}#{text}" if expr.type else text
    if isinstance(expr, BoolLit):
        return "TRUE" if expr.value else "FALSE"
    if isinstance(expr, TimeLit):
        return print_time(expr.nanoseconds)
    if isinstance(expr, Var):
        return expr.name
    if isinstance(expr, Member):
        return f"{expr.base}.{expr.field}"
    if isinstance(expr, Call):
        return f"{expr.name}({', '.join(print_expr(a) for a in expr.args)})"
    if isinstance(expr, Unary):
        operand = _wrapped(expr.operand, _UNARY_PRECEDENCE)
        return f"NOT {operand}" if expr.op == "NOT" else f"-{operand}"
    if isinstance(expr, Binary):
        level = _PRECEDENCE[expr.op]
        # All binary operators are left associative, so a right child at the same level needs ().
        return f"{_wrapped(expr.left, level)} {expr.op} {_wrapped(expr.right, level + 1)}"
    raise TypeError(f"cannot print {expr!r}")


def _print_label(label: CaseLabel) -> str:
    prefix = f"{label.type}#" if label.type else ""
    if label.low == label.high:
        return f"{prefix}{label.low}"
    return f"{prefix}{label.low}..{label.high}"


def _block(stmts: tuple[Stmt, ...], depth: int) -> list[str]:
    lines: list[str] = []
    for stmt in stmts:
        lines.extend(_statement(stmt, depth))
    return lines


def _statement(stmt: Stmt, depth: int) -> list[str]:
    pad = "  " * depth
    if isinstance(stmt, Assign):
        return [f"{pad}{print_expr(stmt.target)} := {print_expr(stmt.value)};"]
    if isinstance(stmt, If):
        lines: list[str] = []
        for index, (condition, body) in enumerate(stmt.branches):
            keyword = "IF" if index == 0 else "ELSIF"
            lines.append(f"{pad}{keyword} {print_expr(condition)} THEN")
            lines.extend(_block(body, depth + 1))
        if stmt.else_body:
            lines.append(f"{pad}ELSE")
            lines.extend(_block(stmt.else_body, depth + 1))
        lines.append(f"{pad}END_IF;")
        return lines
    if isinstance(stmt, Case):
        lines = [f"{pad}CASE {print_expr(stmt.selector)} OF"]
        for branch in stmt.branches:
            labels = ", ".join(_print_label(label) for label in branch.labels)
            lines.append(f"{pad}  {labels}:")
            lines.extend(_block(branch.body, depth + 2))
        if stmt.else_body:
            lines.append(f"{pad}  ELSE")
            lines.extend(_block(stmt.else_body, depth + 2))
        lines.append(f"{pad}END_CASE;")
        return lines
    if isinstance(stmt, For):
        by = f" BY {print_expr(stmt.step)}" if stmt.step is not None else ""
        lines = [f"{pad}FOR {stmt.var} := {print_expr(stmt.start)} TO {print_expr(stmt.stop)}{by} DO"]
        lines.extend(_block(stmt.body, depth + 1))
        lines.append(f"{pad}END_FOR;")
        return lines
    if isinstance(stmt, While):
        lines = [f"{pad}WHILE {print_expr(stmt.condition)} DO"]
        lines.extend(_block(stmt.body, depth + 1))
        lines.append(f"{pad}END_WHILE;")
        return lines
    if isinstance(stmt, FBCall):
        args = []
        for arg in stmt.args:
            text = print_expr(arg.value)
            args.append(text if arg.name is None
                        else f"{arg.name} {'=>' if arg.is_output else ':='} {text}")
        return [f"{pad}{stmt.instance}({', '.join(args)});"]
    raise TypeError(f"cannot print {stmt!r}")


def print_statements(stmts: tuple[Stmt, ...]) -> str:
    """Statements as text, one per line, with a trailing newline when non-empty."""
    lines = _block(stmts, 0)
    return "\n".join(lines) + "\n" if lines else ""
