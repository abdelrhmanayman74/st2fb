"""AST for the v1 ST subset. Line numbers are ignored in equality, so two programs that differ
only in layout compare equal; that is what the translator tests rely on."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class IntLit:
    value: int
    type: str | None = None  # None for a plain `5`; it takes its type from context.


@dataclass(frozen=True)
class RealLit:
    value: float
    type: str | None = None


@dataclass(frozen=True)
class BoolLit:
    value: bool


@dataclass(frozen=True)
class TimeLit:
    nanoseconds: int


@dataclass(frozen=True)
class Var:
    name: str


@dataclass(frozen=True)
class Member:
    """`T1.Q`: an output or input of a standard FB instance."""
    base: str
    field: str


@dataclass(frozen=True)
class Unary:
    op: str  # "-" or "NOT"
    operand: "Expr"


@dataclass(frozen=True)
class Binary:
    op: str  # OR XOR AND = <> < > <= >= + - * / MOD **
    left: "Expr"
    right: "Expr"


@dataclass(frozen=True)
class Call:
    """A standard function call in an expression, e.g. ABS(x)."""
    name: str
    args: tuple["Expr", ...]


Expr = Union[IntLit, RealLit, BoolLit, TimeLit, Var, Member, Unary, Binary, Call]


@dataclass(frozen=True)
class Assign:
    target: Union[Var, Member]
    value: Expr
    line: int = field(default=0, compare=False)


@dataclass(frozen=True)
class If:
    branches: tuple[tuple[Expr, tuple["Stmt", ...]], ...]
    else_body: tuple["Stmt", ...] = ()
    line: int = field(default=0, compare=False)


@dataclass(frozen=True)
class CaseLabel:
    low: int
    high: int  # Equal to low for a single value; `low..high` otherwise.
    type: str | None = None


@dataclass(frozen=True)
class CaseBranch:
    labels: tuple[CaseLabel, ...]
    body: tuple["Stmt", ...]


@dataclass(frozen=True)
class Case:
    selector: Expr
    branches: tuple[CaseBranch, ...]
    else_body: tuple["Stmt", ...] = ()
    line: int = field(default=0, compare=False)


@dataclass(frozen=True)
class For:
    var: str
    start: Expr
    stop: Expr
    step: Expr | None
    body: tuple["Stmt", ...]
    line: int = field(default=0, compare=False)


@dataclass(frozen=True)
class While:
    condition: Expr
    body: tuple["Stmt", ...]
    line: int = field(default=0, compare=False)


@dataclass(frozen=True)
class CallArg:
    """One FB call argument: `IN := x`, `Q => y`, or positional when name is None."""
    name: str | None
    value: Expr
    is_output: bool = False


@dataclass(frozen=True)
class FBCall:
    """Statement form `T1(IN := x, PT := T#1s);`. Removed by the translator's lowering."""
    instance: str
    args: tuple[CallArg, ...]
    line: int = field(default=0, compare=False)


Stmt = Union[Assign, If, Case, For, While, FBCall]


@dataclass(frozen=True)
class VarDecl:
    name: str
    type: str
    initial: Expr | None = None


@dataclass(frozen=True)
class FunctionBlock:
    name: str
    inputs: tuple[VarDecl, ...]
    outputs: tuple[VarDecl, ...]
    locals: tuple[VarDecl, ...]
    body: tuple[Stmt, ...]
