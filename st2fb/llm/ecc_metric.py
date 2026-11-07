"""A strict static check: is control position held by ECC state across REQ events?

`restructured` (engine.ecc_structure) only counts states with actions, so a hub that returns to START every scan and
then dispatches on a variable counts as restructured. That form is a CASE statement drawn as a diagram: between two
scans the ECC is always in START, and the position lives in the variable.

The verdict is one of `persistent`, `not_persistent`, `needs_reading` or `unreadable`. Definitions first:

    rest state       a reachable state with a transition that needs the REQ event, and no always-true transition
                     ahead of it, so the ECC can stop there and wait for the next REQ.
    scan path        from a rest state: the REQ transition taken, then the guard-only hops, up to a state where
                     the ECC can stop. One REQ is one scan, so this is what one scan can do from that position.
    control states   the rest states that the ECC can occupy for more than one scan, because some scans from there come back. A chain
                     that only moves one way counts, as long as it holds in each position. A state left for good on the first REQ does not.

Every variable that is not an input falls into one class, whatever its type:

    enumerated       only ever assigned constants, or plain copies of another enumerated variable (a copy may pass through a type conversion,
                     arithmetic with a constant, or a comparison with a constant). Its root is the variable it was copied from. It can hold a position.
    counter          assigned from itself by arithmetic (TRIES := TRIES + 1), or a copy of such a variable. It may be a retry count or a step number. A TIME moved this way is a clock, so it is data.
    data             depends on an input or on other data, so it holds a measurement or a setting, and not a position.

A named constant, a variable that nothing assigns, counts as its value. A guard or branch reads a variable's carried-over value unless this scan has
definitely assigned it first, from something other than a position. So a copy (K := SEQ) carries the position just as SEQ does.

    C1 at least two control states, one reachable from another. START -> RUN -> START has one.
    C2 no hub: no other state lies on every scan path of every control state. Passing through one forgets the position,
       and anything after it has to recover the position from a variable.
    C3 no guard dispatch: no enumerated root is compared with two or more values by guards while it holds a carried-over value. That value is a
       position kept outside the ECC. A one-hot set of booleans copied from one root counts as that root. A guard reading a variable that an
       algorithm has already assigned in this scan is an exit test, and is allowed.
    C4 no algorithm dispatch: no such root selects branches (CASE with two or more labels, or two or more IF tests that read it) in algorithms run from two or
       more control states. One test is one branch, so a shared `IF STATE_NO >= 2 AND STATE_NO <= 4` that derives an output from a state number just assigned is allowed.
    C5 distinct behaviour: control states do not all run the same algorithms.

A clause failing gives `not_persistent`. Otherwise, `needs_reading` means a static check cannot tell and a person has to read the candidate:

    R1 a counter is compared by guards with two or more values from two or more control states, or with three or more from one, or selects branches in
       algorithms from two or more control states. It may be a retry count, or a step number kept in data.
    R2 booleans that are only ever assigned constants are read as carried-over guards, and the same ones from two or more control states, so they may be a one-hot position.
    R3 guards compare a variable with two or more values after an algorithm that only sometimes assigns it, and that algorithm runs from two or more control states.
       The value read may be the one carried over.

A lowered timer's state variable is left out of all this only if it really is one: its statements are a TON, TOF or TP body, recognised by shape (it moves from 0 to 1 while a TIME
start value is taken, and to 2 on a comparison of TIME values), it takes only the values 0, 1 and 2, and no guard reads it. A name is not enough.

What this does not prove. It is static, and it says nothing about behaviour, which only the trace comparison decides. Someone determined could satisfy it with a
meaningless ECC, for example with one conditional assignment per state in front of its guards, so read the candidates too. Data can hold a position if it is laundered through an input.
The failures and the reading notes come with reasons, as `ecc_persistent_failures` and `ecc_needs_reading`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterator

from .. import fbt
from ..st import (
    Assign, Binary, BoolLit, Call, Case, Expr, FBCall, For, If, IntLit, Member, RealLit, Stmt, STParseError, TimeLit, Unary, Var, While,
    parse_expression, parse_statements,
)

_RELATIONS = {"=", "<>", "<", "<=", ">", ">="}
_LOGIC = {"AND", "OR", "XOR"}
_CONVERSION = re.compile(r"[A-Z]+_TO_[A-Z]+\Z")
_EVENT_GUARD = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)?\s*\[(.*)\]\s*\Z", re.DOTALL)
_MAX_PATHS = 20000
_ENUMERATED, _COUNTER, _DATA = "enumerated", "counter", "data"


class _Unreadable(ValueError):
    pass


@dataclass(frozen=True)
class _Edge:
    destination: str
    needs_event: bool
    always: bool  # Always true once it is tried.
    guard: Expr | None


@dataclass(frozen=True)
class _ScanPath:
    start: str
    states: tuple[str, ...]  # Without the rest state it starts from.
    algorithms: tuple[str, ...]


def _literal(expr: Expr) -> int | None:
    if isinstance(expr, IntLit):
        return expr.value
    if isinstance(expr, Unary) and expr.op == "-" and isinstance(expr.operand, IntLit):
        return -expr.operand.value
    return None


def _parse_edge(transition: fbt.ECTransition, events: set[str]) -> _Edge:
    condition = transition.condition.strip()
    if condition in ("1", "TRUE", "true"):
        return _Edge(transition.destination, False, True, None)
    if condition in events:
        return _Edge(transition.destination, True, True, None)
    matched = _EVENT_GUARD.match(condition)
    event, text = (matched.group(1), matched.group(2)) if matched else (None, condition)
    try:
        guard = parse_expression(text)
    except STParseError as exc:
        raise _Unreadable(f"guard {condition!r}: {exc}") from exc
    always = isinstance(guard, BoolLit) and guard.value or _literal(guard) == 1
    return _Edge(transition.destination, event is not None, bool(always), guard)


def _active(edges: list[_Edge], needs_event: bool) -> list[_Edge]:
    """The edges that can fire, in order: nothing after an edge that is always true can be reached."""
    result = []
    for edge in edges:
        if edge.needs_event == needs_event:
            result.append(edge)
            if edge.always:
                break
    return result


def _reads(expr: Expr | None) -> Iterator[str]:
    """Every variable an expression reads."""
    if isinstance(expr, Var):
        yield expr.name.upper()
    elif isinstance(expr, Member):
        yield expr.base.upper()
    elif isinstance(expr, Unary):
        yield from _reads(expr.operand)
    elif isinstance(expr, Binary):
        yield from _reads(expr.left)
        yield from _reads(expr.right)
    elif isinstance(expr, Call):
        for argument in expr.args:
            yield from _reads(argument)


def _assignments(stmts: tuple[Stmt, ...]) -> Iterator[tuple[str, Expr | None]]:
    """(target, value) for every assignment in a statement list. The value is None for anything but a plain assignment."""
    for stmt in stmts:
        if isinstance(stmt, Assign) and isinstance(stmt.target, Var):
            yield stmt.target.name.upper(), stmt.value
        elif isinstance(stmt, If):
            for _, body in stmt.branches:
                yield from _assignments(body)
            yield from _assignments(stmt.else_body)
        elif isinstance(stmt, Case):
            for branch in stmt.branches:
                yield from _assignments(branch.body)
            yield from _assignments(stmt.else_body)
        elif isinstance(stmt, For):
            yield stmt.var.upper(), None
            yield from _assignments(stmt.body)
        elif isinstance(stmt, While):
            yield from _assignments(stmt.body)
        elif isinstance(stmt, FBCall):
            for argument in stmt.args:
                if argument.is_output and isinstance(argument.value, Var):
                    yield argument.value.name.upper(), None


def _assigned(stmts: tuple[Stmt, ...]) -> set[str]:
    """Every variable a statement list can assign."""
    return {target for target, _ in _assignments(stmts)}


def _definitely_assigned(stmts: tuple[Stmt, ...]) -> set[str]:
    """Every variable a statement list assigns on all paths through it."""
    found: set[str] = set()
    for stmt in stmts:
        if isinstance(stmt, Assign) and isinstance(stmt.target, Var):
            found.add(stmt.target.name.upper())
        elif isinstance(stmt, If) and stmt.else_body:
            bodies = [body for _, body in stmt.branches] + [stmt.else_body]
            found |= set.intersection(*(_definitely_assigned(body) for body in bodies))
        elif isinstance(stmt, Case) and stmt.else_body:
            bodies = [branch.body for branch in stmt.branches] + [stmt.else_body]
            found |= set.intersection(*(_definitely_assigned(body) for body in bodies))
    return found


def _statements(stmts: tuple[Stmt, ...]) -> Iterator[Stmt]:
    for stmt in stmts:
        yield stmt
        if isinstance(stmt, If):
            for _, body in stmt.branches:
                yield from _statements(body)
            yield from _statements(stmt.else_body)
        elif isinstance(stmt, Case):
            for branch in stmt.branches:
                yield from _statements(branch.body)
            yield from _statements(stmt.else_body)
        elif isinstance(stmt, (For, While)):
            yield from _statements(stmt.body)


class _Variables:
    """Sorts every variable of an FB into constant, enumerated, counter or data, and follows copies back to their root."""

    def __init__(self, fb: fbt.FBType, bodies: dict[str, tuple[Stmt, ...]]) -> None:
        self.inputs = {var.name.upper() for var in fb.input_vars}
        self.types = {var.name.upper(): var.type.upper() for var in fb.input_vars + fb.output_vars + fb.internal_vars}
        self.writes: dict[str, list[Expr | None]] = {}
        for body in bodies.values():
            for target, value in _assignments(body):
                self.writes.setdefault(target, []).append(value)
        self.constants: dict[str, str] = {}
        initial = {var.name.upper(): var.initial for var in fb.output_vars + fb.internal_vars}
        for name in self.types:
            if name not in self.writes and name not in self.inputs:
                self.constants[name] = (initial.get(name) or "0").strip()
        self.kind, self.root = self._classify()

    def _is_constant(self, expr: Expr | None) -> bool:
        if isinstance(expr, (IntLit, RealLit, BoolLit, TimeLit)):
            return True
        if isinstance(expr, Var):
            return expr.name.upper() in self.constants
        if isinstance(expr, Unary):
            return self._is_constant(expr.operand)
        if isinstance(expr, Binary):
            return self._is_constant(expr.left) and self._is_constant(expr.right)
        if isinstance(expr, Call):
            return all(self._is_constant(argument) for argument in expr.args)
        return False

    def constant_value(self, expr: Expr) -> str:
        """A key that is the same for two constant expressions of the same value, as far as can be told without evaluating them."""
        if isinstance(expr, Var):
            text = self.constants[expr.name.upper()]
            return text.upper() if not re.fullmatch(r"[-+]?\d+(\.\d+)?", text) else str(float(text))
        if isinstance(expr, (IntLit, RealLit)):
            return str(float(expr.value))
        if isinstance(expr, Unary) and expr.op == "-" and isinstance(expr.operand, (IntLit, RealLit)):
            return str(float(-expr.operand.value))
        return repr(expr)

    def _source(self, expr: Expr | None) -> str | None:
        """The one variable that expr is a plain copy of, through conversions, arithmetic and comparisons with constants."""
        if isinstance(expr, Var) and expr.name.upper() not in self.constants:
            return expr.name.upper()
        if isinstance(expr, Unary):
            return self._source(expr.operand)
        if isinstance(expr, Call) and _CONVERSION.match(expr.name.upper()) and len(expr.args) == 1:
            return self._source(expr.args[0])
        if isinstance(expr, Binary) and expr.op not in _LOGIC:
            if self._is_constant(expr.right):
                return self._source(expr.left)
            if self._is_constant(expr.left):
                return self._source(expr.right)
        return None

    def _classify(self) -> tuple[dict[str, str], dict[str, str]]:
        names = [name for name in self.types if name not in self.inputs and name not in self.constants]
        kind = {name: _ENUMERATED for name in names}
        changed = True
        while changed:
            changed = False
            for name in names:
                worst = kind[name]
                for value in self.writes.get(name, []):
                    worst = self._weakest(worst, self._write_kind(name, value, kind))
                if worst != kind[name]:
                    kind[name], changed = worst, True
        root = {name: name for name in names}
        for _ in names:
            for name in names:
                for value in self.writes.get(name, []):
                    source = self._source(value)
                    if source is not None and source != name and source in kind and kind[source] == kind[name]:
                        root[name] = root[source]
        return kind, root

    @staticmethod
    def _weakest(a: str, b: str) -> str:
        order = {_ENUMERATED: 0, _COUNTER: 1, _DATA: 2}
        return a if order[a] >= order[b] else b

    def _write_kind(self, name: str, value: Expr | None, kind: dict[str, str]) -> str:
        if value is None:
            return _DATA
        if self._is_constant(value):
            return _ENUMERATED
        source = self._source(value)
        if source is None:
            return _DATA
        if source == name:
            if isinstance(value, Var):
                return _ENUMERATED  # X := X changes nothing.
            return _DATA if self.types.get(name) == "TIME" else _COUNTER  # A TIME moved by arithmetic is a clock. Anything else moved so counts.
        if source in self.inputs:
            return _DATA
        return kind.get(source, _DATA)

    def is_position_derived(self, value: Expr | None) -> bool:
        return any(self.kind.get(name, _DATA) != _DATA for name in _reads(value))

    def fresh_writes(self, name: str) -> bool:
        """Every write of this variable is from a constant or from data, so assigning it does not carry a position along."""
        return not any(value is None or (not self._is_constant(value) and self.is_position_derived(value)) for value in self.writes.get(name, []))


def _timer_states(variables: _Variables, bodies: dict[str, tuple[Stmt, ...]]) -> set[str]:
    """Variables whose statements really are a lowered TON, TOF or TP body. See the module docstring."""
    found = set()
    for body in bodies.values():
        for stmt in _statements(body):
            if not isinstance(stmt, If):
                continue
            condition, first = stmt.branches[0]
            for name in set(_reads(condition)):
                if _is_timer_body(variables, name, condition, first, stmt):
                    found.add(name)
    return found


def _is_timer_body(variables: _Variables, name: str, condition: Expr, first: tuple[Stmt, ...], whole: If) -> bool:
    if not any(variable == name and value == str(0.0) and operator == "=" for variable, value, operator in _relations(variables, condition)):
        return False
    writes = variables.writes.get(name, [])
    if not writes or not all(isinstance(value, IntLit) and value.value in (0, 1, 2) for value in writes):
        return False
    moves_to_one = any(isinstance(stmt, Assign) and stmt.target == Var(name) and stmt.value == IntLit(1) for stmt in first)
    takes_start = {
        stmt.target.name.upper()
        for stmt in first
        if isinstance(stmt, Assign) and isinstance(stmt.target, Var) and isinstance(stmt.value, Var)
        and variables.types.get(stmt.target.name.upper()) == "TIME" and variables.types.get(stmt.value.name.upper()) == "TIME"
    }
    if not moves_to_one or not takes_start:
        return False
    for inner in _statements((whole,)):
        if not isinstance(inner, If):
            continue
        for test, body in inner.branches:
            uses_start = takes_start & set(_reads(test))
            is_time_comparison = isinstance(test, Binary) and test.op in _RELATIONS and all(variables.types.get(read) == "TIME" for read in _reads(test))
            if uses_start and is_time_comparison and any(isinstance(stmt, Assign) and stmt.target == Var(name) and stmt.value == IntLit(2) for stmt in body):
                return True
    return False


def _relations(variables: _Variables, expr: Expr | None) -> Iterator[tuple[str, str, str]]:
    """(variable, value key, operator) for every comparison in expr, and for every boolean read bare. A value is a constant, or the text of what it is compared with."""
    if isinstance(expr, Binary) and expr.op in _RELATIONS:
        left, right = set(_reads(expr.left)) - set(variables.constants), set(_reads(expr.right)) - set(variables.constants)
        if variables._is_constant(expr.right):
            value = variables.constant_value(expr.right)
            for name in left:
                yield name, value, expr.op
        elif variables._is_constant(expr.left):
            value = variables.constant_value(expr.left)
            for name in right:
                yield name, value, expr.op
        else:
            for name in left:
                yield name, f"var:{sorted(right)}", expr.op
            for name in right:
                yield name, f"var:{sorted(left)}", expr.op
    elif isinstance(expr, Binary):
        yield from _relations(variables, expr.left)
        yield from _relations(variables, expr.right)
    elif isinstance(expr, Unary) and expr.op == "NOT":
        for name, value, operator in _relations(variables, expr.operand):
            yield name, f"not:{value}", operator
    elif isinstance(expr, Var) and expr.name.upper() not in variables.constants:
        yield expr.name.upper(), "true", "bare"


def _branching(variables: _Variables, stmts: tuple[Stmt, ...], clean: set[str], out: dict[str, set[str]]) -> None:
    """Record variables that select branches and that this algorithm has not cleanly assigned first."""
    clean = set(clean)
    for stmt in stmts:
        if isinstance(stmt, Assign) and isinstance(stmt.target, Var):
            name = stmt.target.name.upper()
            if variables._is_constant(stmt.value) or not variables.is_position_derived(stmt.value):
                clean.add(name)
            else:
                clean.discard(name)
        elif isinstance(stmt, If):
            for condition, body in stmt.branches:
                # One test is one branch, however many comparisons it holds, so a range test is one and not two.
                tests: dict[str, list[str]] = {}
                for name, value, operator in _relations(variables, condition):
                    if name not in clean and operator != "bare":
                        tests.setdefault(name, []).append(f"{operator} {value}")
                for name, comparisons in tests.items():
                    out.setdefault(name, set()).add(" & ".join(sorted(comparisons)))
                _branching(variables, body, clean, out)
            _branching(variables, stmt.else_body, clean, out)
        elif isinstance(stmt, Case):
            selector = set(_reads(stmt.selector)) - set(variables.constants)
            labels = {str(float(label.low)) for branch in stmt.branches for label in branch.labels}
            if len(labels) >= 2:
                for name in selector - clean:
                    out.setdefault(name, set()).update(labels)
            for branch in stmt.branches:
                _branching(variables, branch.body, clean, out)
            _branching(variables, stmt.else_body, clean, out)
        elif isinstance(stmt, For):
            _branching(variables, stmt.body, clean | {stmt.var.upper()}, out)
        elif isinstance(stmt, While):
            _branching(variables, stmt.body, clean, out)


def _held(nodes: set[str], moves: dict[str, set[str]]) -> set[str]:
    """The nodes that some scans come back to, directly or round a cycle."""

    def reach(start: str) -> set[str]:
        seen, stack = set(), [start]
        while stack:
            for next_node in moves.get(stack.pop(), ()):
                if next_node not in seen:
                    seen.add(next_node)
                    stack.append(next_node)
        return seen

    return {node for node in nodes if node in reach(node)}


class _Analysis:
    def __init__(self, fb: fbt.FBType) -> None:
        self.fb = fb
        events = {event.name for event in fb.event_inputs}
        self.edges: dict[str, list[_Edge]] = {state.name: [] for state in fb.states}
        for transition in fb.transitions:
            if transition.source in self.edges:
                self.edges[transition.source].append(_parse_edge(transition, events))
        self.actions = {
            state.name: tuple(action.algorithm for action in state.actions if action.algorithm) for state in fb.states
        }
        self.bodies = {}
        for algorithm in fb.algorithms:
            try:
                self.bodies[algorithm.name] = parse_statements(algorithm.st)
            except STParseError as exc:
                raise _Unreadable(f"algorithm {algorithm.name}: {exc}") from exc
        self.variables = _Variables(fb, self.bodies)
        self.paths: dict[str, list[_ScanPath]] = {}
        # Every guard read of a carried-over value, and every one that follows an assignment made only on some paths.
        self.carried: list[tuple[str, str, str, str]] = []  # (rest state, variable, value key, operator)
        self.maybe: list[tuple[str, str, str, tuple[str, ...]]] = []  # (rest state, variable, value key, algorithms)

    def _can_rest(self, state: str) -> bool:
        return not any(edge.always and not edge.needs_event for edge in self.edges.get(state, []))

    def is_rest(self, state: str) -> bool:
        return self._can_rest(state) and any(edge.needs_event for edge in self.edges.get(state, []))

    def _read_guard(self, start: str, edge: _Edge, algorithms: tuple[str, ...]) -> None:
        definite: set[str] = set()
        maybe: set[str] = set()
        for name in algorithms:
            body = self.bodies.get(name, ())
            definite |= _definitely_assigned(body)
            maybe |= _assigned(body)
        for variable, value, operator in _relations(self.variables, edge.guard):
            if variable not in self.variables.kind:
                continue
            if variable in maybe and not self.variables.fresh_writes(variable):
                self.carried.append((start, variable, value, operator))
            elif variable in definite:
                continue
            elif variable in maybe:
                self.maybe.append((start, variable, value, algorithms))
            else:
                self.carried.append((start, variable, value, operator))

    def _walk(self, start: str, state: str, seen: tuple[str, ...], algorithms: tuple[str, ...], out: list[_ScanPath]) -> None:
        if len(out) > _MAX_PATHS:
            raise _Unreadable(f"more than {_MAX_PATHS} scan paths from state {start}")
        algorithms = algorithms + self.actions.get(state, ())
        seen = seen + (state,)
        if self._can_rest(state):
            out.append(_ScanPath(start, seen, algorithms))
        for edge in _active(self.edges.get(state, []), needs_event=False):
            self._read_guard(start, edge, algorithms)
            if edge.destination not in seen:
                self._walk(start, edge.destination, seen, algorithms, out)

    def scan_paths(self, state: str) -> list[_ScanPath]:
        if state not in self.paths:
            found: list[_ScanPath] = []
            for edge in _active(self.edges.get(state, []), needs_event=True):
                self._read_guard(state, edge, ())
                self._walk(state, edge.destination, (), (), found)
            self.paths[state] = found
        return self.paths[state]

    def rest_graph(self) -> tuple[set[str], dict[str, set[str]]]:
        start = next((state.name for state in self.fb.states if state.name == "START"), None)
        start = start or (self.fb.states[0].name if self.fb.states else None)
        if start is None:
            return set(), {}
        rest: set[str] = set()
        moves: dict[str, set[str]] = {}
        stack = []
        # START can also move on at once, through a guard or a 1, before the first REQ.
        entry: list[_ScanPath] = []
        self._walk(start, start, (), (), entry)
        for path in entry:
            stack.append(path.states[-1])
        while stack:
            state = stack.pop()
            if state in rest or not self.is_rest(state):
                continue
            rest.add(state)
            moves[state] = {path.states[-1] for path in self.scan_paths(state) if self.is_rest(path.states[-1])}
            stack.extend(moves[state])
        return rest, moves

    def _guard_clauses(self, control: set[str]) -> tuple[list[str], list[str]]:
        problems, reading = [], []
        kind, root = self.variables.kind, self.variables.root
        by_root: dict[str, set[str]] = {}
        counter_sites: dict[str, dict[str, set[str]]] = {}
        bool_sites: dict[str, set[str]] = {}
        for state, variable, value, operator in self.carried:
            if state not in control or variable in self.timers:
                continue
            base = root.get(variable, variable)
            if kind[variable] == _COUNTER:
                counter_sites.setdefault(base, {}).setdefault(state, set()).add(value)
            elif kind[variable] == _ENUMERATED:
                is_bool = self.variables.types.get(base) == "BOOL"
                if is_bool and base == variable:
                    bool_sites.setdefault(base, set()).add(state)
                else:
                    by_root.setdefault(base, set()).add(f"{variable}:{value}" if variable != base else value)
        for name, values in sorted(by_root.items()):
            if len(values) >= 2:
                problems.append(f"C3: guards compare carried-over {name}, or copies of it, with {len(values)} values: {sorted(values)}")
        for name, sites in sorted(counter_sites.items()):
            values = set().union(*sites.values())
            if (len(sites) >= 2 and len(values) >= 2) or len(values) >= 3:
                reading.append(f"R1: guards compare carried-over counter {name} with {sorted(values)} from {sorted(sites)}. A retry count, or a step number?")
        repeated = sorted(name for name, sites in bool_sites.items() if len(sites) >= 2)
        if len(repeated) >= 2:
            reading.append(f"R2: guards read carried-over booleans {repeated}, only ever assigned constants, from two or more control states. A one-hot position?")
        shared: dict[str, set[str]] = {}
        run_from: dict[str, set[str]] = {}
        for state in control:
            for path in self.scan_paths(state):
                for algorithm in path.algorithms:
                    run_from.setdefault(algorithm, set()).add(state)
        for state, variable, value, algorithms in self.maybe:
            if state in control and variable not in self.timers and kind[variable] != _DATA:
                if any(len(run_from.get(algorithm, ())) >= 2 and variable in _assigned(self.bodies.get(algorithm, ())) for algorithm in algorithms):
                    shared.setdefault(variable, set()).add(value)
        for name, values in sorted(shared.items()):
            if len(values) >= 2:
                reading.append(f"R3: guards compare {name} with {sorted(values)} after a shared algorithm that only sometimes assigns it. The value read may be the carried-over one.")
        return problems, reading

    def _algorithm_clauses(self, control: set[str]) -> tuple[list[str], list[str]]:
        problems, reading = [], []
        kind, root = self.variables.kind, self.variables.root
        dispatch: dict[str, set[str]] = {}
        for state in control:
            for algorithm in {name for path in self.scan_paths(state) for name in path.algorithms}:
                branches: dict[str, set[str]] = {}
                _branching(self.variables, self.bodies.get(algorithm, ()), set(), branches)
                by_root: dict[str, set[str]] = {}
                for name, values in branches.items():
                    if kind.get(name, _DATA) != _DATA and name not in self.timers:
                        by_root.setdefault(root.get(name, name), set()).update(values)
                for name, values in by_root.items():
                    if len(values) >= 2:
                        dispatch.setdefault(name, set()).add(state)
        for name, states in sorted(dispatch.items()):
            if len(states) >= 2:
                if kind.get(name) == _COUNTER:
                    reading.append(f"R1: algorithms run from {len(states)} control states branch on counter {name}. A retry count, or a step number?")
                else:
                    problems.append(f"C4: algorithms run from {len(states)} control states branch on {name}, or a copy of it")
        return problems, reading

    def verdict(self) -> tuple[int, list[str], list[str]]:
        rest, moves = self.rest_graph()
        control = _held(rest, moves)
        problems: list[str] = []
        connected = any(other in moves.get(state, ()) for state in control for other in control if other != state) or self._reaches_another(control, moves)
        if len(control) < 2 or not connected:
            problems.append(f"C1: {len(control)} control state(s) that hold and connect, and at least 2 are needed")
            return len(control), problems, []

        all_paths = [path for state in control for path in self.scan_paths(state)]
        guard_readers = {variable for _, variable, _, _ in self.carried} | {variable for _, variable, _, _ in self.maybe}
        self.timers = _timer_states(self.variables, self.bodies) - guard_readers
        common = set(all_paths[0].states) if all_paths else set()
        for path in all_paths:
            common &= set(path.states)
        hubs = sorted(common - control)
        if hubs:
            problems.append(f"C2: every scan from every control state passes through {hubs}")

        guard_problems, reading = self._guard_clauses(control)
        problems += guard_problems
        algorithm_problems, algorithm_reading = self._algorithm_clauses(control)
        problems += algorithm_problems
        reading += algorithm_reading

        behaviours = {frozenset(path.algorithms for path in self.scan_paths(state)) for state in control}
        if len(behaviours) < 2:
            problems.append("C5: every control state runs the same algorithms")
        return len(control), problems, reading

    @staticmethod
    def _reaches_another(control: set[str], moves: dict[str, set[str]]) -> bool:
        """A chain may pass through states that do not hold on its way from one control state to the next."""
        for state in control:
            seen, stack = {state}, [state]
            while stack:
                for next_node in moves.get(stack.pop(), ()):
                    if next_node in control and next_node != state:
                        return True
                    if next_node not in seen:
                        seen.add(next_node)
                        stack.append(next_node)
        return False


def ecc_persistence(candidate: str) -> dict[str, Any]:
    """Report fields. ecc_persistent is True or False once decided, and None when the candidate is unreadable or a person has to read it: see ecc_verdict."""
    try:
        fb = fbt.parse_fbt(candidate)
    except (ValueError, TypeError):
        return {"ecc_persistent": None, "ecc_verdict": "unreadable", "control_states": None, "ecc_persistent_failures": ["not a readable FBType"], "ecc_needs_reading": []}
    try:
        control, problems, reading = _Analysis(fb).verdict()
    except _Unreadable as exc:
        return {"ecc_persistent": False, "ecc_verdict": "not_persistent", "control_states": None, "ecc_persistent_failures": [str(exc)], "ecc_needs_reading": []}
    if problems:
        return {"ecc_persistent": False, "ecc_verdict": "not_persistent", "control_states": control, "ecc_persistent_failures": problems, "ecc_needs_reading": reading}
    if reading:
        return {"ecc_persistent": None, "ecc_verdict": "needs_reading", "control_states": control, "ecc_persistent_failures": [], "ecc_needs_reading": reading}
    return {"ecc_persistent": True, "ecc_verdict": "persistent", "control_states": control, "ecc_persistent_failures": [], "ecc_needs_reading": []}
