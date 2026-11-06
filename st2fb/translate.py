"""Baseline translator: one ST FUNCTION_BLOCK to one IEC 61499 Basic FB in the safe form of
docs/DESIGN.md (START -> RUN on REQ, RUN runs `scan` and emits CNF, RUN -> START on 1).

Standard FB instances are lowered to inline ST on internal variables. The bodies in STD_FBS are
copied from matiec's lib/ (timer.txt, counter.txt, edge_detection.txt, bistable.txt), because the
migrated FB is judged against matiec: same statements, same order, same state variables.

Usage: python3 -m st2fb.translate corpus/X/program.st --out build/X/X.fbt
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from . import fbt
from .fbt import V1_TYPES
from .st import (
    Assign, Binary, Call, Case, CaseBranch, Expr, FBCall, For, FunctionBlock, If, Member, Stmt, Unary,
    Var, VarDecl, While, parse_program, parse_statements, print_expr,
    print_statements,
)

SCAN_DT = "SCAN_DT"
# Plays the role of matiec's __CURRENT_TIME: advanced once per scan, before any timer runs.
SCAN_CLOCK = "ST2FB_NOW"


class TranslateError(ValueError):
    pass


@dataclass(frozen=True)
class StdFB:
    inputs: tuple[tuple[str, str], ...]
    outputs: tuple[tuple[str, str], ...]
    state: tuple[tuple[str, str], ...]
    body: str  # ST, using the names above. CURRENT_TIME is the shared scan clock.


_TIMER_INPUTS = (("IN", "BOOL"), ("PT", "TIME"))
_TIMER_OUTPUTS = (("Q", "BOOL"), ("ET", "TIME"))
_TIMER_STATE = (("STATE", "INT"), ("PREV_IN", "BOOL"), ("START_TIME", "TIME"))

STD_FBS: dict[str, StdFB] = {
    "R_TRIG": StdFB((("CLK", "BOOL"),), (("Q", "BOOL"),), (("M", "BOOL"),), """
        Q := CLK AND NOT M;
        M := CLK;
    """),
    "F_TRIG": StdFB((("CLK", "BOOL"),), (("Q", "BOOL"),), (("M", "BOOL"),), """
        Q := NOT CLK AND NOT M;
        M := NOT CLK;
    """),
    "SR": StdFB((("S1", "BOOL"), ("R", "BOOL")), (("Q1", "BOOL"),), (), """
        Q1 := S1 OR (NOT R AND Q1);
    """),
    "RS": StdFB((("S", "BOOL"), ("R1", "BOOL")), (("Q1", "BOOL"),), (), """
        Q1 := NOT R1 AND (S OR Q1);
    """),
    # matiec's CTU and CTD hold an R_TRIG instance CU_T / CD_T; it is flattened to two statements.
    "CTU": StdFB(
        (("CU", "BOOL"), ("R", "BOOL"), ("PV", "INT")), (("Q", "BOOL"), ("CV", "INT")),
        (("CU_T_Q", "BOOL"), ("CU_T_M", "BOOL")), """
        CU_T_Q := CU AND NOT CU_T_M;
        CU_T_M := CU;
        IF R THEN
          CV := 0;
        ELSIF CU_T_Q AND (CV < PV) THEN
          CV := CV + 1;
        END_IF;
        Q := CV >= PV;
    """),
    "CTD": StdFB(
        (("CD", "BOOL"), ("LD", "BOOL"), ("PV", "INT")), (("Q", "BOOL"), ("CV", "INT")),
        (("CD_T_Q", "BOOL"), ("CD_T_M", "BOOL")), """
        CD_T_Q := CD AND NOT CD_T_M;
        CD_T_M := CD;
        IF LD THEN
          CV := PV;
        ELSIF CD_T_Q AND (CV > 0) THEN
          CV := CV - 1;
        END_IF;
        Q := CV <= 0;
    """),
    "TP": StdFB(_TIMER_INPUTS, _TIMER_OUTPUTS, _TIMER_STATE, """
        IF (STATE = 0) AND NOT PREV_IN AND IN THEN
          STATE := 1;
          Q := TRUE;
          START_TIME := CURRENT_TIME;
        ELSIF STATE = 1 THEN
          IF START_TIME + PT <= CURRENT_TIME THEN
            STATE := 2;
            Q := FALSE;
            ET := PT;
          ELSE
            ET := CURRENT_TIME - START_TIME;
          END_IF;
        END_IF;
        IF (STATE = 2) AND NOT IN THEN
          ET := T#0s;
          STATE := 0;
        END_IF;
        PREV_IN := IN;
    """),
    "TON": StdFB(_TIMER_INPUTS, _TIMER_OUTPUTS, _TIMER_STATE, """
        IF (STATE = 0) AND NOT PREV_IN AND IN THEN
          STATE := 1;
          Q := FALSE;
          START_TIME := CURRENT_TIME;
        ELSE
          IF NOT IN THEN
            ET := T#0s;
            Q := FALSE;
            STATE := 0;
          ELSIF STATE = 1 THEN
            IF START_TIME + PT <= CURRENT_TIME THEN
              STATE := 2;
              Q := TRUE;
              ET := PT;
            ELSE
              ET := CURRENT_TIME - START_TIME;
            END_IF;
          END_IF;
        END_IF;
        PREV_IN := IN;
    """),
    "TOF": StdFB(_TIMER_INPUTS, _TIMER_OUTPUTS, _TIMER_STATE, """
        IF (STATE = 0) AND PREV_IN AND NOT IN THEN
          STATE := 1;
          START_TIME := CURRENT_TIME;
        ELSE
          IF IN THEN
            ET := T#0s;
            STATE := 0;
          ELSIF STATE = 1 THEN
            IF START_TIME + PT <= CURRENT_TIME THEN
              STATE := 2;
              ET := PT;
            ELSE
              ET := CURRENT_TIME - START_TIME;
            END_IF;
          END_IF;
        END_IF;
        Q := IN OR (STATE = 1);
        PREV_IN := IN;
    """),
}
_TIMERS = {"TON", "TOF", "TP"}
_PARSED_BODIES = {name: parse_statements(std.body) for name, std in STD_FBS.items()}


def _map_expr(expr: Expr, fn) -> Expr:
    """Rebuild an expression, applying fn to every Var and Member leaf."""
    if isinstance(expr, (Var, Member)):
        return fn(expr)
    if isinstance(expr, Unary):
        return Unary(expr.op, _map_expr(expr.operand, fn))
    if isinstance(expr, Binary):
        return Binary(expr.op, _map_expr(expr.left, fn), _map_expr(expr.right, fn))
    if isinstance(expr, Call):
        return Call(expr.name, tuple(_map_expr(arg, fn) for arg in expr.args))
    return expr


class _Lowering:
    """Rewrites the body of one FB: FB calls become statements, `T1.Q` becomes `T1_Q`."""

    def __init__(self, fb: FunctionBlock):
        self.instances: dict[str, tuple[str, str]] = {}  # UPPER name -> (spelling, std type)
        self.names: dict[str, str] = {}  # UPPER name -> spelling, for every variable
        self.internal: list[VarDecl] = []

        for decl in fb.inputs + fb.outputs + fb.locals:
            self._claim(decl.name)
        for decl in fb.locals:
            if decl.type in STD_FBS:
                if decl.initial is not None:
                    raise TranslateError(f"{decl.name}: an FB instance cannot have an initial value")
                self.instances[decl.name.upper()] = (decl.name, decl.type)
            elif decl.type in V1_TYPES:
                self.internal.append(decl)
            else:
                raise TranslateError(f"{decl.name}: type {decl.type} is outside the v1 subset")
        for decl in fb.inputs + fb.outputs:
            if decl.type not in V1_TYPES:
                raise TranslateError(f"{decl.name}: type {decl.type} is not allowed on the interface")

        self.uses_timers = any(kind in _TIMERS for _, kind in self.instances.values())
        if self.uses_timers:
            self._claim(SCAN_DT)
            self._declare(SCAN_CLOCK, "TIME")
        for spelling, kind in self.instances.values():
            std = STD_FBS[kind]
            for name, type_name in std.inputs + std.outputs + std.state:
                self._declare(f"{spelling}_{name}", type_name)

    def _claim(self, name: str) -> None:
        if name.upper() in self.names:
            raise TranslateError(f"duplicate or reserved variable name {name}")
        self.names[name.upper()] = name

    def _declare(self, name: str, type_name: str) -> None:
        self._claim(name)
        self.internal.append(VarDecl(name, type_name))

    def _resolve(self, node: Var | Member) -> Expr:
        if isinstance(node, Member):
            found = self.instances.get(node.base.upper())
            if found is None:
                raise TranslateError(f"{node.base} is not a standard FB instance")
            spelling, kind = found
            std = STD_FBS[kind]
            known = {name.upper(): name for name, _ in std.inputs + std.outputs}
            if node.field.upper() not in known:
                raise TranslateError(f"{kind} has no parameter {node.field}")
            return Var(f"{spelling}_{known[node.field.upper()]}")
        key = node.name.upper()
        if key in self.instances:
            raise TranslateError(f"FB instance {node.name} used as a value")
        if key not in self.names:
            raise TranslateError(f"undeclared variable {node.name}")
        return Var(self.names[key])

    def expr(self, expr: Expr) -> Expr:
        return _map_expr(expr, self._resolve)

    def statements(self, stmts: tuple[Stmt, ...]) -> tuple[Stmt, ...]:
        result: list[Stmt] = []
        for stmt in stmts:
            if isinstance(stmt, FBCall):
                result.extend(self._lower_call(stmt))
            else:
                result.append(self._statement(stmt))
        return tuple(result)

    def _statement(self, stmt: Stmt) -> Stmt:
        if isinstance(stmt, Assign):
            target = self._resolve(stmt.target)
            return Assign(target, self.expr(stmt.value), stmt.line)
        if isinstance(stmt, If):
            branches = tuple((self.expr(c), self.statements(b)) for c, b in stmt.branches)
            return If(branches, self.statements(stmt.else_body), stmt.line)
        if isinstance(stmt, Case):
            branches = tuple(CaseBranch(b.labels, self.statements(b.body)) for b in stmt.branches)
            return Case(self.expr(stmt.selector), branches, self.statements(stmt.else_body), stmt.line)
        if isinstance(stmt, For):
            var = self._resolve(Var(stmt.var))
            step = self.expr(stmt.step) if stmt.step is not None else None
            return For(var.name, self.expr(stmt.start), self.expr(stmt.stop), step,
                       self.statements(stmt.body), stmt.line)
        if isinstance(stmt, While):
            return While(self.expr(stmt.condition), self.statements(stmt.body), stmt.line)
        raise TypeError(f"unexpected statement {stmt!r}")

    def _lower_call(self, call: FBCall) -> list[Stmt]:
        found = self.instances.get(call.instance.upper())
        if found is None:
            raise TranslateError(f"line {call.line}: {call.instance} is not a standard FB instance")
        spelling, kind = found
        std = STD_FBS[kind]
        prefix = f"{spelling}_"
        inputs = {name.upper(): name for name, _ in std.inputs}
        outputs = {name.upper(): name for name, _ in std.outputs}

        # Inputs are latched in argument order, as in matiec's generated call. An omitted input
        # keeps its previous value, so nothing is emitted for it.
        lowered: list[Stmt] = []
        output_assigns: list[Stmt] = []
        positional = [name for name, _ in std.inputs]
        for index, arg in enumerate(call.args):
            if arg.name is None:
                if index >= len(positional):
                    raise TranslateError(f"line {call.line}: too many arguments for {kind}")
                name = positional[index]
            elif arg.is_output:
                if arg.name.upper() not in outputs or not isinstance(arg.value, (Var, Member)):
                    raise TranslateError(f"line {call.line}: bad output argument {arg.name} on {kind}")
                source = Var(prefix + outputs[arg.name.upper()])
                output_assigns.append(Assign(self._resolve(arg.value), source, call.line))
                continue
            elif arg.name.upper() in inputs:
                name = inputs[arg.name.upper()]
            else:
                raise TranslateError(f"line {call.line}: {kind} has no input {arg.name}")
            lowered.append(Assign(Var(prefix + name), self.expr(arg.value), call.line))

        lowered.extend(self._inline(_PARSED_BODIES[kind], std, prefix, call.line))
        lowered.extend(output_assigns)
        return lowered

    def _inline(self, stmts: tuple[Stmt, ...], std: StdFB, prefix: str, line: int) -> list[Stmt]:
        own = {name for name, _ in std.inputs + std.outputs + std.state}

        def rename(node: Var | Member) -> Expr:
            if node.name == "CURRENT_TIME":
                return Var(SCAN_CLOCK)
            if node.name not in own:
                raise AssertionError(f"library body uses unknown name {node.name}")
            return Var(prefix + node.name)

        def walk(body: tuple[Stmt, ...]) -> tuple[Stmt, ...]:
            result: list[Stmt] = []
            for stmt in body:
                if isinstance(stmt, Assign):
                    result.append(Assign(rename(stmt.target), _map_expr(stmt.value, rename), line))
                elif isinstance(stmt, If):
                    branches = tuple((_map_expr(c, rename), walk(b)) for c, b in stmt.branches)
                    result.append(If(branches, walk(stmt.else_body), line))
                else:
                    raise AssertionError(f"library bodies use only := and IF, not {stmt!r}")
            return tuple(result)

        return list(walk(stmts))


def translate(fb: FunctionBlock) -> fbt.FBType:
    lowering = _Lowering(fb)
    body = lowering.statements(fb.body)
    inputs = [fbt.VarDeclaration(d.name, d.type, _initial(d)) for d in fb.inputs]
    if lowering.uses_timers:
        inputs.append(fbt.VarDeclaration(SCAN_DT, "TIME"))
        body = (Assign(Var(SCAN_CLOCK), Binary("+", Var(SCAN_CLOCK), Var(SCAN_DT))),) + body
    outputs = [fbt.VarDeclaration(d.name, d.type, _initial(d)) for d in fb.outputs]
    internal = [fbt.VarDeclaration(d.name, d.type, _initial(d)) for d in lowering.internal]
    return fbt.FBType(
        name=fb.name,
        comment="Migrated from IEC 61131-3 ST",
        event_inputs=(fbt.Event("REQ", tuple(v.name for v in inputs)),),
        event_outputs=(fbt.Event("CNF", tuple(v.name for v in outputs)),),
        input_vars=tuple(inputs),
        output_vars=tuple(outputs),
        internal_vars=tuple(internal),
        states=(
            fbt.ECState("START", (), 0, 0),
            fbt.ECState("RUN", (fbt.ECAction("scan", "CNF"),), 400, 0),
        ),
        transitions=(
            fbt.ECTransition("START", "RUN", "REQ", 200, -60),
            fbt.ECTransition("RUN", "START", "1", 200, 60),
        ),
        algorithms=(fbt.Algorithm("scan", print_statements(body)),),
    )


def _initial(decl: VarDecl) -> str | None:
    return print_expr(decl.initial) if decl.initial is not None else None


def translate_source(source: str) -> fbt.FBType:
    return translate(parse_program(source))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Translate ST to a baseline IEC 61499 Basic FB")
    parser.add_argument("program", type=Path, help="program.st")
    parser.add_argument("--out", type=Path, required=True, help="output .fbt")
    args = parser.parse_args(argv)
    try:
        fb = translate_source(args.program.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"translate: {args.program}: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(fbt.write_fbt(fb), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
