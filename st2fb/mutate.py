"""Seeded mutation testing: does the comparison catch injected bugs?

Three modes:

    # Write N mutated copies of a migrated block, one bug in its ST algorithm text each.
    python3 -m st2fb.mutate fbt build/X/X.fbt --count 20 --seed 61499 --out-dir build/X/mutants

    # The same for a source program. Only the body is mutated, never the declarations.
    python3 -m st2fb.mutate st corpus/X/program.st --count 20 --seed 61499 --out-dir build/X/st_mutants

    # Whole corpus, matiec against mutated matiec, and write docs/MUTATION_RESULTS.md.
    python3 -m st2fb.mutate campaign --corpus corpus --count 20 --seed 61499 --report docs/MUTATION_RESULTS.md

    # Every mutant on every scored stimulus, with no cap, and which stimulus saw what. See docs/HARD_MUTATION_RESULTS.md.
    python3 -m st2fb.mutate campaign --corpus corpus_hard --uncapped --report docs/HARD_MUTATION_RESULTS.md --save-json corpus_hard/mutation_results.json

A mutant the compiler rejects says nothing about the comparison, so it is not counted. A mutant that
crashes or hangs is counted as killed, and shown separately. A survivor may be equivalent to the
original or may expose a weak stimulus, and only inspection can tell which. Detection rate is
killed / (killed + survived).
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from st2fb.compare import compare_traces
from st2fb.reference_run import CompileFailed, Container, RunFailed, ensure_image, run_reference

DEFAULT_TIME_STEP_MS = 10

_TOKEN = re.compile(
    r"""
    (?P<skip>\s+|\(\*.*?\*\)|//[^\n]*)
  | (?P<time>(?:TIME|T)\#[0-9a-zA-Z_.]+)
  | (?P<based>[0-9A-Za-z_]+\#[0-9a-zA-Z_.]+)
  | (?P<real>\d[\d_]*\.\d[\d_]*(?:[eE][-+]?\d+)?)
  | (?P<int>\d[\d_]*)
  | (?P<word>[A-Za-z_]\w*)
  | (?P<op>:=|<=|>=|<>|\.\.|\*\*|[-+*/=<>(),;:.&\[\]])
    """,
    re.VERBOSE | re.DOTALL | re.IGNORECASE,
)

_OPERATOR_SWAPS = {"AND": "OR", "OR": "AND", "XOR": "OR", "+": "-", "-": "+", "*": "/", "/": "*", "MOD": "/", "**": "*"}
_BOUNDARY_SWAPS = {"<": "<=", "<=": "<", ">": ">=", ">=": ">", "=": "<>", "<>": "="}
_NOT_A_STATEMENT = {
    "IF", "ELSIF", "ELSE", "END_IF", "CASE", "END_CASE", "FOR", "END_FOR", "WHILE", "END_WHILE",
    "REPEAT", "UNTIL", "END_REPEAT", "END_FUNCTION_BLOCK", "END_FUNCTION",
}  # fmt: skip
_STATEMENT_BOUNDARY = {";", "THEN", "ELSE", "DO", "REPEAT", ":"}


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int

    @property
    def upper(self) -> str:
        return self.text.upper()


@dataclass(frozen=True)
class Mutant:
    kind: str
    description: str
    text: str  # the complete mutated ST text


def tokenize(text: str) -> list[Token]:
    tokens = []
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise ValueError(f"cannot tokenize ST at offset {position}: {text[position:position + 20]!r}")
        if match.lastgroup != "skip":
            tokens.append(Token(str(match.lastgroup), match.group(), match.start(), match.end()))
        position = match.end()
    return tokens


def _time_literal_ms(text: str) -> int | None:
    """Value of T#500ms or T#2s in ms, or None for anything more elaborate."""
    match = re.fullmatch(r"(?:TIME|T)#(\d+)(ms|s)", text, flags=re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1)) * (1000 if match.group(2).lower() == "s" else 1)


class _Builder:
    """Collects mutants of one text, each described by the edit that creates it."""

    def __init__(self, text: str, label: str = "") -> None:
        self.text = text
        self.label = label
        self.mutants: list[Mutant] = []

    def _line(self, offset: int) -> int:
        return self.text.count("\n", 0, offset) + 1

    def _position(self, offset: int) -> str:
        """line:column, which makes descriptions unique within a program."""
        return f"{self._line(offset)}:{offset - self.text.rfind(chr(10), 0, offset)}"

    def edit(self, kind: str, start: int, end: int, replacement: str, note: str | None = None) -> None:
        before = " ".join(self.text[start:end].split())
        note = note or f"{before!r} -> {replacement!r}"
        description = f"{self.label}line {self._position(start)}: {kind}: {note}"
        self.mutants.append(Mutant(kind, description, self.text[:start] + replacement + self.text[end:]))


def _is_binary(tokens: list[Token], i: int) -> bool:
    """True if the operator at i has a left operand, which rules out unary minus."""
    if i == 0:
        return False
    previous = tokens[i - 1]
    keywords = {"IF", "ELSIF", "THEN", "NOT", "TO", "BY", "AND", "OR", "XOR", "MOD", "WHILE", "CASE", "UNTIL"}
    return previous.text == ")" or previous.kind in ("real", "int", "time") or (
        previous.kind == "word" and previous.upper not in keywords
    )


def _simple_mutations(builder: _Builder, tokens: list[Token], time_step_ms: int) -> None:
    for i, token in enumerate(tokens):
        if token.upper in _OPERATOR_SWAPS and (token.kind == "word" or _is_binary(tokens, i)):
            builder.edit("operator", token.start, token.end, _OPERATOR_SWAPS[token.upper])
        elif token.text in _BOUNDARY_SWAPS:
            builder.edit("boundary", token.start, token.end, _BOUNDARY_SWAPS[token.text])
        elif token.kind == "int":
            value = int(token.text.replace("_", ""))
            builder.edit("constant", token.start, token.end, str(value + 1))
            builder.edit("constant", token.start, token.end, str(value - 1))
        elif token.kind == "real":
            value_real = float(token.text.replace("_", ""))
            builder.edit("constant", token.start, token.end, repr(value_real + 1.0))
            builder.edit("constant", token.start, token.end, repr(value_real - 1.0))
        elif token.kind == "time":
            # +/-1 ms is invisible on a coarser scan grid, so the step is one scan: the smallest
            # change to a time constant that the trace can show.
            milliseconds = _time_literal_ms(token.text)
            if milliseconds is not None:
                builder.edit("constant", token.start, token.end, f"T#{milliseconds + time_step_ms}ms")
                if milliseconds > time_step_ms:
                    builder.edit("constant", token.start, token.end, f"T#{milliseconds - time_step_ms}ms")
        elif token.upper in ("TRUE", "FALSE"):
            builder.edit("constant", token.start, token.end, "FALSE" if token.upper == "TRUE" else "TRUE")


def _condition_mutations(builder: _Builder, tokens: list[Token]) -> None:
    for i, token in enumerate(tokens):
        if token.upper not in ("IF", "ELSIF", "WHILE", "UNTIL"):
            continue
        closer = {"WHILE": "DO", "UNTIL": "END_REPEAT"}.get(token.upper, "THEN")
        j = next(k for k in range(i + 1, len(tokens)) if tokens[k].upper == closer)
        start, end = tokens[i + 1].start, tokens[j - 1].end
        condition = builder.text[start:end]
        one_line = " ".join(condition.split())
        builder.edit("negate", start, end, f"NOT ({condition})", f"{token.upper} condition {one_line!r} negated")


def _branch_swaps(builder: _Builder, tokens: list[Token]) -> None:
    """Swap the bodies of adjacent branches of each IF."""
    # Each open IF holds a list of (body start, body end); an open CASE holds None, so that
    # a CASE's ELSE is not mistaken for an IF's.
    stack: list[list[tuple[int, int]] | None] = []
    body_start: list[int] = []
    for i, token in enumerate(tokens):
        word = token.upper
        if word == "IF":
            stack.append([])
            body_start.append(0)
        elif word == "CASE":
            stack.append(None)
            body_start.append(0)
        elif not stack:
            continue
        elif word == "THEN" and stack[-1] is not None:
            body_start[-1] = token.end
        elif word in ("ELSIF", "ELSE") and stack[-1] is not None:
            stack[-1].append((body_start[-1], tokens[i - 1].end))
            if word == "ELSE":
                body_start[-1] = token.end
        elif word == "END_CASE":
            stack.pop()
            body_start.pop()
        elif word == "END_IF":
            branches = stack.pop()
            start = body_start.pop()
            assert branches is not None
            branches.append((start, tokens[i - 1].end))
            for (a_start, a_end), (b_start, b_end) in zip(branches, branches[1:]):
                text = builder.text
                swapped = (
                    text[:a_start] + text[b_start:b_end] + text[a_end:b_start] + text[a_start:a_end] + text[b_end:]
                )
                description = (
                    f"{builder.label}line {builder._position(a_start)}: swap: "
                    f"branch body swapped with the one at line {builder._line(b_start)}"
                )
                builder.mutants.append(Mutant("swap", description, swapped))


def _statement_removals(builder: _Builder, tokens: list[Token]) -> None:
    i = 0
    while i < len(tokens):
        token = tokens[i]
        at_start = i == 0 or tokens[i - 1].upper in _STATEMENT_BOUNDARY
        if at_start and token.kind == "word" and token.upper not in _NOT_A_STATEMENT:
            depth = 0
            j = i
            while tokens[j].text != ";" or depth > 0:
                depth += {"(": 1, ")": -1}.get(tokens[j].text, 0)
                j += 1
            one_line = " ".join(builder.text[token.start : tokens[j].end].split())
            builder.edit("remove", token.start, tokens[j].end, "", f"removed {one_line!r}")
            i = j
        i += 1


def all_mutants(text: str, time_step_ms: int = DEFAULT_TIME_STEP_MS, label: str = "") -> list[Mutant]:
    """Every mutant of a piece of ST statement text, in a fixed order."""
    tokens = tokenize(text)
    builder = _Builder(text, label)
    _simple_mutations(builder, tokens, time_step_ms)
    _condition_mutations(builder, tokens)
    _branch_swaps(builder, tokens)
    _statement_removals(builder, tokens)
    return builder.mutants


def select_mutants(mutants: list[Mutant], count: int, seed: str | int) -> list[Mutant]:
    """Pick count mutants, taking kinds in turn so that rare kinds are not crowded out."""
    rng = random.Random(str(seed))
    by_kind: dict[str, list[Mutant]] = {}
    for mutant in mutants:
        by_kind.setdefault(mutant.kind, []).append(mutant)
    for group in by_kind.values():
        rng.shuffle(group)
    selected: list[Mutant] = []
    kinds = sorted(by_kind)
    while len(selected) < count and any(by_kind.values()):
        for kind in kinds:
            if by_kind[kind] and len(selected) < count:
                selected.append(by_kind[kind].pop())
    return selected


def body_spans(st_text: str) -> list[tuple[int, int]]:
    """Offsets of the statements of each FUNCTION_BLOCK or FUNCTION: after its last END_VAR, up to its end.

    A helper block in the same file is mutated too, since it is part of what the oracle computes.
    """
    # Comments are blanked, keeping every offset, so that a comment cannot open or close a block.
    masked = re.sub(r"\(\*.*?\*\)", lambda m: " " * len(m.group()), st_text, flags=re.DOTALL)
    spans = []
    position = 0
    for closing in re.finditer(r"\bEND_FUNCTION(?:_BLOCK)?\b", masked, flags=re.IGNORECASE):
        ends = list(re.finditer(r"\bEND_VAR\b", masked[position : closing.start()], flags=re.IGNORECASE))
        start = position + ends[-1].end() if ends else position
        spans.append((start, closing.start()))
        position = closing.end()
    if not spans:
        raise ValueError("no END_FUNCTION_BLOCK found")
    return spans


def st_mutants(st_text: str, time_step_ms: int = DEFAULT_TIME_STEP_MS) -> list[Mutant]:
    result = []
    for start, end in body_spans(st_text):
        body = st_text[start:end]
        line_offset = st_text.count("\n", 0, start)
        for mutant in all_mutants(body, time_step_ms):
            # Report lines as they are in the source file, not in the extracted body.
            description = re.sub(
                r"(line )(\d+)", lambda m: f"{m.group(1)}{int(m.group(2)) + line_offset}", mutant.description
            )
            result.append(Mutant(mutant.kind, description, st_text[:start] + mutant.text + st_text[end:]))
    return result


_FBT_ALGORITHM = re.compile(
    r"""(<Algorithm\b[^>]*\bName="(?P<name>[^"]*)"[^>]*>\s*<ST>)(?P<body>.*?)(</ST>)""", re.DOTALL
)


def fbt_mutants(fbt_text: str, time_step_ms: int = DEFAULT_TIME_STEP_MS) -> list[Mutant]:
    """Mutate the ST of each algorithm of an .fbt, leaving the ECC and the interface alone."""
    result = []
    for match in _FBT_ALGORITHM.finditer(fbt_text):
        raw = match.group("body").strip()
        cdata = re.fullmatch(r"<!\[CDATA\[(.*)\]\]>", raw, flags=re.DOTALL)
        algorithm = cdata.group(1) if cdata else html.unescape(raw)
        label = f"algorithm {match.group('name')}, "
        for mutant in all_mutants(algorithm, time_step_ms, label):
            replacement = f"<![CDATA[{mutant.text}]]>"
            text = fbt_text[: match.start("body")] + replacement + fbt_text[match.end("body") :]
            result.append(Mutant(mutant.kind, mutant.description, text))
    if not result:
        raise ValueError("no mutable <Algorithm><ST> text found in the .fbt")
    return result


def write_mutants(mutants: list[Mutant], out_dir: Path, suffix: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, mutant in enumerate(mutants):
        name = f"mutant_{i:03d}{suffix}"
        (out_dir / name).write_text(mutant.text)
        manifest.append({"file": name, "kind": mutant.kind, "description": mutant.description})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(mutants)} mutants to {out_dir}")


# ---- campaign: matiec against mutated matiec ----


def _run_mutant(st_text: str, stimulus: dict[str, Any], baseline: dict[str, Any], container: Container) -> str:
    try:
        trace = run_reference(st_text, stimulus, container)
    except CompileFailed:
        return "compile_failed"
    except RunFailed:
        return "crashed"
    return "survived" if compare_traces(baseline, trace)["equal"] else "killed"


def oracle_file(program_dir: Path) -> Path:
    """The ST that matiec runs for this program: reference.st where a program is paired with one."""
    reference = program_dir / "reference.st"
    return reference if reference.exists() else program_dir / "program.st"


def program_dirs(corpus: Path) -> list[Path]:
    """Program directories directly under corpus, or one level further down for corpus_hard/<set>/<program>."""
    direct = sorted(path.parent for path in corpus.glob("*/stimulus.json"))
    return direct or sorted(path.parent for path in corpus.glob("*/*/stimulus.json"))


def run_program(
    program_dir: Path, count: int, seed: int, pool: ThreadPoolExecutor, container: Container
) -> dict[str, Any]:
    st_text = oracle_file(program_dir).read_text()
    stimulus = json.loads((program_dir / "stimulus.json").read_text())
    baseline = run_reference(st_text, stimulus, container)
    # Control: the unmutated program must equal itself, or a "kill" could just be flakiness.
    control_equal = compare_traces(baseline, run_reference(st_text, stimulus, container))["equal"]

    available = st_mutants(st_text, stimulus["scan_ms"])
    selected = select_mutants(available, count, f"{seed}:{program_dir.name}")
    outcomes = list(pool.map(lambda m: _run_mutant(m.text, stimulus, baseline, container), selected))
    return {
        "program": program_dir.name,
        "scans": len(stimulus["scans"]),
        "available": len(available),
        "control_equal": control_equal,
        "mutants": [
            {"kind": m.kind, "description": m.description, "outcome": outcome}
            for m, outcome in zip(selected, outcomes)
        ],
    }


def scored_stimuli(program_dir: Path) -> list[Path]:
    """Tuning first, then every held-out file."""
    return [program_dir / "stimulus.json", *sorted(program_dir.glob("heldout_stimulus*.json"))]


def run_program_uncapped(program_dir: Path, pool: ThreadPoolExecutor, container: Container) -> dict[str, Any]:
    """Every mutant, on every scored stimulus. A mutant the compiler rejects on one is rejected on all, so it runs once."""
    st_text = oracle_file(program_dir).read_text()
    paths = scored_stimuli(program_dir)
    stimuli = {path.stem: json.loads(path.read_text()) for path in paths}
    baselines = {name: run_reference(st_text, stimulus, container) for name, stimulus in stimuli.items()}
    control_equal = all(compare_traces(baselines[name], run_reference(st_text, stimuli[name], container))["equal"] for name in stimuli)
    available = st_mutants(st_text, stimuli["stimulus"]["scan_ms"])

    def judge(mutant: Mutant) -> dict[str, str]:
        outcomes: dict[str, str] = {}
        for name, stimulus in stimuli.items():
            outcomes[name] = _run_mutant(mutant.text, stimulus, baselines[name], container)
            if outcomes[name] == "compile_failed":
                return {other: "compile_failed" for other in stimuli}
        return outcomes

    results = list(pool.map(judge, available))
    mutants = []
    for mutant, outcomes in zip(available, results):
        values = set(outcomes.values())
        overall = "compile_failed" if "compile_failed" in values else "killed" if "killed" in values else "crashed" if "crashed" in values else "survived"
        mutants.append({"kind": mutant.kind, "description": mutant.description, "outcome": overall, "by_stimulus": outcomes})
    return {
        "program": program_dir.name,
        "set": program_dir.parent.name,
        "scans": {name: len(stimulus["scans"]) for name, stimulus in stimuli.items()},
        "scan_ms": {name: stimulus["scan_ms"] for name, stimulus in stimuli.items()},
        "available": len(available),
        "control_equal": control_equal,
        "mutants": mutants,
    }


_DETECTED = ("killed", "crashed")


def split_detection(mutant: dict[str, Any]) -> tuple[bool, bool]:
    """(seen on tuning, seen on any held-out file)."""
    outcomes = mutant["by_stimulus"]
    return outcomes["stimulus"] in _DETECTED, any(value in _DETECTED for name, value in outcomes.items() if name != "stimulus")


def render_uncapped_report(results: list[dict[str, Any]], notes: dict[str, Any], before: dict[str, int] | None, notes_path: str) -> str:
    everything = [mutant for result in results for mutant in result["mutants"]]
    counted = [mutant for mutant in everything if mutant["outcome"] != "compile_failed"]
    survivors = [(result["program"], mutant) for result in results for mutant in result["mutants"] if mutant["outcome"] == "survived"]
    tuning = sum(split_detection(mutant)[0] for mutant in counted)
    heldout = sum(split_detection(mutant)[1] for mutant in counted)
    only_tuning = sum(split_detection(mutant) == (True, False) for mutant in counted)
    only_heldout = sum(split_detection(mutant) == (False, True) for mutant in counted)
    lines = [
        "# Mutation results, corpus_hard",
        "",
        "Generated by `python3 -m st2fb.mutate campaign --corpus corpus_hard --uncapped`. Every number comes from running matiec on the original and on each mutant, then",
        f"comparing traces with `st2fb.compare`. The forward path and FORTE are not involved. Do not edit by hand, except through `{notes_path}`.",
        "",
        "Every mutant of every program, with no cap and no sampling, run on every scored stimulus: `stimulus.json`, `heldout_stimulus.json` and `heldout_stimulus_2.json`. For a paired",
        "program it mutates `reference.st`, so it asks whether the stimuli would notice a slip in the hand translation of about this size. It does not show that a pairing is correct.",
        "",
        f"**Detected on some scored stimulus: {len(counted) - len(survivors)} of {len(counted)} counted mutants ({100.0 * (len(counted) - len(survivors)) / len(counted):.1f}%)**, "
        f"{len(survivors)} survived all of them, {len(everything) - len(counted)} rejected by the compiler and not counted.",
        "",
        f"On tuning alone: {tuning} of {len(counted)}. On held-out alone: {heldout} of {len(counted)}. Only tuning saw {only_tuning}. **Only held-out saw {only_heldout}.**",
    ]
    if before:
        lines += [
            "",
            f"Before this revision, from the independent review's uncapped run on the earlier corpus (tuning and one held-out file, {before['counted']} counted): tuning {before['tuning']}, held-out {before['heldout']}, "
            f"neither {before['neither']}, only tuning {before['only_tuning']}, only held-out {before['only_heldout']}.",
        ]
    lines += [
        "",
        "Detected means killed or crashed, where crashed means the mutant hung past the time limit, died on a signal, or produced a non-finite REAL. Control is the unmutated program against a second run of itself on every stimulus.",
        "",
        "## Per program: what held-out sees and tuning does not",
        "",
        "| Set | Program | Mutants | Compile-failed | Counted | Tuning detected | Held-out detected | Both | Tuning only | Held-out only | Survived all | Rate | Control |",
        "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|",
    ]
    for result in results:
        mine = [mutant for mutant in result["mutants"] if mutant["outcome"] != "compile_failed"]
        split = [split_detection(mutant) for mutant in mine]
        left = sum(mutant["outcome"] == "survived" for mutant in mine)
        rate = f"{100.0 * (len(mine) - left) / len(mine):.1f}%" if mine else "n/a"
        lines.append(
            f"| {result['set']} | {result['program']} | {result['available']} | {result['available'] - len(mine)} | {len(mine)} | {sum(a for a, _ in split)} | {sum(b for _, b in split)} "
            f"| {sum(a and b for a, b in split)} | {sum(a and not b for a, b in split)} | {sum(b and not a for a, b in split)} | {left} | {rate} | {'equal' if result['control_equal'] else 'DIFFERENT'} |"
        )
    lines += ["", "## By mutation kind", "", "| Kind | Compile-failed | Counted | Detected | Survived | Rate |", "|---|--:|--:|--:|--:|--:|"]
    for kind in sorted({mutant["kind"] for mutant in everything}):
        mine = [mutant for mutant in everything if mutant["kind"] == kind]
        counted_kind = [mutant for mutant in mine if mutant["outcome"] != "compile_failed"]
        left = sum(mutant["outcome"] == "survived" for mutant in counted_kind)
        rate = f"{100.0 * (len(counted_kind) - left) / len(counted_kind):.1f}%" if counted_kind else "n/a"
        lines.append(f"| {kind} | {len(mine) - len(counted_kind)} | {len(counted_kind)} | {len(counted_kind) - left} | {left} | {rate} |")
    survivor_notes = notes.get("survivors", notes)
    verdicts: dict[str, int] = {}
    rows = []
    for program, mutant in survivors:
        note = survivor_notes.get(f"{program}|{mutant['description']}")
        verdict, reason = (note["verdict"], note["reason"]) if isinstance(note, dict) else ("not analysed", note or "not analysed")
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        rows.append(f"| {program} | `{mutant['description'].replace('|', chr(92) + '|')}` | {verdict} | {reason} |")
    lines += ["", "## Survivors", "", "Every mutant that survived all scored stimuli, read one by one. **Each analysis is a reasoned argument from reading the program and the mutant. It is not a proof, and no equivalence checker was run.**", ""]
    lines += [f"Of {len(survivors)}: " + ", ".join(f"{count} {verdict}" for verdict, count in sorted(verdicts.items())) + ".", ""]
    if rows:
        lines += ["| Program | Mutant | Verdict | Analysis |", "|---|---|---|---|"] + rows
    else:
        lines.append("None.")
    if notes.get("findings"):
        lines += ["", "## Notes on what the mutants exercise", ""] + notes["findings"]
    return "\n".join(lines) + "\n"


def campaign_uncapped(args: argparse.Namespace) -> int:
    results = []
    if args.from_json:
        results = json.loads(Path(args.from_json).read_text())
    else:
        ensure_image()
        programs = program_dirs(Path(args.corpus))
        if args.only:
            programs = [path for path in programs if path.name in args.only]
        with ThreadPoolExecutor(max_workers=args.jobs) as pool, Container() as container:
            for program_dir in programs:
                result = run_program_uncapped(program_dir, pool, container)
                counts = {"survived": 0, "killed": 0, "crashed": 0, "compile_failed": 0}
                for mutant in result["mutants"]:
                    counts[mutant["outcome"]] += 1
                split = [split_detection(mutant) for mutant in result["mutants"] if mutant["outcome"] != "compile_failed"]
                print(f"{result['program']}: {counts} tuning only {sum(a and not b for a, b in split)} held-out only {sum(b and not a for a, b in split)}", flush=True)
                results.append(result)
                if args.save_json:  # After every program, so an interrupted run keeps what it did.
                    Path(args.save_json).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.save_json).write_text(json.dumps(results, indent=1) + "\n")
    notes = json.loads(Path(args.notes).read_text()) if args.notes and Path(args.notes).exists() else {}
    before = json.loads(Path(args.before).read_text()) if args.before else None
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(render_uncapped_report(results, notes, before, args.notes))
    return 0 if all(result["control_equal"] for result in results) else 1


def _tally(mutants: list[dict[str, Any]]) -> dict[str, int]:
    tally = {"killed": 0, "crashed": 0, "survived": 0, "compile_failed": 0}
    for mutant in mutants:
        tally[mutant["outcome"]] += 1
    return tally


def _rate(tally: dict[str, int]) -> str:
    detected = tally["killed"] + tally["crashed"]
    total = detected + tally["survived"]
    return f"{100.0 * detected / total:.1f}%" if total else "n/a"


def render_report(
    results: list[dict[str, Any]],
    count: int,
    seed: int,
    baseline: list[dict[str, Any]] | None,
    notes: dict[str, str],
    history: dict[str, list[dict[str, Any]]] | None = None,
    notes_path: str = "corpus/mutation_survivor_notes.json",
) -> str:
    everything = [mutant for result in results for mutant in result["mutants"]]
    overall = _tally(everything)
    detected = overall["killed"] + overall["crashed"]
    lines = [
        "# Mutation results",
        "",
        "Generated by `python3 -m st2fb.mutate campaign`. Every number comes from running matiec on the",
        "original and on each mutant, then comparing traces with `st2fb.compare`. The forward path and",
        f"FORTE are not involved. Do not edit by hand, except through `{notes_path}`.",
        "",
        f"Run with `--count {count} --seed {seed}`. A count above what a program has selects all its mutants.",
        "",
        f"**Overall detection rate: {_rate(overall)}**, {detected} of {detected + overall['survived']} counted "
        f"mutants detected, {overall['survived']} survived, {overall['compile_failed']} compile-failed and not counted.",
    ]
    if baseline is not None:
        before = _tally([mutant for result in baseline for mutant in result["mutants"]])
        lines += [
            "",
            f"Before stimulus improvements, on the same selection method: **{_rate(before)}**, "
            f"{before['killed'] + before['crashed']} of {before['killed'] + before['crashed'] + before['survived']} "
            f"counted, {before['survived']} survived, {before['compile_failed']} compile-failed.",
        ]
    lines += [
        "",
        "Rate = detected / (detected + survived). Detected = killed plus crashed, where crashed means the",
        "mutant hung past the time limit, died on a signal, or produced a non-finite REAL. Control = the",
        "unmutated program compared with a second run of itself. The section on mutation testing in",
        "`docs/CORPUS.md` covers how to read these numbers and what changed between the runs.",
        "",
        "## Per program",
        "",
    ]
    before_by_name = {result["program"]: _tally(result["mutants"]) for result in baseline or []}
    header = "| Program | Scans | Mutants available | Selected | Compile-failed | Total counted | Killed | Crashed | Survived | Rate | Control |"
    rule = "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|"
    if baseline is not None:
        header += " Rate before |"
        rule += "--:|"
    lines += [header, rule]
    for result in results:
        tally = _tally(result["mutants"])
        total = tally["killed"] + tally["crashed"] + tally["survived"]
        row = (
            f"| {result['program']} | {result['scans']} | {result['available']} | {len(result['mutants'])} "
            f"| {tally['compile_failed']} | {total} | {tally['killed']} | {tally['crashed']} | {tally['survived']} "
            f"| {_rate(tally)} | {'equal' if result['control_equal'] else 'DIFFERENT'} |"
        )
        if baseline is not None:
            old = before_by_name.get(result["program"])
            row += f" {_rate(old) if old else 'n/a'} |"
        lines.append(row)

    lines += ["", "## By mutation kind", "", "| Kind | Compile-failed | Total counted | Detected | Survived | Rate |", "|---|--:|--:|--:|--:|--:|"]
    for kind in sorted({mutant["kind"] for mutant in everything}):
        tally = _tally([mutant for mutant in everything if mutant["kind"] == kind])
        found = tally["killed"] + tally["crashed"]
        lines.append(
            f"| {kind} | {tally['compile_failed']} | {found + tally['survived']} | {found} | {tally['survived']} | {_rate(tally)} |"
        )

    if history:
        lines += [
            "",
            "## Other runs",
            "",
            "Raw results of other runs on the same program text, so on the same mutants.",
            "",
            "| Raw results | Selected | Compile-failed | Total counted | Detected | Survived | Rate |",
            "|---|--:|--:|--:|--:|--:|--:|",
        ]
        for label, run_results in history.items():
            mutants = [mutant for result in run_results for mutant in result["mutants"]]
            tally = _tally(mutants)
            found = tally["killed"] + tally["crashed"]
            lines.append(
                f"| `{label}` | {len(mutants)} | {tally['compile_failed']} | {found + tally['survived']} "
                f"| {found} | {tally['survived']} | {_rate(tally)} |"
            )

    lines += ["", "## Survivors", "", "Every surviving mutant. Each reason comes from reading the program and the mutant.", ""]
    survivors = [
        (result["program"], mutant["description"])
        for result in results
        for mutant in result["mutants"]
        if mutant["outcome"] == "survived"
    ]
    if survivors:
        lines += ["| Program | Mutant | Analysis |", "|---|---|---|"]
        for program, description in survivors:
            analysis = notes.get(f"{program}|{description}", "not analysed")
            cell = description.replace("|", "\\|")
            lines.append(f"| {program} | `{cell}` | {analysis} |")
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"


def campaign(args: argparse.Namespace) -> int:
    ensure_image()
    programs = program_dirs(Path(args.corpus))
    if args.only:
        programs = [path for path in programs if path.name in args.only]
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool, Container() as container:
        for program_dir in programs:
            result = run_program(program_dir, args.count, args.seed, pool, container)
            tally = _tally(result["mutants"])
            print(f"{result['program']}: {tally} rate {_rate(tally)}", flush=True)
            results.append(result)

    if args.save_json:
        Path(args.save_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save_json).write_text(json.dumps(results, indent=1) + "\n")
    baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else None
    notes = json.loads(Path(args.notes).read_text()) if args.notes and Path(args.notes).exists() else {}
    history = {path: json.loads(Path(path).read_text()) for path in args.history}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(render_report(results, args.count, args.seed, baseline, notes, history, args.notes))
    return 0 if all(result["control_equal"] for result in results) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seeded mutation of ST, to prove the comparison catches bugs.")
    modes = parser.add_subparsers(dest="mode", required=True)
    for mode in ("fbt", "st"):
        sub = modes.add_parser(mode, help=f"write mutants of a .{mode} file")
        sub.add_argument("path")
        sub.add_argument("--count", type=int, default=20)
        sub.add_argument("--seed", type=int, default=61499)
        sub.add_argument("--time-step-ms", type=int, default=DEFAULT_TIME_STEP_MS)
        sub.add_argument("--out-dir", required=True)
    run = modes.add_parser("campaign", help="matiec against mutated matiec over a corpus")
    run.add_argument("--corpus", default="corpus")
    run.add_argument("--count", type=int, default=20, help="mutants selected per program")
    run.add_argument("--seed", type=int, default=61499)
    run.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    run.add_argument("--only", nargs="*", help="restrict to these program directories")
    run.add_argument("--report", help="Markdown report to write")
    run.add_argument("--save-json", help="raw results to write")
    run.add_argument("--baseline", help="raw results of an earlier run, shown as 'before'")
    run.add_argument("--history", nargs="*", default=[], help="raw results of other runs to summarise")
    run.add_argument("--notes", default="corpus/mutation_survivor_notes.json", help="survivor analysis")
    run.add_argument("--uncapped", action="store_true", help="every mutant on every scored stimulus. --count and --seed then play no part")
    run.add_argument("--before", help="with --uncapped: a JSON file of the earlier totals, shown as 'before'")
    run.add_argument("--from-json", help="with --uncapped: render the report from saved results, without running")
    args = parser.parse_args(argv)

    if args.mode == "campaign":
        return campaign_uncapped(args) if args.uncapped else campaign(args)
    source = Path(args.path).read_text()
    generate = fbt_mutants if args.mode == "fbt" else st_mutants
    selected = select_mutants(generate(source, args.time_step_ms), args.count, args.seed)
    write_mutants(selected, Path(args.out_dir), Path(args.path).suffix)
    return 0


if __name__ == "__main__":
    sys.exit(main())
