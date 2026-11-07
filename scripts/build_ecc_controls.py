#!/usr/bin/env python3
"""Build corpus_hard/ecc_persistent/<program>/control.fbt: persistent-form migrations designed by hand.

    python3 scripts/build_ecc_controls.py

These are solvability controls. They show that the ecc_persistent form can reach behavioural equality with matiec on
real FORTE for each program in the mode, so that a model failing there is a real result and not an impossible task. They
are never shown to a model. tests/test_ecc_metric.py runs them.

Each ECC below is written out by hand. Only the ST text of the algorithms goes through the translator's lowering, so
that the timers and other standard FBs inside them are the same code the baseline uses. The shape is the same in all of them:

    WAIT_k --REQ[abort-like condition]--> the abort step, --REQ--> STEP_k
    STEP_k runs the shared prelude, this step's algorithm and CNF, then its exit guards lead to the next WAIT.

No state is passed through by every scan, and between two scans the ECC itself is the position.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from st2fb import fbt  # noqa: E402
from st2fb.st import parse_program, print_statements  # noqa: E402
from st2fb.translate import SCAN_CLOCK, SCAN_DT, _Lowering  # noqa: E402

OUT = REPO / "corpus_hard" / "ecc_persistent"
CLOCK = f"{SCAN_CLOCK} := {SCAN_CLOCK} + {SCAN_DT};\n"


def lowered(declarations: str, name: str, body: str) -> str:
    """The body as the translator would lower it, given the program's declarations."""
    fb = parse_program(f"FUNCTION_BLOCK {name}\n{declarations}\n{body}\nEND_FUNCTION_BLOCK\n")
    return print_statements(_Lowering(fb).statements(fb.body))


def build(source: str, algorithms: dict[str, str], states: list[tuple[str, list[str], bool]], transitions: list[tuple[str, str, str]]) -> str:
    """states: (name, algorithms in order, emit CNF after them). transitions: (from, to, condition), in priority order."""
    fb = parse_program(source)
    declarations = source[source.index("VAR_INPUT"):source.rindex("END_VAR") + len("END_VAR")]
    lowering = _Lowering(fb)
    inputs = [fbt.VarDeclaration(d.name, d.type) for d in fb.inputs]
    if lowering.uses_timers:
        inputs.append(fbt.VarDeclaration(SCAN_DT, "TIME"))
    outputs = [fbt.VarDeclaration(d.name, d.type) for d in fb.outputs]
    internal = [fbt.VarDeclaration(d.name, d.type, None) for d in lowering.internal]
    ec_states = [fbt.ECState("START", (), 0, 0)]
    for index, (name, ran, emit) in enumerate(states, 1):
        actions = [fbt.ECAction(algorithm, "CNF" if emit and position == len(ran) - 1 else None) for position, algorithm in enumerate(ran)]
        if emit and not ran:
            actions = [fbt.ECAction(None, "CNF")]
        ec_states.append(fbt.ECState(name, tuple(actions), 200 * ((index - 1) % 5 + 1), 150 * ((index - 1) // 5)))
    bodies = []
    for name, text in algorithms.items():
        bodies.append(fbt.Algorithm(name, (CLOCK if name == "clock" else lowered(declarations, fb.name, text))))
    return fbt.write_fbt(fbt.FBType(
        name=fb.name,
        comment="Solvability control: ecc_persistent form, designed by hand. Never shown to a model.",
        event_inputs=(fbt.Event("REQ", tuple(v.name for v in inputs)),),
        event_outputs=(fbt.Event("CNF", tuple(v.name for v in outputs)),),
        input_vars=tuple(inputs),
        output_vars=tuple(outputs),
        internal_vars=tuple(internal),
        states=tuple(ec_states),
        transitions=tuple(fbt.ECTransition(a, b, c, 0, 0) for a, b, c in transitions),
        algorithms=tuple(bodies),
    ))


def case_sequencer(source: str) -> str:
    prelude = """IF NOT HOLD THEN
    STEP_TIMER(IN := TIMING, PT := STEP_TIME);
  END_IF;
  FILL_VALVE := FALSE;
  MIXER := FALSE;
  DRAIN_VALVE := FALSE;
  RINSE_VALVE := FALSE;
"""
    algorithms = {
        "clock": "",
        "prelude": prelude,
        "step0": "TIMING := FALSE;\nIF START_PB THEN\n  SEQ := 1;\nEND_IF;\n",
        "step1": "FILL_VALVE := TRUE;\nIF LEVEL_HIGH THEN\n  SEQ := 2;\n  TIMING := TRUE;\nEND_IF;\n",
        "step2": "MIXER := TRUE;\nIF STEP_TIMER.Q THEN\n  SEQ := 3;\n  TIMING := FALSE;\nEND_IF;\n",
        "step3": "DRAIN_VALVE := TRUE;\nIF LEVEL_LOW THEN\n  SEQ := 4;\nEND_IF;\n",
        "rinse": "RINSE_VALVE := TRUE;\nIF STEP_TIMER.Q THEN\n  SEQ := SEQ + 1;\n  TIMING := FALSE;\nELSE\n  TIMING := TRUE;\nEND_IF;\n",
        "step7": "CYCLES := CYCLES + 1;\nSEQ := 0;\n",
        "abort": "SEQ := 8;\n",
        "step8": "TIMING := FALSE;\nDRAIN_VALVE := TRUE;\nIF LEVEL_LOW AND NOT ABORT THEN\n  SEQ := 0;\nEND_IF;\n",
    }
    states: list[tuple[str, list[str], bool]] = []
    transitions: list[tuple[str, str, str]] = []
    steps = {0: "step0", 1: "step1", 2: "step2", 3: "step3", 4: "rinse", 5: "rinse", 6: "rinse", 7: "step7", 8: "step8"}
    wait = {k: ("START" if k == 0 else f"WAIT_{k}") for k in steps}
    for k, algorithm in steps.items():
        if k != 0:
            states.append((wait[k], [], False))
        states.append((f"STEP_{k}", ["clock", "prelude", algorithm], True))
    states.append(("ABORTING", ["clock", "prelude", "abort", "step8"], True))
    for k in steps:
        if k != 8:
            transitions.append((wait[k], "ABORTING", "REQ[ABORT]"))
        transitions.append((wait[k], f"STEP_{k}", "REQ"))
    exits = {0: "START_PB", 1: "LEVEL_HIGH", 2: "STEP_TIMER_Q", 3: "LEVEL_LOW", 4: "STEP_TIMER_Q", 5: "STEP_TIMER_Q", 6: "STEP_TIMER_Q"}
    for k, condition in exits.items():
        transitions.append((f"STEP_{k}", wait[k + 1], f"[{condition}]"))
        transitions.append((f"STEP_{k}", wait[k], "1"))
    transitions.append(("STEP_7", "START", "1"))
    for state in ("STEP_8", "ABORTING"):
        transitions.append((state, "START", "[LEVEL_LOW AND NOT ABORT]"))
        transitions.append((state, wait[8], "1"))
    return build(source, algorithms, states, transitions)


def batch_filling(source: str) -> str:
    prelude = """START_EDGE(CLK := START_PB);
  NET_WEIGHT := WEIGHT - TARE;
  FAST_VALVE := FALSE;
  SLOW_VALVE := FALSE;
  COUNT_PULSE := FALSE;
"""
    start = "TARE := WEIGHT;\nNET_WEIGHT := 0.0;\nACCEPTED := FALSE;\nREJECTED := FALSE;\nSTATE_NO := 1;\n"
    algorithms = {
        "clock": "",
        "prelude": prelude,
        "abort": "STATE_NO := 0;\nACCEPTED := FALSE;\nREJECTED := FALSE;\n",
        "step0": f"IF START_EDGE.Q AND NOT ABORT THEN\n{start}END_IF;\n",
        "step1": "FAST_VALVE := TRUE;\nSLOW_VALVE := TRUE;\nIF NET_WEIGHT >= TARGET - SLOW_BAND THEN\n  STATE_NO := 2;\nEND_IF;\n",
        "step2": "SLOW_VALVE := TRUE;\nIF NET_WEIGHT >= TARGET THEN\n  STATE_NO := 3;\nEND_IF;\n",
        "step3": "IF SETTLE_TIMER.Q THEN\n  IF (NET_WEIGHT >= TARGET - TOLERANCE) AND (NET_WEIGHT <= TARGET + TOLERANCE) THEN\n    ACCEPTED := TRUE;\n    COUNT_PULSE := TRUE;\n  ELSE\n    REJECTED := TRUE;\n  END_IF;\n  STATE_NO := 4;\nEND_IF;\n",
        "step4": f"IF START_EDGE.Q THEN\n{start}END_IF;\n",
        "post": "SETTLE_TIMER(IN := STATE_NO = 3, PT := SETTLE_TIME);\nCOUNTER(CU := COUNT_PULSE, R := RESET_COUNT, PV := 1000);\nBATCH_COUNT := COUNTER.CV;\n",
    }
    wait = {k: ("START" if k == 0 else f"WAIT_{k}") for k in range(5)}
    states: list[tuple[str, list[str], bool]] = []
    for k in range(5):
        if k != 0:
            states.append((wait[k], [], False))
        states.append((f"STEP_{k}", ["clock", "prelude", f"step{k}", "post"], True))
    states.append(("ABORTED", ["clock", "prelude", "abort", "step0", "post"], True))
    transitions: list[tuple[str, str, str]] = []
    for k in range(5):
        transitions.append((wait[k], "ABORTED", "REQ[ABORT]"))
        transitions.append((wait[k], f"STEP_{k}", "REQ"))
    # Step 0 and the abort step leave only to step 1. The other steps leave only to the next one, and 4 back to 1.
    transitions += [
        ("STEP_0", "WAIT_1", "[STATE_NO = 1]"), ("STEP_0", "START", "1"),
        ("ABORTED", "WAIT_1", "[STATE_NO = 1]"), ("ABORTED", "START", "1"),
        ("STEP_1", "WAIT_2", "[STATE_NO = 2]"), ("STEP_1", "WAIT_1", "1"),
        ("STEP_2", "WAIT_3", "[STATE_NO = 3]"), ("STEP_2", "WAIT_2", "1"),
        ("STEP_3", "WAIT_4", "[STATE_NO = 4]"), ("STEP_3", "WAIT_3", "1"),
        ("STEP_4", "WAIT_1", "[STATE_NO = 1]"), ("STEP_4", "WAIT_4", "1"),
    ]
    return build(source, algorithms, states, transitions)


def pump_supervisor(source: str) -> str:
    text = source[source.index("(* Level filter"):]
    prelude = text[: text.index("IF NOT AUTO_MODE AND STATE_NO <> 5")]
    post = text[text.index("PROOF_TIMER(IN :="): text.rindex("END_FUNCTION_BLOCK")]
    algorithms = {
        "clock": "",
        "prelude": prelude,
        "force_off": "STATE_NO := 0;\n",
        "step0": "IF AUTO_MODE THEN\n  STATE_NO := 1;\nEND_IF;\n",
        "step1": "IF LEAD_FAILED AND LAG_FAILED THEN\n  STATE_NO := 5;\nELSIF LEAD_FAILED THEN\n  LEAD_IS_2 := NOT LEAD_IS_2;\nELSIF FILTERED_LEVEL >= START_LEVEL THEN\n  STARTS := STARTS + 1;\n  STATE_NO := 2;\nEND_IF;\n",
        "step2": "IF LEAD_FAILED THEN\n  STATE_NO := 1;\nELSIF LEAD_RUNNING_FB THEN\n  STATE_NO := 3;\nEND_IF;\n",
        "step3": "IF LEAD_FAILED THEN\n  STATE_NO := 1;\nELSIF FILTERED_LEVEL <= STOP_LEVEL THEN\n  LEAD_IS_2 := NOT LEAD_IS_2;\n  STATE_NO := 1;\nELSIF (FILTERED_LEVEL >= LAG_LEVEL) AND NOT LAG_FAILED THEN\n  STATE_NO := 4;\nEND_IF;\n",
        "step4": "IF LEAD_FAILED THEN\n  STATE_NO := 1;\nELSIF LAG_FAILED OR (FILTERED_LEVEL < LAG_LEVEL) THEN\n  STATE_NO := 3;\nEND_IF;\n",
        "step5": "IF NOT (LEAD_FAILED OR LAG_FAILED) THEN\n  STATE_NO := 0;\nEND_IF;\n",
        "post": post,
    }
    wait = {k: ("START" if k == 0 else f"WAIT_{k}") for k in range(6)}
    states: list[tuple[str, list[str], bool]] = []
    for k in range(6):
        if k != 0:
            states.append((wait[k], [], False))
        states.append((f"STEP_{k}", ["clock", "prelude", f"step{k}", "post"], True))
    states.append(("FORCED_OFF", ["clock", "prelude", "force_off", "step0", "post"], True))
    transitions: list[tuple[str, str, str]] = []
    for k in (1, 2, 3, 4):
        transitions.append((wait[k], "FORCED_OFF", "REQ[NOT AUTO_MODE]"))
    for k in range(6):
        transitions.append((wait[k], f"STEP_{k}", "REQ"))
    leaving = {
        "STEP_0": [(1, "[STATE_NO = 1]"), (0, "1")],
        "FORCED_OFF": [(1, "[STATE_NO = 1]"), (0, "1")],
        "STEP_1": [(5, "[STATE_NO = 5]"), (2, "[STATE_NO = 2]"), (1, "1")],
        "STEP_2": [(1, "[STATE_NO = 1]"), (3, "[STATE_NO = 3]"), (2, "1")],
        "STEP_3": [(1, "[STATE_NO = 1]"), (4, "[STATE_NO = 4]"), (3, "1")],
        "STEP_4": [(1, "[STATE_NO = 1]"), (3, "[STATE_NO = 3]"), (4, "1")],
        "STEP_5": [(0, "[STATE_NO = 0]"), (5, "1")],
    }
    for state, exits in leaving.items():
        transitions += [(state, wait[k], condition) for k, condition in exits]
    return build(source, algorithms, states, transitions)


def star_delta(source: str) -> str:
    algorithms = {
        "clock": "",
        "logic": "RUN_CMD := (START_PB OR RUN_CMD) AND NOT STOP_PB AND NOT OVERLOAD;\nSTAR_TIMER(IN := RUN_CMD, PT := STAR_TIME);\nGAP_TIMER(IN := STAR_TIMER.Q, PT := T#50ms);\nSTAR_ELAPSED := STAR_TIMER.ET;\n",
        "off": "K_MAIN := FALSE;\nK_STAR := FALSE;\nK_DELTA := FALSE;\n",
        "star": "K_MAIN := TRUE;\nK_STAR := TRUE;\nK_DELTA := FALSE;\n",
        "gap": "K_MAIN := TRUE;\nK_STAR := FALSE;\nK_DELTA := FALSE;\n",
        "delta": "K_MAIN := TRUE;\nK_STAR := FALSE;\nK_DELTA := TRUE;\n",
    }
    states = [
        ("WAIT_STAR", [], False), ("WAIT_GAP", [], False), ("WAIT_DELTA", [], False),
        ("FROM_OFF", ["clock", "logic"], False), ("FROM_STAR", ["clock", "logic"], False),
        ("FROM_GAP", ["clock", "logic"], False), ("FROM_DELTA", ["clock", "logic"], False),
        ("OFF", ["off"], True), ("STAR", ["star"], True), ("GAP", ["gap"], True), ("DELTA", ["delta"], True),
    ]
    transitions = [
        ("START", "FROM_OFF", "REQ"), ("WAIT_STAR", "FROM_STAR", "REQ"), ("WAIT_GAP", "FROM_GAP", "REQ"), ("WAIT_DELTA", "FROM_DELTA", "REQ"),
        # Which positions can follow which is the state machine that the timers imply.
        ("FROM_OFF", "OFF", "[NOT RUN_CMD]"), ("FROM_OFF", "STAR", "1"),
        ("FROM_STAR", "OFF", "[NOT RUN_CMD]"), ("FROM_STAR", "GAP", "[STAR_TIMER_Q]"), ("FROM_STAR", "STAR", "1"),
        ("FROM_GAP", "OFF", "[NOT RUN_CMD]"), ("FROM_GAP", "DELTA", "[GAP_TIMER_Q]"), ("FROM_GAP", "GAP", "1"),
        ("FROM_DELTA", "OFF", "[NOT RUN_CMD]"), ("FROM_DELTA", "DELTA", "1"),
        ("OFF", "START", "1"), ("STAR", "WAIT_STAR", "1"), ("GAP", "WAIT_GAP", "1"), ("DELTA", "WAIT_DELTA", "1"),
    ]
    return build(source, algorithms, states, transitions)


BUILDERS = {
    "06_star_delta": star_delta,
    "13_case_sequencer": case_sequencer,
    "14_batch_filling": batch_filling,
    "20_pump_station_supervisor": pump_supervisor,
}


def main() -> None:
    for name, builder in BUILDERS.items():
        source = (REPO / "corpus" / name / "program.st").read_text(encoding="utf-8")
        target = OUT / name / "control.fbt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(builder(source), encoding="utf-8")
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
