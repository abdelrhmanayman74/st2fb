#!/usr/bin/env python3
"""Plausible faults a migration could make, and correct rewrites it could make. Which stimulus sees each one, on real matiec?

    python3 scripts/check_plausible_faults.py

Mutation testing changes one token at a time. These are the mistakes someone migrating the program might make: a hard-coded scan period, a reset that forgets a member, a bit read without
its mask. `fault` means a scored stimulus should see it. `correct` means the edit keeps the behaviour, usually by reordering REAL arithmetic, so it should pass within the comparison's tolerance, and a difference there would be a false alarm.
`rounding` means the maths is the same, and a difference is only a rounding error made larger by cancellation near zero, which the relative tolerance has no floor for. It has no expected result, and docs/HARD_CORPUS.md lists it.
Each is matiec on the original against matiec on the edited text, so it says what the stimuli can see, and nothing about FORTE. tests/test_hard_corpus.py runs the hard-coded period on real FORTE.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from st2fb import reference_run  # noqa: E402
from st2fb.compare import compare_traces  # noqa: E402
from st2fb.mutate import oracle_file, program_dirs, scored_stimuli  # noqa: E402

CASES = [
    ("r01_motor_aoi", "fault", "TaskPeriodMs hard-coded as 10", "+ TaskPeriodMs", "+ 10"),
    ("r01_motor_aoi", "fault", "RES leaves the previous enable", "    Fb_PREV := FALSE;\n", ""),
    ("r01_motor_aoi", "fault", "TONR counts on the first enabled scan", "IF Delay_PREV AND NOT Delay_DN THEN", "IF NOT Delay_DN THEN"),
    ("r02_fill_retry_aoi", "fault", "TaskPeriodMs hard-coded as 10 in the timers", "+ TaskPeriodMs;", "+ 10;"),
    ("r02_fill_retry_aoi", "fault", "TaskPeriodMs hard-coded as 10.0 in the totaliser", "DINT_TO_REAL(TaskPeriodMs)", "10.0"),
    ("r02_fill_retry_aoi", "correct", "counter RES also clears its previous input: RES(OpenTimer) clears the counter's input on the same scan, so no reading differs", "    Retries_DN := FALSE;\n    Open_ACC", "    Retries_DN := FALSE;\n    Retries_PREV := FALSE;\n    Open_ACC"),
    ("r03_sequence_aoi", "fault", "TaskPeriodMs hard-coded as 10", "+ TaskPeriodMs;", "+ 10;"),
    ("r04_alarm_word_aoi", "fault", "TaskPeriodMs hard-coded as 10", "+ TaskPeriodMs;", "+ 10;"),
    ("r04_alarm_word_aoi", "fault", "mask bit read as >= without MOD", "Mask2 := (MaskWord / 4) MOD 2 = 1;", "Mask2 := MaskWord >= 4;"),
    ("s06_status_word", "fault", "bit 7 read without MOD", "tempCtl7 := (i_controlWord / 128) MOD 2 = 1;", "tempCtl7 := (i_controlWord / 128) = 1;"),
    ("s06_status_word", "correct", "speed with the constants folded", "INT_TO_REAL(i_speedRef) * 100.0 / 16384.0", "INT_TO_REAL(i_speedRef) * (100.0 / 16384.0)"),
    ("s07_heater_pi", "correct", "kp and ki terms combined", "i_kp * o_error + statIntegral + i_ki * o_error", "(i_kp + i_ki) * o_error + statIntegral"),
    ("s07_heater_pi", "correct", "x ** 2 as x * x", "o_error ** 2.0", "o_error * o_error"),
    ("s08_packaging_counter", "fault", "count not guarded by the batch size", "ELSIF tempCartonEdge AND (o_count < i_batchSize) THEN", "ELSIF tempCartonEdge THEN"),
    ("s08_packaging_counter", "fault", "max speed frozen at the tuned default", "MIN(i_speedRef, i_maxSpeed)", "MIN(i_speedRef, 100.0)"),
    ("s02_analog_input", "fault", "alarm delay frozen at the tuned value", "statDelay := i_alarmDelay;", "statDelay := T#30ms;"),
    ("r02_fill_retry_aoi", "fault", "start level frozen at the tuned value", "IF LevelPct <= StartPct THEN", "IF LevelPct <= 20.0 THEN"),
    ("r02_fill_retry_aoi", "fault", "stop level frozen at the tuned value", "ELSIF LevelPct >= StopPct THEN", "ELSIF LevelPct >= 80.0 THEN"),
    ("x01_pump_station", "fault", "ticks counted on RUN, not on STATE = 2", "IF STATE = 2 THEN\n    TICKS", "IF RUN THEN\n    TICKS"),
    ("x01_pump_station", "fault", "a tie goes to the highest pump", "(VIEW[CANDIDATE].TICKS < BEST_TICKS)", "(VIEW[CANDIDATE].TICKS <= BEST_TICKS)"),
    ("x01_pump_station", "fault", "an interlock clears a lockout", "IF NOT PERMIT AND STATE <> 4 THEN", "IF NOT PERMIT THEN"),
    ("x01_pump_station", "fault", "interlock guard tests state 3", "IF NOT PERMIT AND STATE <> 4 THEN", "IF NOT PERMIT AND STATE <> 3 THEN"),
    ("x01_pump_station", "fault", "interlock guard tests state 5", "IF NOT PERMIT AND STATE <> 4 THEN", "IF NOT PERMIT AND STATE <> 5 THEN"),
    ("x01_pump_station", "fault", "LEVEL_2 tested with >", "ELSIF LEVEL >= LEVEL_2 THEN", "ELSIF LEVEL > LEVEL_2 THEN"),
    ("x01_pump_station", "fault", "a reset ignores a thermal trip", "IF RESET AND NOT THERMAL THEN", "IF RESET THEN"),
    ("x01_pump_station", "fault", "retry delay frozen at the tuned value", "RETRY_DELAY := RETRY_DELAY, MAX_RETRIES", "RETRY_DELAY := T#30ms, MAX_RETRIES"),
    ("u01_sensor_voting", "fault", "span frozen at the tuned value", "100.0 * VOTED / SPAN", "100.0 * VOTED / 200.0"),
    ("u05_pump_duty_records", "fault", "the wear score ignores starts", "WEAR_PER_START * INT_TO_DINT(PUMP[P].STARTS)", "0 * INT_TO_DINT(PUMP[P].STARTS)"),
    ("u06_cascade_nested", "rounding", "SQRT for ** 0.5", "ABS(ERROR) ** 0.5", "SQRT(ABS(ERROR))"),
    ("p02_pi_controller", "correct", "P term distributed", "(Setpoint - ProcessVariable) * Kp", "Setpoint * Kp - ProcessVariable * Kp"),
]


def run_all() -> list[dict[str, object]]:
    directories = {path.name: path for path in program_dirs(REPO / "corpus_hard")}
    rows = []
    reference_run.ensure_image()
    with reference_run.Container() as container:
        for program, kind, label, old, new in CASES:
            directory = directories[program]
            source = oracle_file(directory).read_text(encoding="utf-8")
            if old not in source:
                raise SystemExit(f"{program}: this text is not in the oracle, so the case is stale: {old!r}")
            edited = source.replace(old, new)
            seen = {}
            for path in scored_stimuli(directory):
                stimulus = json.loads(path.read_text(encoding="utf-8"))
                report = compare_traces(reference_run.run_reference(source, stimulus, container), reference_run.run_reference(edited, stimulus, container))
                seen[path.stem] = report["divergences"]
            rows.append({"program": program, "kind": kind, "label": label, "seen": seen})
    return rows


def main() -> int:
    rows = run_all()
    failed = False
    for row in rows:
        seen = row["seen"]
        cells = " ".join(f"{name.replace('heldout_stimulus', 'heldout').replace('stimulus', 'tuning')}:{count}" for name, count in seen.items())
        wrong = row["kind"] != "rounding" and (row["kind"] == "fault") != any(seen.values())
        failed = failed or wrong
        print(f"{row['program']:24} {row['kind']:8} {row['label']:50} {cells}{'  <-- UNEXPECTED' if wrong else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
