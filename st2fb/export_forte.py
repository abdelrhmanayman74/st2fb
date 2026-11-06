"""Export a Basic FB (.fbt) to FORTE C++ in the style of FORTE's own generated FBs, for example
stdfblib/events/src/E_CTU_fbt.cpp and modules/IEC61131-3/src/iec61131/timers/FB_TP_LTIME_fbt.cpp.
The convenience evt_REQ/operator() members of those files are left out; nothing here calls them.

Any FB is handled the same way: several states, guarded transitions, several algorithms and
actions per state. Algorithm bodies and guards go through the ST parser, so a type error in LLM
output is reported as an ExportError rather than as a page of template errors from g++.

Usage: python3 -m st2fb.export_forte build/X/X.fbt --out build/X/forte_src
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import fbt
from .fbt import V1_TYPES
from .st import (
    Assign, Binary, BoolLit, Call, Case, CaseLabel, Expr, For, If, IntLit, Member, RealLit, Stmt,
    STParseError, TimeLit, Unary, Var, While, parse_expression, parse_statements,
)

NAMESPACE = "st2fb"
_NUMERIC = ("INT", "UINT", "DINT", "REAL")


class ExportError(ValueError):
    pass


def promote(left: str | None, right: str | None, context: str) -> str | None:
    """Result type of an arithmetic pair. None means an untyped literal, which adapts."""
    if left is None or right is None or left == right:
        return left or right
    pair = {left, right}
    if pair == {"INT", "DINT"} or pair == {"UINT", "DINT"}:
        return "DINT"
    if "REAL" in pair and pair <= set(_NUMERIC):
        return "REAL"
    raise ExportError(f"{context}: no implicit conversion between {left} and {right}")


_FUNC_OPS = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "**": "EXPT", "MOD": "MOD"}
_COMPARE_OPS = {"=": "EQ", "<>": "NE", "<": "LT", ">": "GT", "<=": "LE", ">=": "GE"}
_LOGIC_OPS = {"AND": "AND", "OR": "OR", "XOR": "XOR"}
# Standard functions whose result has the type of their (promoted) arguments.
_SAME_TYPE_FUNCS = {
    "ABS", "SQRT", "SIN", "COS", "TAN", "ASIN", "ACOS", "ATAN", "EXP", "LN", "LOG", "MIN", "MAX",
    "LIMIT", "MOVE",
}
_CONVERSION = re.compile(r"(BOOL|INT|DINT|UINT|REAL|TIME)_(TO|TRUNC)_(BOOL|INT|DINT|UINT|REAL|TIME)\Z")


@dataclass(frozen=True)
class _Symbol:
    cpp: str
    type: str


class _Algorithm:
    """Turns ST for one algorithm or guard into C++ expressions and statements."""

    def __init__(self, fb: fbt.FBType, symbols: dict[str, _Symbol], includes: set[str], context: str):
        self.fb = fb
        self.symbols = symbols
        self.includes = includes
        self.context = context
        self.counter = 0

    def symbol(self, name: str) -> _Symbol:
        found = self.symbols.get(name.upper())
        if found is None:
            raise ExportError(f"{self.context}: undeclared variable {name}")
        return found

    # Types

    def type_of(self, expr: Expr) -> str | None:
        if isinstance(expr, IntLit):
            return expr.type
        if isinstance(expr, RealLit):
            return expr.type or "REAL"
        if isinstance(expr, BoolLit):
            return "BOOL"
        if isinstance(expr, TimeLit):
            return "TIME"
        if isinstance(expr, Var):
            return self.symbol(expr.name).type
        if isinstance(expr, Member):
            raise ExportError(f"{self.context}: member access {expr.base}.{expr.field} is not "
                              "allowed here; standard FB instances must be lowered to internal "
                              "variables")
        if isinstance(expr, Unary):
            return "BOOL" if expr.op == "NOT" else self.type_of(expr.operand)
        if isinstance(expr, Binary):
            if expr.op in _COMPARE_OPS or expr.op in _LOGIC_OPS:
                return "BOOL"
            left, right = self.type_of(expr.left), self.type_of(expr.right)
            if "TIME" in (left, right):
                return self._time_arithmetic(expr.op, left, right)
            return promote(left, right, self.context)
        if isinstance(expr, Call):
            conversion = _CONVERSION.match(expr.name)
            if conversion:
                return conversion.group(3)
            if expr.name == "SEL" and len(expr.args) == 3:
                return promote(self.type_of(expr.args[1]), self.type_of(expr.args[2]), self.context)
            if expr.name in _SAME_TYPE_FUNCS and expr.args:
                result = None
                for arg in expr.args:
                    result = promote(result, self.type_of(arg), self.context)
                return result
            raise ExportError(f"{self.context}: unsupported function {expr.name}")
        raise TypeError(f"unknown expression {expr!r}")

    def _time_arithmetic(self, op: str, left: str | None, right: str | None) -> str:
        if op in ("+", "-") and left == right == "TIME":
            return "TIME"
        if op == "*" and {left, right} - {None} <= {"TIME", *_NUMERIC}:
            return "TIME"
        if op == "/" and left == "TIME" and right != "TIME":
            return "TIME"
        raise ExportError(f"{self.context}: operator {op} is not defined on {left} and {right}")

    # Expressions

    def expr(self, expr: Expr, want: str | None = None) -> str:
        """C++ for expr. `want` is the type an untyped literal should take here."""
        if isinstance(expr, IntLit):
            return self._int_literal(expr.value, expr.type or want or "DINT")
        if isinstance(expr, RealLit):
            type_name = expr.type or "REAL"
            self._datatype(type_name)
            return f"{expr.value!r}_{type_name}" if expr.value >= 0 else f"(-{-expr.value!r}_{type_name})"
        if isinstance(expr, BoolLit):
            self._datatype("BOOL")
            return "true_BOOL" if expr.value else "false_BOOL"
        if isinstance(expr, TimeLit):
            self._datatype("TIME")
            if expr.nanoseconds < 0:
                return f"(-{-expr.nanoseconds}_TIME)"
            return f"{expr.nanoseconds}_TIME"
        if isinstance(expr, Var):
            return self.symbol(expr.name).cpp
        if isinstance(expr, Unary):
            if expr.op == "NOT":
                return f"{self._func('NOT')}<CIEC_BOOL>({self.expr(expr.operand, 'BOOL')})"
            return self._negate(expr, want)
        if isinstance(expr, Binary):
            return self._binary(expr, want)
        if isinstance(expr, Call):
            return self._call(expr, want)
        raise ExportError(f"{self.context}: cannot translate {expr!r}")

    def _int_literal(self, value: int, type_name: str) -> str:
        if type_name == "TIME":
            raise ExportError(f"{self.context}: integer literal {value} used as TIME; write T#...")
        if type_name not in V1_TYPES:
            raise ExportError(f"{self.context}: type {type_name} is outside the v1 subset")
        self._datatype(type_name)
        text = f"{abs(value)}_{type_name}"
        return f"(-{text})" if value < 0 else text

    def _negate(self, expr: Unary, want: str | None) -> str:
        if isinstance(expr.operand, (IntLit, RealLit)):
            return f"(-{self.expr(expr.operand, want)})"
        return f"{self._func('MINUS')}({self.expr(expr.operand, want)})"

    def _binary(self, expr: Binary, want: str | None) -> str:
        left_type, right_type = self.type_of(expr.left), self.type_of(expr.right)
        if expr.op in _LOGIC_OPS:
            func = self._func(_LOGIC_OPS[expr.op])
            return f"{func}<CIEC_BOOL>({self.expr(expr.left, 'BOOL')}, {self.expr(expr.right, 'BOOL')})"
        if expr.op in _COMPARE_OPS:
            if "TIME" not in (left_type, right_type) and "BOOL" not in (left_type, right_type):
                promote(left_type, right_type, self.context)
            elif left_type and right_type and left_type != right_type:
                raise ExportError(f"{self.context}: cannot compare {left_type} with {right_type}")
            hint = left_type or right_type or "DINT"
            func = self._func(_COMPARE_OPS[expr.op])
            return f"{func}({self.expr(expr.left, hint)}, {self.expr(expr.right, hint)})"

        result = self.type_of(expr) or want or "DINT"
        # TIME * 2: FORTE defines this for any integer, so the plain literal becomes DINT.
        hint = "DINT" if result == "TIME" else result
        left = self.expr(expr.left, hint)
        right = self.expr(expr.right, hint)
        func = self._func(_FUNC_OPS[expr.op])
        if expr.op in ("+", "-", "*", "/"):  # The arithmetic ones check their template argument.
            self._datatype(result)
            return f"{func}<CIEC_{result}>({left}, {right})"
        return f"{func}({left}, {right})"

    def _call(self, expr: Call, want: str | None) -> str:
        result = self.type_of(expr) or want or "DINT"
        conversion = _CONVERSION.match(expr.name)
        if conversion:
            args = [self.expr(arg, conversion.group(1)) for arg in expr.args]
        elif expr.name == "SEL":
            args = [self.expr(expr.args[0], "BOOL"), self.expr(expr.args[1], result),
                    self.expr(expr.args[2], result)]
        else:
            args = [self.expr(arg, result) for arg in expr.args]
        return f"{self._func(expr.name)}({', '.join(args)})"

    def _func(self, name: str) -> str:
        self.includes.add(f"forte/iec61131_functions/func_{name}.h")
        if name == "LIMIT":  # func_LIMIT.h uses MIN and MAX without including them.
            self.includes.update(f"forte/iec61131_functions/func_{dep}.h" for dep in ("MIN", "MAX"))
        return f"func_{name}"

    def _datatype(self, type_name: str) -> None:
        self.includes.add(f"forte/datatypes/forte_{type_name.lower()}.h")

    # Statements

    def body(self, stmts: tuple[Stmt, ...], depth: int) -> list[str]:
        lines: list[str] = []
        for stmt in stmts:
            lines.extend(self.statement(stmt, depth))
        return lines

    def statement(self, stmt: Stmt, depth: int) -> list[str]:
        pad = "  " * depth
        lines = [f'#line {stmt.line} "{self.fb.name}.fbt"'] if stmt.line else []
        if isinstance(stmt, Assign):
            if not isinstance(stmt.target, Var):
                raise ExportError(f"{self.context}: assignment target must be a variable")
            target = self.symbol(stmt.target.name)
            self._check_assignable(target.type, stmt.value)
            lines.append(f"{pad}{target.cpp} = {self.expr(stmt.value, target.type)};")
        elif isinstance(stmt, If):
            for index, (condition, branch) in enumerate(stmt.branches):
                self._require_bool(condition)
                head = "if" if index == 0 else "} else if"
                lines.append(f"{pad}{head} ({self.expr(condition, 'BOOL')}) {{")
                lines.extend(self.body(branch, depth + 1))
            if stmt.else_body:
                lines.append(f"{pad}}} else {{")
                lines.extend(self.body(stmt.else_body, depth + 1))
            lines.append(f"{pad}}}")
        elif isinstance(stmt, Case):
            lines.extend(self._case(stmt, depth))
        elif isinstance(stmt, For):
            lines.extend(self._for(stmt, depth))
        elif isinstance(stmt, While):
            self._require_bool(stmt.condition)
            lines.append(f"{pad}while ({self.expr(stmt.condition, 'BOOL')}) {{")
            lines.extend(self.body(stmt.body, depth + 1))
            lines.append(f"{pad}}}")
        else:
            raise ExportError(f"{self.context}: FB calls are not allowed in a Basic FB algorithm; "
                              "lower standard FBs to internal variables")
        return lines

    def _case(self, stmt: Case, depth: int) -> list[str]:
        # An if chain, not a C++ switch: it handles ranges directly and keeps every comparison in
        # FORTE's func_EQ style. The selector is evaluated once, as ST requires.
        pad = "  " * depth
        type_name = self.type_of(stmt.selector) or "DINT"
        if type_name not in ("INT", "DINT", "UINT"):
            raise ExportError(f"{self.context}: CASE selector must be an integer, not {type_name}")
        self.counter += 1
        selector = f"st_case_{self.counter}"
        lines = [f"{pad}{{", f"{pad}  const CIEC_{type_name} {selector} = {self.expr(stmt.selector, type_name)};"]
        keyword = "if"
        for branch in stmt.branches:
            condition = None
            for label in branch.labels:
                test = self._label_test(selector, type_name, label)
                condition = test if condition is None else f"{self._func('OR')}<CIEC_BOOL>({condition}, {test})"
            lines.append(f"{pad}  {keyword} ({condition}) {{")
            lines.extend(self.body(branch.body, depth + 2))
            keyword = "} else if"
        if stmt.else_body:
            if stmt.branches:
                lines.append(f"{pad}  }} else {{")
                lines.extend(self.body(stmt.else_body, depth + 2))
            else:
                lines.extend(self.body(stmt.else_body, depth + 1))
        if stmt.branches:
            lines.append(f"{pad}  }}")
        lines.append(f"{pad}}}")
        return lines

    def _label_test(self, selector: str, type_name: str, label: CaseLabel) -> str:
        low = self._int_literal(label.low, label.type or type_name)
        if label.low == label.high:
            return f"{self._func('EQ')}({selector}, {low})"
        high = self._int_literal(label.high, label.type or type_name)
        return (f"{self._func('AND')}<CIEC_BOOL>({self._func('GE')}({selector}, {low}), "
                f"{self._func('LE')}({selector}, {high}))")

    def _for(self, stmt: For, depth: int) -> list[str]:
        # Written out the way matiec generates it (generate_c_st.cc), not with FORTE's ST_FOR_ITER:
        # matiec re-evaluates TO and BY before every iteration and ST_FOR_ITER only once, so a body
        # that changes a variable used in TO would otherwise diverge from the reference.
        pad = "  " * depth
        counter = self.symbol(stmt.var)
        if counter.type not in ("INT", "DINT", "UINT"):
            raise ExportError(f"{self.context}: FOR counter {stmt.var} must be an integer")
        step = stmt.step if stmt.step is not None else IntLit(1)
        self._check_assignable(counter.type, step)
        self._check_assignable(counter.type, stmt.start)
        self._datatype(counter.type)
        start = self.expr(stmt.start, counter.type)
        stop = self.expr(stmt.stop, counter.type)
        step_cpp = self.expr(step, counter.type)
        up = f"{self._func('LE')}({counter.cpp}, {stop})"
        down = f"{self._func('GE')}({counter.cpp}, {stop})"
        constant = _constant_int(step)
        if constant is None:
            condition = f"{self._func('GT')}({step_cpp}, 0_{counter.type}) ? {up} : {down}"
        else:
            condition = up if constant > 0 else down
        increment = f"{self._func('ADD')}<CIEC_{counter.type}>({counter.cpp}, {step_cpp})"
        lines = [f"{pad}for ({counter.cpp} = {start}; {condition}; {counter.cpp} = {increment}) {{"]
        lines.extend(self.body(stmt.body, depth + 1))
        lines.append(f"{pad}}}")
        return lines

    def _check_assignable(self, target_type: str, value: Expr) -> None:
        value_type = self.type_of(value)
        if value_type is None or value_type == target_type:
            return
        if {value_type, target_type} <= set(_NUMERIC) and promote(value_type, target_type, self.context) == target_type:
            return
        raise ExportError(f"{self.context}: cannot assign {value_type} to {target_type}")

    def _require_bool(self, condition: Expr) -> None:
        found = self.type_of(condition)
        if found != "BOOL":
            raise ExportError(f"{self.context}: condition has type {found}, expected BOOL")


def _constant_int(expr: Expr) -> int | None:
    if isinstance(expr, IntLit):
        return expr.value
    if isinstance(expr, Unary) and expr.op == "-" and isinstance(expr.operand, IntLit):
        return -expr.operand.value
    return None


_GUARD = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)?\s*\[(.*)\]\s*\Z", re.DOTALL)


class _Exporter:
    def __init__(self, fb: fbt.FBType):
        self.fb = fb
        self.includes: set[str] = {"forte/forte_st_util.h"}
        self.symbols: dict[str, _Symbol] = {}
        self.event_ids = {e.name: index for index, e in enumerate(fb.event_inputs)}
        self.output_ids = {e.name: index for index, e in enumerate(fb.event_outputs)}
        for var in fb.input_vars + fb.output_vars + fb.internal_vars:
            if var.type not in V1_TYPES:
                raise ExportError(f"{var.name}: type {var.type} is outside the v1 subset")
            if var.name.upper() in self.symbols:
                raise ExportError(f"duplicate variable {var.name}")
            self.symbols[var.name.upper()] = _Symbol(f"var_{var.name}", var.type)
            self.includes.add(f"forte/datatypes/forte_{var.type.lower()}.h")
        self.states = self._ordered_states()
        self._validate()

    def _ordered_states(self) -> list[fbt.ECState]:
        # FORTE starts every ECC in state 0, so the initial state gets index 0.
        if not self.fb.states:
            raise ExportError("the ECC has no states")
        first = next((s for s in self.fb.states if s.name == "START"), self.fb.states[0])
        return [first] + [s for s in self.fb.states if s is not first]

    def _validate(self) -> None:
        shared = set(self.event_ids) & set(self.output_ids)
        if shared:
            raise ExportError(f"event names used as both input and output: {sorted(shared)}")
        names = {s.name for s in self.states}
        algorithms = {a.name for a in self.fb.algorithms}
        for tr in self.fb.transitions:
            for end in (tr.source, tr.destination):
                if end not in names:
                    raise ExportError(f"transition refers to unknown state {end!r}")
        for state in self.states:
            for action in state.actions:
                if action.algorithm and action.algorithm not in algorithms:
                    raise ExportError(f"state {state.name}: unknown algorithm {action.algorithm!r}")
                if action.output and action.output not in self.output_ids:
                    raise ExportError(f"state {state.name}: unknown output event {action.output!r}")
        for event, indexed in ((self.fb.event_inputs, self.fb.input_vars), (self.fb.event_outputs, self.fb.output_vars)):
            known = {v.name for v in indexed}
            for item in event:
                for var in item.with_vars:
                    if var not in known:
                        raise ExportError(f"event {item.name}: With refers to unknown variable {var!r}")

    # Pieces of ST

    def _literal(self, var: fbt.VarDeclaration) -> str:
        if var.initial is None:
            return f"0_{var.type}"
        translator = _Algorithm(self.fb, self.symbols, self.includes, f"initial value of {var.name}")
        try:
            expr = parse_expression(var.initial)
        except STParseError as exc:
            raise ExportError(f"initial value of {var.name}: {exc}") from exc
        translator._check_assignable(var.type, expr)
        return translator.expr(expr, var.type)

    def _guard(self, condition: str) -> str:
        context = f"guard {condition!r}"
        if not condition:
            raise ExportError("transition with an empty condition")
        if condition.strip() in ("1", "TRUE", "true"):
            return "1"
        translator = _Algorithm(self.fb, self.symbols, self.includes, context)
        matched = _GUARD.match(condition)
        try:
            if matched:
                event, guard = matched.group(1), parse_expression(matched.group(2))
                translator._require_bool(guard)
                guard_cpp = translator.expr(guard, "BOOL")
                if event is None:
                    return guard_cpp
                return f"({self._event_test(event, context)}) && ({guard_cpp})"
            if condition.strip() in self.event_ids:
                return self._event_test(condition.strip(), context)
            expr = parse_expression(condition)
        except STParseError as exc:
            raise ExportError(f"{context}: {exc}") from exc
        translator._require_bool(expr)
        return translator.expr(expr, "BOOL")

    def _event_test(self, event: str, context: str) -> str:
        if event not in self.event_ids:
            raise ExportError(f"{context}: unknown event {event}")
        return f"scmEvent{event}ID == paEIID"

    def _algorithm_body(self, algorithm: fbt.Algorithm) -> list[str]:
        translator = _Algorithm(self.fb, self.symbols, self.includes, f"algorithm {algorithm.name}")
        try:
            stmts = parse_statements(algorithm.st)
        except STParseError as exc:
            raise ExportError(f"algorithm {algorithm.name}: {exc}") from exc
        return translator.body(stmts, 2)

    # Files

    def header(self) -> str:
        fb = self.fb
        cls = f"FORTE_{fb.name}"
        lines = ["#pragma once", "", '#include "forte/basicfb.h"']
        lines += [f'#include "{inc}"' for inc in sorted(self.includes) if "datatypes" in inc]
        lines += ['#include "forte/forte_st_util.h"', "", f"namespace forte::{NAMESPACE} {{"]
        lines += [f"  class {cls} final : public CBasicFB {{", f"      DECLARE_FIRMWARE_FB({cls})", "", "    private:"]
        lines += [f"      static const TEventID scmEvent{e.name}ID = {i};" for i, e in enumerate(fb.event_inputs)]
        lines += [f"      static const TEventID scmEvent{e.name}ID = {i};" for i, e in enumerate(fb.event_outputs)]
        lines.append("")
        lines += [f"      CIEC_{v.type} var_{v.name};" for v in fb.internal_vars]
        lines += ["", "      CIEC_ANY *getVarInternal(size_t) override;", ""]
        lines += [f"      void alg_{a.name}(void);" for a in fb.algorithms]
        lines.append("")
        lines += [f"      static const TForteInt16 scmState{s.name} = {i};" for i, s in enumerate(self.states)]
        lines.append("")
        lines += [f"      void enterState{s.name}(CEventChainExecutionThread *const paECET);" for s in self.states]
        lines += [
            "",
            "      void executeEvent(TEventID paEIID, CEventChainExecutionThread *const paECET) override;",
            "",
            "      void readInputData(TEventID paEIID) override;",
            "      void writeOutputData(TEventID paEIID) override;",
            "      void setInitialValues() override;",
            "",
            "    public:",
            f"      {cls}(StringId paInstanceNameId, CFBContainer &paContainer);",
            "",
        ]
        lines += [f"      CIEC_{v.type} var_{v.name};" for v in fb.input_vars + fb.output_vars]
        lines.append("")
        lines += [f"      CEventConnection conn_{e.name};" for e in fb.event_outputs]
        lines.append("")
        lines += [f"      CDataConnection *conn_{v.name};" for v in fb.input_vars]
        lines.append("")
        lines += [f"      COutDataConnection<CIEC_{v.type}> conn_{v.name};" for v in fb.output_vars]
        lines += [
            "",
            "      CIEC_ANY *getDI(size_t) override;",
            "      CIEC_ANY *getDO(size_t) override;",
            "      CEventConnection *getEOConUnchecked(TPortId) override;",
            "      CDataConnection **getDIConUnchecked(TPortId) override;",
            "      CDataConnection *getDOConUnchecked(TPortId) override;",
            "  };",
            f"}} // namespace forte::{NAMESPACE}",
            "",
        ]
        return "\n".join(lines)

    def source(self) -> str:
        fb = self.fb
        cls = f"FORTE_{fb.name}"
        # Rendering these first collects the includes they need.
        algorithms = [(a, self._algorithm_body(a)) for a in fb.algorithms]
        guards = {id(tr): self._guard(tr.condition) for tr in fb.transitions}
        initials = {v.name: self._literal(v) for v in fb.input_vars + fb.output_vars + fb.internal_vars}

        lines = [f'#include "{fb.name}_fbt.h"', ""]
        lines += [f'#include "{inc}"' for inc in sorted(self.includes, key=lambda inc: ("func_LIMIT" in inc, inc))]
        lines += ["", "using namespace forte::literals;", "", f"namespace forte::{NAMESPACE} {{", "  namespace {"]
        lines += [
            _names_array("cEventInputNames", [e.name for e in fb.event_inputs]),
            _names_array("cEventOutputNames", [e.name for e in fb.event_outputs]),
            _names_array("cDataInputNames", [v.name for v in fb.input_vars]),
            _names_array("cDataOutputNames", [v.name for v in fb.output_vars]),
            _names_array("cInternalsNames", [v.name for v in fb.internal_vars]),
            "    const SFBInterfaceSpec cFBInterfaceSpec = {",
            "        .mEINames = cEventInputNames,",
            "        .mEITypeNames = {},",
            "        .mEONames = cEventOutputNames,",
            "        .mEOTypeNames = {},",
            "        .mDINames = cDataInputNames,",
            "        .mDONames = cDataOutputNames,",
            "        .mDIONames = {},",
            "        .mSocketNames = {},",
            "        .mPlugNames = {},",
            "    };",
            "  } // namespace",
            "",
            f'  DEFINE_FIRMWARE_FB({cls}, "{NAMESPACE}::{fb.name}"_STRID)',
            "",
            f"  {cls}::{cls}(const StringId paInstanceNameId, CFBContainer &paContainer) :",
            "      CBasicFB(paContainer, cFBInterfaceSpec, paInstanceNameId, cInternalsNames),",
        ]
        members = [f"var_{v.name}({initials[v.name]})" for v in fb.internal_vars + fb.input_vars + fb.output_vars]
        members += [f"conn_{e.name}(*this, {i})" for i, e in enumerate(fb.event_outputs)]
        members += [f"conn_{v.name}(nullptr)" for v in fb.input_vars]
        members += [f"conn_{v.name}(*this, {i}, var_{v.name})" for i, v in enumerate(fb.output_vars)]
        lines.append(",\n".join(f"      {m}" for m in members) + " {")
        lines += ["  }", "", f"  void {cls}::setInitialValues() {{", "    CBasicFB::setInitialValues();"]
        lines += [f"    var_{v.name} = {initials[v.name]};" for v in fb.internal_vars + fb.input_vars + fb.output_vars]
        lines += ["  }", ""]
        lines += self._execute_event(cls, guards)
        lines += self._enter_states(cls)
        lines += self._read_input_data(cls)
        lines += self._write_output_data(cls)
        lines += self._accessors(cls)
        for algorithm, body in algorithms:
            lines += [f"  void {cls}::alg_{algorithm.name}(void) {{", *body, "  }", ""]
        lines += [f"}} // namespace forte::{NAMESPACE}", ""]
        return "\n".join(lines)

    def _execute_event(self, cls: str, guards: dict[int, str]) -> list[str]:
        lines = [
            f"  void {cls}::executeEvent(TEventID paEIID, CEventChainExecutionThread *const paECET) {{",
            "    do {",
            "      switch (mECCState) {",
        ]
        for state in self.states:
            lines.append(f"        case scmState{state.name}:")
            keyword = "if"
            for tr in self.fb.transitions:
                if tr.source != state.name:
                    continue
                lines.append(f"          {keyword} ({guards[id(tr)]})")
                lines.append(f"            enterState{tr.destination}(paECET);")
                keyword = "else if"
            if keyword == "if":
                lines.append("          return; // no outgoing transition")
            else:
                lines += ["          else", "            return; // no transition cleared"]
            lines.append("          break;")
        lines += [
            "        default:",
            '          DEVLOG_ERROR("The state is not in the valid range! The state value is: %d. '
            f'The max value can be: {len(self.states)}.",',
            "                       mECCState.operator TForteUInt16());",
            "          mECCState = 0; // 0 is always the initial state",
            "          return;",
            "      }",
            "      paEIID = cgInvalidEventID; // we have to clear the event after the first check in order to ensure correct behavior",
            "    } while (true);",
            "  }",
            "",
        ]
        return lines

    def _enter_states(self, cls: str) -> list[str]:
        lines: list[str] = []
        for state in self.states:
            sends = any(a.output for a in state.actions)
            parameter = "paECET" if sends else ""
            lines.append(f"  void {cls}::enterState{state.name}(CEventChainExecutionThread *const {parameter}) {{")
            lines.append(f"    mECCState = scmState{state.name};")
            for action in state.actions:
                if action.algorithm:
                    lines.append(f"    alg_{action.algorithm}();")
                if action.output:
                    lines.append(f"    sendOutputEvent(scmEvent{action.output}ID, paECET);")
            lines += ["  }", ""]
        return lines

    def _read_input_data(self, cls: str) -> list[str]:
        index = {v.name: i for i, v in enumerate(self.fb.input_vars)}
        lines = [f"  void {cls}::readInputData(const TEventID paEIID) {{", "    switch (paEIID) {"]
        for event in self.fb.event_inputs:
            lines.append(f"      case scmEvent{event.name}ID: {{")
            lines += [f"        readData({index[v]}, var_{v}, conn_{v});" for v in event.with_vars]
            lines += ["        break;", "      }"]
        lines += ["      default: break;", "    }", "  }", ""]
        return lines

    def _write_output_data(self, cls: str) -> list[str]:
        index = {v.name: i for i, v in enumerate(self.fb.output_vars)}
        lines = [f"  void {cls}::writeOutputData(const TEventID paEIID) {{", "    switch (paEIID) {"]
        for event in self.fb.event_outputs:
            lines.append(f"      case scmEvent{event.name}ID: {{")
            lines += [
                f"        writeData(cFBInterfaceSpec.getNumDIs() + {index[v]}, var_{v}, conn_{v});"
                for v in event.with_vars
            ]
            lines += ["        break;", "      }"]
        lines += ["      default: break;", "    }", "  }", ""]
        return lines

    def _accessors(self, cls: str) -> list[str]:
        fb = self.fb
        return (
            _switch(f"CIEC_ANY *{cls}::getDI(const size_t paIndex)", [f"&var_{v.name}" for v in fb.input_vars])
            + _switch(f"CIEC_ANY *{cls}::getDO(const size_t paIndex)", [f"&var_{v.name}" for v in fb.output_vars])
            + _switch(f"CEventConnection *{cls}::getEOConUnchecked(const TPortId paIndex)",
                      [f"&conn_{e.name}" for e in fb.event_outputs])
            + _switch(f"CDataConnection **{cls}::getDIConUnchecked(const TPortId paIndex)",
                      [f"&conn_{v.name}" for v in fb.input_vars])
            + _switch(f"CDataConnection *{cls}::getDOConUnchecked(const TPortId paIndex)",
                      [f"&conn_{v.name}" for v in fb.output_vars])
            + _switch(f"CIEC_ANY *{cls}::getVarInternal(const size_t paIndex)",
                      [f"&var_{v.name}" for v in fb.internal_vars])
        )


def _names_array(name: str, items: list[str]) -> str:
    if not items:
        return f"    const std::array<StringId, 0> {name}{{}};"
    quoted = ", ".join(f'"{item}"_STRID' for item in items)
    return f"    const auto {name} = std::array{{{quoted}}};"


def _switch(signature: str, returns: list[str]) -> list[str]:
    if not returns:
        # Same signature with the unused parameter unnamed.
        return [f"  {signature.rsplit(' ', 1)[0]}) {{", "    return nullptr;", "  }", ""]
    lines = [f"  {signature} {{", "    switch (paIndex) {"]
    lines += [f"      case {i}: return {item};" for i, item in enumerate(returns)]
    lines += ["    }", "    return nullptr;", "  }", ""]
    return lines


def export_fb(fb: fbt.FBType) -> dict[str, str]:
    """File name to file content for one FB."""
    exporter = _Exporter(fb)
    source = exporter.source()  # First, because rendering it collects the includes.
    return {f"{fb.name}_fbt.h": exporter.header(), f"{fb.name}_fbt.cpp": source}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a Basic FB .fbt to FORTE C++")
    parser.add_argument("fbt", type=Path)
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    args = parser.parse_args(argv)
    try:
        files = export_fb(fbt.read_fbt(args.fbt))
    except (OSError, ValueError) as exc:
        print(f"export_forte: {args.fbt}: {exc}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.out / name).write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
