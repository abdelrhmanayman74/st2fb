#!/usr/bin/env python3
"""How deep does each stimulus take x01_pump_station? Counts scans in each pump state, on real matiec.

    python3 scripts/x01_state_reach.py

STATE is internal, so a copy of the program with three more outputs runs, used for this count only. Nothing else about the copy differs, and a check here confirms that every
original output is unchanged. A stimulus that never leaves state 0 would test little, which is what the review found: interlocks toggled at random kept the station idle for most scans.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from st2fb import reference_run  # noqa: E402

PROGRAM = REPO / "corpus_hard" / "stress" / "x01_pump_station"
STATE_NAMES = {0: "idle", 1: "proving", 2: "running", 3: "waiting to retry", 4: "locked out"}


def instrumented(source: str) -> str:
    """Expose each unit's STATE and RETRIES as outputs of the station."""
    text = source.replace("  LOCKED : BOOL;\n  RETRIES : INT;\n", "  LOCKED : BOOL;\n  RETRIES : INT;\n  STATE_OUT : INT;\n", 1)
    text = text.replace("  LOCKED := STATE = 4;\n", "  LOCKED := STATE = 4;\n  STATE_OUT := STATE;\n", 1)
    text = text.replace("  STATION_ALARM : BOOL;\nEND_VAR", "  STATION_ALARM : BOOL;\n  S_1, S_2, S_3 : INT;\nEND_VAR", 1)
    text = text.replace("  RUN_1 := U1.RUN;\n", "  S_1 := U1.STATE_OUT;\n  S_2 := U2.STATE_OUT;\n  S_3 := U3.STATE_OUT;\n  RUN_1 := U1.RUN;\n", 1)
    return text


def reach(stimulus_name: str, container: reference_run.Container) -> dict[str, object]:
    source = (PROGRAM / "program.st").read_text(encoding="utf-8")
    stimulus = json.loads((PROGRAM / stimulus_name).read_text(encoding="utf-8"))
    original = reference_run.run_reference(source, stimulus, container)
    trace = reference_run.run_reference(instrumented(source), stimulus, container)
    for before, after in zip(original["scans"], trace["scans"]):
        if any(before[name] != after[name] for name in original["outputs"]):
            raise SystemExit("the instrumented copy differs from the program")
    counts: dict[int, dict[int, int]] = {}
    for pump in (1, 2, 3):
        counts[pump] = {state: sum(scan[f"S_{pump}"] == state for scan in trace["scans"]) for state in STATE_NAMES}
    return {
        "scans": len(trace["scans"]),
        "counts": counts,
        "retries": max(max(scan[f"RETRIES_{pump}"] for scan in trace["scans"]) for pump in (1, 2, 3)),
        "stages": sorted({scan["STAGES"] for scan in trace["scans"]}),
        "duty": sorted({scan["DUTY"] for scan in trace["scans"]}),
    }


def main() -> int:
    reference_run.ensure_image()
    failed = False
    with reference_run.Container() as container:
        for name in ("stimulus.json", "heldout_stimulus.json", "heldout_stimulus_2.json"):
            result = reach(name, container)
            print(f"{name}: {result['scans']} scans. Highest retry count {result['retries']}. Stages {result['stages']}. Duty {result['duty']}.")
            for pump, counts in result["counts"].items():
                print(f"  pump {pump}: " + ", ".join(f"{STATE_NAMES[state]} {count}" for state, count in counts.items()))
                failed = failed or any(count == 0 for count in counts.values())
            failed = failed or result["retries"] <= 2
    print("FAILED: a state goes unvisited, or no retry count passes 2." if failed else "Every pump reaches every state on every stimulus, and a retry count passes 2 on every stimulus.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
