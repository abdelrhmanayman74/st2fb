"""A small, mechanical rewrite of the vendor dialects of corpus_hard/ into plain ST.

    python3 -m st2fb.vendor_frontend corpus_hard/siemens_scl/s01_conveyor_starter/program.scl

It exists to be an honest comparator. "The translator rejects it" says only that this project's parser stopped at the first `"`, so
a report also has to say how far a few regular expressions get on the same input. The rules below come from the dialect prompts
(st2fb/llm/prompt_files/dialect_*.md), which is the same text a model reads. It does not read reference.st, and a test checks that.

It is not a compiler. It does not parse the dialect, it has no type checker beyond the declarations it can see, and it handles only the
constructs of this corpus. Anything it cannot rewrite either raises FrontendError or is left for the translator to reject. Arrays stay
arrays: flattening them is compiler work, and it is left out on purpose so that the tier stays what it says it is.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable


class FrontendError(ValueError):
    """The source holds something these rules do not cover."""


# ---- Calls with named arguments ----


def _split_arguments(text: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for char in text:
        depth += {"(": 1, "[": 1, ")": -1, "]": -1}.get(char, 0)
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    return [part.strip() for part in parts + [current]]


def _rewrite_calls(text: str, name: str, rewrite: Callable[[dict[str | int, str]], str]) -> str:
    """Replace each call of `name`. Arguments are keyed by upper-case name if named, and by position if not. Nested calls are done first."""
    head = re.compile(rf"\b{name}\s*\(")
    out, position = "", 0
    while (match := head.search(text, position)) is not None:
        end, depth = match.end(), 1
        while depth:
            depth += {"(": 1, ")": -1}.get(text[end], 0)
            end += 1
        arguments: dict[str | int, str] = {}
        for index, raw in enumerate(_split_arguments(_rewrite_calls(text[match.end() : end - 1], name, rewrite))):
            named = re.fullmatch(r"(\w+)\s*:=\s*(.*)", raw, flags=re.DOTALL)
            if named:
                arguments[named.group(1).upper()] = named.group(2)
            else:
                arguments[index] = raw
        out += text[position : match.start()] + rewrite(arguments)
        position = end
    return out + text[position:]


def _as_real(text: str) -> str:
    return f"{text}.0" if re.fullmatch(r"\d+", text.strip()) else text


# ---- Siemens SCL ----

_SCL_NAMES = {
    "Bool": "BOOL", "DInt": "DINT", "UInt": "UINT", "Int": "INT", "Real": "REAL", "Time": "TIME", "Word": "UINT",
    "TON_TIME": "TON", "TOF_TIME": "TOF", "TP_TIME": "TP", "CTU_INT": "CTU", "IEC_TIMER": "TON", "VAR_TEMP": "VAR",
}
_SCL_CALLS: tuple[tuple[str, Callable[[dict[str | int, str]], str]], ...] = (
    ("T_ADD", lambda a: f"({a['IN1']} + {a['IN2']})"),
    ("T_SUB", lambda a: f"({a['IN1']} - {a['IN2']})"),
    ("NORM_X", lambda a: f"((INT_TO_REAL({a['VALUE']}) - {_as_real(a['MIN'])}) / ({_as_real(a['MAX'])} - {_as_real(a['MIN'])}))"),
    ("SCALE_X", lambda a: f"({a['VALUE']} * ({a['MAX']} - {a['MIN']}) + {a['MIN']})"),
    ("LIMIT", lambda a: f"LIMIT({a['MN']}, {a['IN']}, {a['MX']})"),
    ("MIN", lambda a: f"MIN({a['IN1']}, {a['IN2']})"),
    ("MAX", lambda a: f"MAX({a['IN1']}, {a['IN2']})"),
    ("SEL", lambda a: f"SEL({a['G']}, {a['IN0']}, {a['IN1']})"),
    ("ROUND", lambda a: f"REAL_TO_DINT({a[0]})"),
    ("SQR", lambda a: f"(({a[0]}) * ({a[0]}))"),
    ("UINT_TO_WORD", lambda a: a[0]),
    ("WORD_TO_UINT", lambda a: a[0]),
)


def _inline_constants(text: str) -> str:
    constants: dict[str, str] = {}

    def collect(match: re.Match[str]) -> str:
        constants.update({name: value.strip() for name, value in re.findall(r"(\w+)\s*:\s*\w+\s*:=\s*([^;]+);", match.group(1))})
        return ""

    text = re.sub(r"VAR CONSTANT(.*?)END_VAR", collect, text, flags=re.DOTALL)
    for name, value in constants.items():
        text = re.sub(rf"\b{name}\b", value, text)
    return text


def _flatten_struct_arrays(text: str) -> str:
    """`x : Array[r] of Struct a : T; END_STRUCT;` becomes one array per member, and `x[i].a` becomes `x_a[i]`. Still arrays."""

    def declare(match: re.Match[str]) -> str:
        members = re.findall(r"(\w+)\s*:\s*(\w+)\s*;", match.group(3))
        return "\n".join(f"{match.group(1)}_{member} : ARRAY[{match.group(2)}] OF {kind};" for member, kind in members)

    text = re.sub(r"(\w+)\s*:\s*Array\[(\d+\.\.\d+)\]\s+of\s+Struct(.*?)END_STRUCT;", declare, text, flags=re.DOTALL)
    return re.sub(r"(\w+)\[((?:[^\[\]]|\([^()]*\))*)\]\.(\w+)", r"\1_\3[\2]", text)


def _nesting(text: str) -> int:
    opened = len(re.findall(r"\b(IF|CASE|FOR|WHILE)\b", text))
    closed = len(re.findall(r"\b(END_IF|END_CASE|END_FOR|END_WHILE)\b", text))
    return opened - closed


def _remove_return(text: str) -> str:
    """`IF c THEN ... RETURN; END_IF; rest` at the top of the body becomes `IF c THEN ... ELSE rest END_IF;`."""
    match = re.search(r"\bIF\s+([^;]*?)\s+THEN((?:(?!END_IF).)*?)\bRETURN;\s*END_IF;", text, flags=re.DOTALL)
    if match is None or _nesting(text[: match.start()]) > 0 or _nesting(match.group(2)) > 0:
        return text  # A RETURN further in is left, and scl_to_st refuses it.
    end = text.index("END_FUNCTION_BLOCK")
    head = f"IF {match.group(1)} THEN{match.group(2)}ELSE\n" if match.group(2).strip() else f"IF NOT ({match.group(1)}) THEN\n"
    return text[: match.start()] + head + text[match.end() : end] + "END_IF;\n" + text[end:]


def _remove_continue(text: str) -> str:
    """`IF NOT c THEN CONTINUE; END_IF; rest END_FOR;` becomes `IF c THEN rest END_IF; END_FOR;`."""
    match = re.search(r"\bIF\s+NOT\s+([^;]*?)\s+THEN\s*CONTINUE;\s*END_IF;(.*?)END_FOR;", text, flags=re.DOTALL)
    if match is None:
        return text
    return text[: match.start()] + f"IF {match.group(1)} THEN {match.group(2)} END_IF;\nEND_FOR;" + text[match.end() :]


def scl_to_st(source: str) -> str:
    text = re.sub(r"//[^\n]*", "", source)
    text = re.sub(r"\{[^}]*\}", "", text)
    text = re.sub(r"^\s*(TITLE|AUTHOR|FAMILY|NAME|VERSION)\b.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r'FUNCTION_BLOCK\s+"(\w+)"', r"FUNCTION_BLOCK \1", text)
    text = re.sub(r"(?<![0-9A-Za-z_])#(?=[A-Za-z_])", "", text)  # Keeps 16#0000 and T#5s.
    text = re.sub(r"^\s*(BEGIN|END_REGION|REGION\b.*)$", "", text, flags=re.MULTILINE)
    text = _inline_constants(text)
    text = _flatten_struct_arrays(text)
    for vendor, plain in _SCL_NAMES.items():
        text = re.sub(rf"\b{vendor}\b", plain, text)
    text = re.sub(r"\.TON\(", "(", text)
    text = re.sub(r"(\w+)\s*\+=\s*([^;]+);", r"\1 := \1 + \2;", text)
    for name, rewrite in _SCL_CALLS:
        text = _rewrite_calls(text, name, rewrite)
    text = text.replace("16#0000", "0")
    # Bit n of a word. The dialect only writes bits of a word just set to 0, so a write is an addition.
    text = re.sub(r"(\w+)\.%X(\d+)\s*:=\s*([^;]+);", lambda m: f"IF {m.group(3)} THEN {m.group(1)} := {m.group(1)} + {2 ** int(m.group(2))}; END_IF;", text)
    text = re.sub(r"(\w+)\.%X(\d+)", lambda m: f"(({m.group(1)} / {2 ** int(m.group(2))}) MOD 2 = 1)", text)
    text = _remove_return(text)
    text = _remove_continue(text)
    for keyword in ("RETURN", "CONTINUE"):
        if re.search(rf"\b{keyword}\s*;", text):
            raise FrontendError(f"a {keyword} these rules cannot rewrite is left")
    return text


# ---- Rockwell Logix structured text ----

_TONR = """{t}_EN := {t}_TimerEnable;
IF {t}_EN THEN
  IF {t}_PREV AND NOT {t}_DN THEN
    {t}_ACC := {t}_ACC + TaskPeriodMs;
    IF {t}_ACC >= {t}_PRE THEN
      {t}_ACC := {t}_PRE;
      {t}_DN := TRUE;
    END_IF;
  END_IF;
ELSE
  {t}_ACC := 0;
  {t}_DN := FALSE;
END_IF;
{t}_TT := {t}_EN AND NOT {t}_DN;
{t}_PREV := {t}_EN;
"""
_CTUD = """IF {t}_CUEnable AND NOT {t}_PREV THEN
  {t}_ACC := {t}_ACC + 1;
END_IF;
{t}_PREV := {t}_CUEnable;
{t}_DN := {t}_ACC >= {t}_PRE;
"""
_OSRI = """{t}_OutputBit := {t}_InputBit AND NOT {t}_PREV;
{t}_PREV := {t}_InputBit;
"""
_RES_TIMER = "{t}_ACC := 0;\n{t}_EN := FALSE;\n{t}_TT := FALSE;\n{t}_DN := FALSE;\n{t}_PREV := FALSE;\n"
_RES_COUNTER = "{t}_ACC := 0;\n{t}_DN := FALSE;\n"
_MEMBERS = {
    "FBD_TIMER": (("TimerEnable", "BOOL"), ("PRE", "DINT"), ("EN", "BOOL"), ("TT", "BOOL"), ("DN", "BOOL"), ("ACC", "DINT"), ("PREV", "BOOL")),
    "FBD_COUNTER": (("CUEnable", "BOOL"), ("PRE", "DINT"), ("ACC", "DINT"), ("DN", "BOOL"), ("PREV", "BOOL")),
    "FBD_ONESHOT": (("InputBit", "BOOL"), ("OutputBit", "BOOL"), ("PREV", "BOOL")),
}


def l5k_to_st(source: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    name = re.search(r"ADD_ON_INSTRUCTION_DEFINITION\s+(\w+)", text)
    local_tags = re.search(r"LOCAL_TAGS(.*?)END_LOCAL_TAGS", text, flags=re.DOTALL)
    routine = re.search(r"ST_ROUTINE\s+\w+(.*?)END_ST_ROUTINE", text, flags=re.DOTALL)
    if name is None or local_tags is None or routine is None:
        raise FrontendError("not an ADD_ON_INSTRUCTION_DEFINITION with LOCAL_TAGS and one ST_ROUTINE")
    parameters = re.findall(r"(\w+)\s*:\s*(\w+)\s*\(Usage\s*:=\s*(Input|Output)\)", text)
    types = {tag: kind for tag, kind, _ in parameters}
    instances: dict[str, str] = {}
    declarations = []
    for tag, kind in re.findall(r"(\w+)\s*:\s*(\w+)\s*;", local_tags.group(1)):
        if kind in _MEMBERS:
            instances[tag] = kind
            for member, member_kind in _MEMBERS[kind]:
                declarations.append(f"{tag}_{member} : {member_kind};")
                types[f"{tag}_{member}"] = member_kind
        else:
            declarations.append(f"{tag} : {kind};")
            types[tag] = kind

    def call(match: re.Match[str]) -> str:
        instruction, tag = match.group(1).upper(), match.group(2)
        if instruction == "RES":
            return (_RES_TIMER if instances[tag] == "FBD_TIMER" else _RES_COUNTER).format(t=tag)
        return {"TONR": _TONR, "CTUD": _CTUD, "OSRI": _OSRI}[instruction].format(t=tag)

    body = routine.group(1).replace("[:=", ":=")
    body = re.sub(r"\b(TONR|CTUD|OSRI|RES)\((\w+)\)\s*;", call, body)
    body = re.sub(r"(\b[A-Za-z_]\w*)\.([A-Za-z]\w*)", r"\1_\2", body)
    # Bit n of a DINT. The dialect only writes bits of a word just set to 0, so a write is an addition.
    body = re.sub(r"(\b\w+)\.(\d+)\s*:=\s*([^;]+);", lambda m: f"IF {m.group(3)} THEN {m.group(1)} := {m.group(1)} + {2 ** int(m.group(2))}; END_IF;", body)
    body = re.sub(r"(\b[A-Za-z_]\w*)\.(\d+)", lambda m: f"(({m.group(1)} / {2 ** int(m.group(2))}) MOD 2 = 1)", body)
    body = re.sub(r"(\b\w+)\s*:=\s*([01])\s*;", lambda m: f"{m.group(1)} := {'TRUE' if m.group(2) == '1' else 'FALSE'};" if types.get(m.group(1)) == "BOOL" else m.group(0), body)

    def widen(match: re.Match[str]) -> str:
        """Logix converts DINT to REAL implicitly, and matiec and the translator do not. Mechanical: inside an assignment to a REAL."""
        if types.get(match.group(1)) != "REAL":
            return match.group(0)
        return match.group(1) + match.group(2) + re.sub(r"\b\w+\b", lambda m: f"DINT_TO_REAL({m.group(0)})" if types.get(m.group(0)) == "DINT" else m.group(0), match.group(3)) + ";"

    body = re.sub(r"(\b\w+)(\s*:=\s*)([^;]+);", widen, body)
    lines = [f"FUNCTION_BLOCK {name.group(1)}", "VAR_INPUT"]
    lines += [f"  {tag} : {kind};" for tag, kind, usage in parameters if usage == "Input"]
    lines += ["END_VAR", "VAR_OUTPUT"]
    lines += [f"  {tag} : {kind};" for tag, kind, usage in parameters if usage == "Output"]
    lines += ["END_VAR", "VAR"] + [f"  {line}" for line in declarations] + ["END_VAR", body, "END_FUNCTION_BLOCK"]
    return "\n".join(lines) + "\n"


# ---- Plain ST ----


def iec_to_st(source: str) -> str:
    """The one rule for plain ST: USINT widens to UINT, which the translator accepts. Nothing else here is syntax."""
    return re.sub(r"\bUSINT\b", "UINT", source)


REWRITES: dict[str, Callable[[str], str]] = {"siemens_scl": scl_to_st, "rockwell_logix": l5k_to_st, "iec_st_extended": iec_to_st}


def to_plain_st(source: str, dialect: str | None) -> str:
    if dialect is None:
        return iec_to_st(source)
    if dialect not in REWRITES:
        raise FrontendError(f"no rules for dialect {dialect!r}")
    return REWRITES[dialect](source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rewrite a vendor source of corpus_hard/ into plain ST.")
    parser.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    dialect = {".scl": "siemens_scl", ".l5k": "rockwell_logix"}.get(args.source.suffix, "iec_st_extended")
    sys.stdout.write(to_plain_st(args.source.read_text(encoding="utf-8"), dialect))
    return 0


if __name__ == "__main__":
    sys.exit(main())
