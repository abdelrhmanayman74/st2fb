"""Read and write IEC 61499 .fbt files as used by 4diac. Basic FBs only."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import quoteattr


class FbtError(ValueError):
    pass


# The data types of scope v1 (docs/DESIGN.md).
V1_TYPES = frozenset({"BOOL", "INT", "DINT", "UINT", "REAL", "TIME"})

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
# A fixed date keeps translator output byte-reproducible.
VERSION_DATE = "2026-11-06"


@dataclass(frozen=True)
class VarDeclaration:
    name: str
    type: str
    initial: str | None = None


@dataclass(frozen=True)
class Event:
    name: str
    with_vars: tuple[str, ...] = ()


@dataclass(frozen=True)
class ECAction:
    algorithm: str | None = None
    output: str | None = None


@dataclass(frozen=True)
class ECState:
    name: str
    actions: tuple[ECAction, ...] = ()
    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class ECTransition:
    source: str
    destination: str
    condition: str
    x: int = 0
    y: int = 0


@dataclass(frozen=True)
class Algorithm:
    name: str
    st: str


@dataclass(frozen=True)
class FBType:
    name: str
    event_inputs: tuple[Event, ...]
    event_outputs: tuple[Event, ...]
    input_vars: tuple[VarDeclaration, ...]
    output_vars: tuple[VarDeclaration, ...]
    internal_vars: tuple[VarDeclaration, ...]
    states: tuple[ECState, ...]
    transitions: tuple[ECTransition, ...]
    algorithms: tuple[Algorithm, ...]
    comment: str = field(default="", compare=False)


def _checked_name(text: str | None, what: str) -> str:
    if not text or not _NAME.match(text):
        raise FbtError(f"invalid {what} name {text!r}")
    return text


def _coordinate(text: str | None) -> int:
    # 4diac writes coordinates as decimals such as "200.0"; they have no semantic meaning.
    try:
        return round(float(text)) if text else 0
    except ValueError:
        return 0


def _var_list(parent: ET.Element | None) -> tuple[VarDeclaration, ...]:
    if parent is None:
        return ()
    return tuple(
        VarDeclaration(
            _checked_name(el.get("Name"), "variable"),
            (el.get("Type") or "").upper(),
            el.get("InitialValue") or None,
        )
        for el in parent.findall("VarDeclaration")
    )


def _event_list(parent: ET.Element | None) -> tuple[Event, ...]:
    if parent is None:
        return ()
    return tuple(
        Event(
            _checked_name(el.get("Name"), "event"),
            tuple(w.get("Var", "") for w in el.findall("With")),
        )
        for el in parent.findall("Event")
    )


def parse_fbt(text: str) -> FBType:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise FbtError(f"not well-formed XML: {exc}") from exc
    if root.tag != "FBType":
        raise FbtError(f"root element is {root.tag}, expected FBType")
    interface = root.find("InterfaceList")
    basic = root.find("BasicFB")
    if interface is None or basic is None:
        raise FbtError("expected InterfaceList and BasicFB elements")
    # Reading only BasicFB would silently drop a misplaced block, and the exporter would then report
    # its variables as undeclared, which sends a reader or a repair prompt the wrong way.
    for parent in root.iter():
        if parent is not basic and parent.find("InternalVars") is not None:
            raise FbtError(f"<InternalVars> must be inside <BasicFB>, not inside <{parent.tag}>")
    ecc = basic.find("ECC")
    if ecc is None:
        raise FbtError("BasicFB has no ECC")

    states = tuple(
        ECState(
            _checked_name(state.get("Name"), "state"),
            tuple(
                ECAction(action.get("Algorithm") or None, action.get("Output") or None)
                for action in state.findall("ECAction")
            ),
            _coordinate(state.get("x")),
            _coordinate(state.get("y")),
        )
        for state in ecc.findall("ECState")
    )
    transitions = tuple(
        ECTransition(
            el.get("Source", ""), el.get("Destination", ""), (el.get("Condition") or "").strip(),
            _coordinate(el.get("x")), _coordinate(el.get("y")),
        )
        for el in ecc.findall("ECTransition")
    )

    algorithms = []
    for el in basic.findall("Algorithm"):
        name = _checked_name(el.get("Name"), "algorithm")
        st = el.find("ST")
        if st is None:
            raise FbtError(f"algorithm {name} has no ST body; other languages are unsupported")
        # 4diac normally uses CDATA, but older files keep the body in a Text attribute.
        algorithms.append(Algorithm(name, st.text if st.text else st.get("Text", "")))

    return FBType(
        name=_checked_name(root.get("Name"), "FB type"),
        comment=root.get("Comment", ""),
        event_inputs=_event_list(interface.find("EventInputs")),
        event_outputs=_event_list(interface.find("EventOutputs")),
        input_vars=_var_list(interface.find("InputVars")),
        output_vars=_var_list(interface.find("OutputVars")),
        internal_vars=_var_list(basic.find("InternalVars")),
        states=states,
        transitions=transitions,
        algorithms=tuple(algorithms),
    )


def read_fbt(path: str | Path) -> FBType:
    return parse_fbt(Path(path).read_text(encoding="utf-8"))


def _write_var(var: VarDeclaration) -> str:
    initial = f" InitialValue={quoteattr(var.initial)}" if var.initial is not None else ""
    return f"<VarDeclaration Name={quoteattr(var.name)} Type={quoteattr(var.type)}{initial}/>"


def _write_event(event: Event) -> str:
    withs = "".join(f"<With Var={quoteattr(var)}/>" for var in event.with_vars)
    head = f"<Event Name={quoteattr(event.name)} Type=\"Event\""
    return f"{head}>{withs}</Event>" if withs else f"{head}/>"


def _write_action(action: ECAction) -> str:
    attrs = ""
    if action.algorithm:
        attrs += f" Algorithm={quoteattr(action.algorithm)}"
    if action.output:
        attrs += f" Output={quoteattr(action.output)}"
    return f"<ECAction{attrs}/>"


def _section(lines: list[str], tag: str, items: list[str], indent: str) -> None:
    if items:
        lines.append(f"{indent}<{tag}>")
        lines.extend(f"{indent}  {item}" for item in items)
        lines.append(f"{indent}</{tag}>")


def write_fbt(fb: FBType) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f"<FBType Name={quoteattr(fb.name)} Comment={quoteattr(fb.comment)}>",
        '  <Identification Standard="61499-2"/>',
        f'  <VersionInfo Version="1.0" Author="st2fb" Date="{VERSION_DATE}"/>',
        "  <InterfaceList>",
    ]
    _section(lines, "EventInputs", [_write_event(e) for e in fb.event_inputs], "    ")
    _section(lines, "EventOutputs", [_write_event(e) for e in fb.event_outputs], "    ")
    _section(lines, "InputVars", [_write_var(v) for v in fb.input_vars], "    ")
    _section(lines, "OutputVars", [_write_var(v) for v in fb.output_vars], "    ")
    lines.append("  </InterfaceList>")
    lines.append("  <BasicFB>")
    _section(lines, "InternalVars", [_write_var(v) for v in fb.internal_vars], "    ")
    lines.append("    <ECC>")
    for state in fb.states:
        head = f"<ECState Name={quoteattr(state.name)} x=\"{state.x}\" y=\"{state.y}\""
        if state.actions:
            lines.append(f"      {head}>")
            lines.extend(f"        {_write_action(a)}" for a in state.actions)
            lines.append("      </ECState>")
        else:
            lines.append(f"      {head}/>")
    for tr in fb.transitions:
        lines.append(
            f"      <ECTransition Source={quoteattr(tr.source)} "
            f"Destination={quoteattr(tr.destination)} Condition={quoteattr(tr.condition)} "
            f'x="{tr.x}" y="{tr.y}"/>'
        )
    lines.append("    </ECC>")
    for algorithm in fb.algorithms:
        # `]]>` cannot appear inside one CDATA section, so split it across two.
        body = algorithm.st.replace("]]>", "]]]]><![CDATA[>")
        lines.append(f"    <Algorithm Name={quoteattr(algorithm.name)}>")
        lines.append(f"      <ST><![CDATA[\n{body}]]></ST>")
        lines.append("    </Algorithm>")
    lines.append("  </BasicFB>")
    lines.append("</FBType>")
    return "\n".join(lines) + "\n"
