#!/usr/bin/env python3
"""Regenerate corpus/*/stimulus.json. Same seed, same files.

    python3 corpus/generate_stimuli.py

Each scenario has a directed part, which walks the program's branches and sits exactly on its
comparison boundaries, followed by a seeded random part. REAL values are multiples of 1/8, which
are exact in binary, so feeding a stimulus to a runner involves no decimal rounding.

00_latch is hand-written and not generated here.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Callable

SEED = 61499
CORPUS = Path(__file__).resolve().parent


def eighth(value: float) -> float:
    return round(value * 8) / 8


class Stimulus:
    """Builds a scan list by changing inputs and holding them for some scans."""

    def __init__(self, name: str, scan_ms: int = 10, **defaults: Any) -> None:
        self.rng = random.Random(f"{SEED}:{name}")
        self.scan_ms = scan_ms
        self.current = dict(defaults)
        self.scans: list[dict[str, Any]] = []

    def hold(self, scans: int = 1, **changes: Any) -> "Stimulus":
        """Apply changes and keep them for this many scans."""
        self.current.update(changes)
        self.scans += [dict(self.current) for _ in range(scans)]
        return self

    def pulse(self, scans: int = 1, after: int = 1, **changes: Any) -> "Stimulus":
        """Apply changes for some scans, restore the previous values, then hold."""
        saved = {key: self.current[key] for key in changes}
        self.hold(scans, **changes)
        return self.hold(after, **saved)

    def ramp(self, name: str, end: float, scans: int) -> "Stimulus":
        """Move a REAL input in a straight line, snapped to multiples of 1/8."""
        start = self.current[name]
        for i in range(1, scans + 1):
            self.hold(1, **{name: eighth(start + (end - start) * i / scans)})
        return self

    def sweep(self, name: str, *values: float, dwell: int = 2) -> "Stimulus":
        """Visit exact values, used to sit on comparison boundaries."""
        for value in values:
            self.hold(dwell, **{name: value})
        return self

    def random_phase(
        self,
        scans: int,
        toggle: dict[str, float] | None = None,
        walk: dict[str, tuple[float, float, float]] | None = None,
        choose: dict[str, tuple[float, list[Any]]] | None = None,
    ) -> "Stimulus":
        """Random inputs. toggle: name -> flip probability per scan.
        walk: name -> (low, high, largest step). choose: name -> (change probability, values)."""
        for _ in range(scans):
            for name, probability in (toggle or {}).items():
                if self.rng.random() < probability:
                    self.current[name] = not self.current[name]
            for name, (low, high, step) in (walk or {}).items():
                value = self.current[name] + self.rng.uniform(-step, step)
                self.current[name] = eighth(min(high, max(low, value)))
            for name, (probability, values) in (choose or {}).items():
                if self.rng.random() < probability:
                    self.current[name] = self.rng.choice(values)
            self.hold(1)
        return self


def motor_start_stop(s: Stimulus) -> None:
    s.hold(5).pulse(START_PB=True, after=5).pulse(STOP_PB=True, after=5)
    s.pulse(START_PB=True, after=3).pulse(START_PB=True, STOP_PB=True, after=3)
    s.pulse(START_PB=True, after=3).pulse(OVERLOAD=True, after=3).pulse(START_PB=True, after=3)
    s.pulse(RESET_PB=True, after=3).pulse(START_PB=True, after=3)
    s.pulse(OVERLOAD=True, RESET_PB=True, after=3).pulse(RESET_PB=True, after=3)
    s.random_phase(250, toggle={"START_PB": 0.1, "STOP_PB": 0.05, "OVERLOAD": 0.02, "RESET_PB": 0.1})


def tank_hysteresis(s: Stimulus) -> None:
    s.hold(3)
    s.sweep("LEVEL", 50.0, 30.0, 20.25, 20.0, 19.75, 30.0, 79.75, 80.0, 80.25, 50.0, 20.0)
    # The alarm limits, sitting exactly on each one.
    s.sweep("LEVEL", 15.25, 15.0, 14.75, 15.0, 50.0, 84.75, 85.0, 85.25, 85.0, 50.0)
    s.pulse(5, ENABLE=False, LEVEL=10.0, after=2).hold(3, LEVEL=50.0)
    s.pulse(3, ENABLE=False, after=3)
    s.hold(2, ALARM_MARGIN=0.0).sweep("LEVEL", 20.0, 19.875, 80.0, 80.125)
    s.hold(2, ALARM_MARGIN=5.0, LEVEL=50.0)
    s.ramp("LEVEL", 90.0, 60).ramp("LEVEL", 10.0, 120)
    s.random_phase(200, toggle={"ENABLE": 0.03}, walk={"LEVEL": (0.0, 100.0, 6.0)})


def scaling_clamp(s: Stimulus) -> None:
    s.sweep("RAW", 0.0, 4.0, 3.875, 4.125, 12.0, 19.875, 20.0, 20.125, 24.0)
    s.ramp("RAW", 2.0, 40).ramp("RAW", 22.0, 80)
    s.hold(3, RAW=10.0, ENG_MIN=-50.0, ENG_MAX=150.0)
    s.sweep("RAW", 4.0, 20.0, 3.0, 21.0, 12.0)
    s.pulse(3, RAW_MAX=4.0, after=2).pulse(3, RAW_MAX=3.0, after=2).pulse(3, RAW_MAX=4.125, after=2)
    # Flags set just before the range goes bad must be cleared by it.
    s.hold(2, RAW=25.0).pulse(2, RAW_MAX=3.0, after=2).hold(2, RAW=1.0).pulse(2, RAW_MAX=3.0, after=2).hold(1, RAW=10.0)
    s.random_phase(
        200,
        walk={"RAW": (0.0, 24.0, 3.0), "ENG_MIN": (-10.0, 10.0, 0.5), "ENG_MAX": (90.0, 110.0, 0.5)},
        choose={"RAW_MIN": (0.03, [0.0, 4.0, 6.0]), "RAW_MAX": (0.03, [20.0, 16.0, 6.0, 4.0])},
    )


def parts_counter(s: Stimulus) -> None:
    for _ in range(12):
        s.pulse(SENSOR=True, after=1)
    s.pulse(RESET=True, after=2)
    s.pulse(SENSOR=True, after=1).pulse(SENSOR=True, after=1).pulse(RESET=True, after=2)
    s.hold(4, SENSOR=True).hold(2, SENSOR=False)
    s.pulse(SENSOR=True, RESET=True, after=2)
    s.hold(1, BATCH_SIZE=2)
    for _ in range(6):
        s.pulse(2, SENSOR=True, after=2)
    s.hold(1, BATCH_SIZE=1)
    for _ in range(4):
        s.pulse(SENSOR=True, after=3)
    s.hold(1, BATCH_SIZE=0).hold(3, SENSOR=True).hold(3, SENSOR=False).hold(1, BATCH_SIZE=4)
    s.random_phase(
        300,
        toggle={"SENSOR": 0.3, "RESET": 0.01},
        choose={"BATCH_SIZE": (0.02, [2, 3, 5, 8])},
    )


def alarm_debounce(s: Stimulus) -> None:
    s.hold(3)
    s.pulse(2, PROCESS_TRIP=True, after=5)  # shorter than ON_DELAY, so it must not alarm
    s.pulse(5, PROCESS_TRIP=True, after=2)  # exactly at the ON_DELAY boundary, 40 ms
    s.hold(12, PROCESS_TRIP=True).pulse(ACK=True, after=4).hold(12, PROCESS_TRIP=False)
    s.hold(10, PROCESS_TRIP=True).hold(3, PROCESS_TRIP=False)  # glitch in the off delay
    s.hold(6, PROCESS_TRIP=True).hold(10, PROCESS_TRIP=False)
    s.hold(8, ACK=True, PROCESS_TRIP=True).hold(4, ACK=False).hold(20, PROCESS_TRIP=False)
    s.pulse(ACK=True, after=3).hold(1, ON_DELAY=0, OFF_DELAY=0).pulse(3, PROCESS_TRIP=True, after=3)
    s.hold(1, ON_DELAY=40, OFF_DELAY=60)
    s.random_phase(400, toggle={"PROCESS_TRIP": 0.05, "ACK": 0.08}, choose={"ON_DELAY": (0.01, [20, 40, 70])})


def star_delta(s: Stimulus) -> None:
    s.hold(3).pulse(START_PB=True, after=70).pulse(STOP_PB=True, after=5)
    s.pulse(START_PB=True, after=20).pulse(OVERLOAD=True, after=5)
    s.pulse(START_PB=True, OVERLOAD=True, after=5)
    s.pulse(START_PB=True, after=32).pulse(STOP_PB=True, after=8)
    s.pulse(START_PB=True, after=48).pulse(STOP_PB=True, after=5)
    s.hold(1, STAR_TIME=100).pulse(START_PB=True, after=30).pulse(STOP_PB=True, after=5)
    s.hold(1, STAR_TIME=0).pulse(START_PB=True, after=12).pulse(STOP_PB=True, after=3).hold(1, STAR_TIME=300)
    s.random_phase(
        500,
        toggle={"START_PB": 0.03, "STOP_PB": 0.01, "OVERLOAD": 0.005},
        choose={"STAR_TIME": (0.005, [100, 200, 300])},
    )


def conveyor_interlock(s: Stimulus) -> None:
    s.hold(3).pulse(START_PB=True, after=40).pulse(STOP_PB=True, after=40)
    s.pulse(START_PB=True, after=8).pulse(STOP_PB=True, after=30)  # stop mid-start
    s.pulse(START_PB=True, after=40).pulse(4, ESTOP_OK=False, after=3).hold(20)
    for jam in ("JAM_C1", "JAM_C2", "JAM_C3"):
        s.pulse(START_PB=True, after=40).pulse(3, after=30, **{jam: True})
        s.pulse(START_PB=True, after=30).hold(30, **{jam: True}).pulse(START_PB=True, after=3).hold(3, **{jam: False})
        s.pulse(STOP_PB=True, after=30)
    s.hold(1, STAGGER=30).pulse(START_PB=True, after=20).pulse(STOP_PB=True, after=20).hold(1, STAGGER=100)
    s.pulse(START_PB=True, STOP_PB=True, after=30)
    s.random_phase(
        500,
        toggle={"START_PB": 0.04, "STOP_PB": 0.01, "ESTOP_OK": 0.003, "JAM_C1": 0.003, "JAM_C2": 0.003, "JAM_C3": 0.003},
    )


def first_out(s: Stimulus) -> None:
    s.hold(3)
    for trip in ("TRIP_1", "TRIP_2", "TRIP_3", "TRIP_4"):
        s.pulse(3, after=2, **{trip: True}).pulse(RESET=True, after=2)
    # Cascades in each order, where the first one must stay recorded.
    for order in (("TRIP_2", "TRIP_1"), ("TRIP_4", "TRIP_3", "TRIP_2"), ("TRIP_3", "TRIP_4"), ("TRIP_1", "TRIP_4")):
        for trip in order:
            s.hold(2, **{trip: True})
        s.pulse(RESET=True, after=1)  # refused, trips are still active
        s.hold(2, TRIP_1=False, TRIP_2=False, TRIP_3=False, TRIP_4=False).pulse(RESET=True, after=2)
    # Trips in the same scan, resolved by priority.
    s.pulse(TRIP_1=True, TRIP_2=True, TRIP_3=True, TRIP_4=True, after=2).pulse(RESET=True, after=1)
    s.pulse(TRIP_2=True, TRIP_3=True, after=2).pulse(RESET=True, after=1)
    s.pulse(TRIP_3=True, TRIP_4=True, after=2).pulse(RESET=True, after=1)
    s.pulse(RESET=True, after=1).pulse(TRIP_3=True, RESET=True, after=2).pulse(RESET=True, after=1)
    s.random_phase(300, toggle={"TRIP_1": 0.02, "TRIP_2": 0.02, "TRIP_3": 0.02, "TRIP_4": 0.02, "RESET": 0.2})


def totalizer(s: Stimulus) -> None:
    s.sweep("DP", 0.0, 1.0, 1.125, 4.0, 16.0, 100.0, dwell=20)
    s.pulse(2, RESET=True, after=10).pulse(RESET=True, DP=25.0, after=30)
    s.hold(1, PULSE_SIZE=0.25).hold(40, DP=64.0)  # several pulses per scan
    s.hold(1, PULSE_SIZE=0.5).hold(20, DP=0.5)
    # A pending volume landing exactly on the pulse size. FLOW * hours = 0.5 at DP = 16.
    s.pulse(RESET=True, after=1).hold(1, PULSE_SIZE=1.0, K_FACTOR=1.0, SCAN_HOURS=0.125, DP=16.0).hold(5)
    s.hold(1, K_FACTOR=2.0, SCAN_HOURS=0.0078125, PULSE_SIZE=0.5)
    # A DP large enough that 8 Newton iterations from x0 = DP have not converged yet, so the
    # iteration count shows in FLOW.
    s.sweep("DP", 40000.0, 250000.0, dwell=3).hold(2, DP=4.0)
    s.random_phase(300, toggle={"RESET": 0.005}, walk={"DP": (0.0, 200.0, 10.0)})


def valve_feedback(s: Stimulus) -> None:
    # Normal opening and closing.
    s.hold(5, CLOSED_LS=True).hold(5, OPEN_CMD=True).hold(10, CLOSED_LS=False).hold(10, OPENED_LS=True)
    s.hold(5, OPEN_CMD=False).hold(10, OPENED_LS=False).hold(10, CLOSED_LS=True)
    # Timeout opening, right on the limit, then reset.
    s.hold(35, OPEN_CMD=True, CLOSED_LS=False).pulse(RESET=True, after=2)
    s.hold(5, OPEN_CMD=False, CLOSED_LS=True).pulse(RESET=True, after=2)
    # Timeout closing.
    s.hold(5, OPEN_CMD=True, CLOSED_LS=False, OPENED_LS=True)
    s.hold(35, OPEN_CMD=False, OPENED_LS=False).hold(3, CLOSED_LS=True).pulse(RESET=True, after=2)
    # Travel one scan before and exactly at the limit (limit is 200 ms = 20 scans).
    s.hold(20, OPEN_CMD=True, CLOSED_LS=False).hold(4, OPENED_LS=True)
    s.hold(21, OPEN_CMD=False, OPENED_LS=False).hold(3, CLOSED_LS=True).pulse(RESET=True, after=2)
    # Both limit switches made, with reset refused while they stay made.
    s.hold(3, OPENED_LS=True, CLOSED_LS=True).pulse(RESET=True, after=2)
    s.hold(2, OPENED_LS=False).pulse(RESET=True, after=2)
    s.pulse(RESET=True, OPENED_LS=True, after=2)
    s.random_phase(
        500,
        toggle={"OPEN_CMD": 0.04, "OPENED_LS": 0.06, "CLOSED_LS": 0.06, "RESET": 0.1},
        choose={"TRAVEL_LIMIT": (0.01, [100, 200, 300])},
    )


def ramp_generator(s: Stimulus) -> None:
    s.hold(3).hold(25, SETPOINT=20.0).hold(10, SETPOINT=5.0).hold(10, SETPOINT=5.0)
    s.hold(5, SETPOINT=30.0).hold(5, HOLD=True).hold(5, HOLD=False)
    s.pulse(3, RESET=True, after=2)  # back to preset
    s.hold(20, SETPOINT=10.25).hold(20, SETPOINT=-10.25).hold(20, SETPOINT=0.0)
    s.pulse(RESET=True, HOLD=True, after=2)
    s.hold(1, RATE_UP=2.5, RATE_DOWN=0.25, SETPOINT=50.0).hold(25, SETPOINT=50.0).hold(30, SETPOINT=45.0)
    s.pulse(RESET=True, PRESET=45.0, after=3)
    s.random_phase(
        300,
        toggle={"HOLD": 0.03, "RESET": 0.01},
        walk={"SETPOINT": (-100.0, 100.0, 8.0)},
        choose={"RATE_UP": (0.02, [0.5, 1.0, 2.0]), "RATE_DOWN": (0.02, [0.25, 0.75, 1.5])},
    )


def pid_loop(s: Stimulus) -> None:
    s.hold(3, AUTO_MODE=False, MANUAL_OUT=20.0).hold(3, AUTO_MODE=True)
    s.hold(30, SP=60.0).hold(30, PV=55.0).hold(20, PV=60.0)
    # Deadband edges and just inside.
    s.sweep("PV", 59.5, 60.5, 59.0, 61.0, 58.875, 61.125, 60.0)
    # Saturation at both ends: integrating away from the limit must resume.
    s.hold(40, SP=100.0, PV=0.0).hold(10, PV=120.0).hold(40, SP=0.0).hold(10, PV=-20.0).hold(10, SP=50.0, PV=50.0)
    s.hold(4, AUTO_MODE=False, MANUAL_OUT=120.0).hold(4, MANUAL_OUT=-5.0).hold(4, MANUAL_OUT=100.0)
    s.hold(4, MANUAL_OUT=0.0).hold(4, MANUAL_OUT=42.0).hold(10, AUTO_MODE=True)
    s.hold(5, PV=30.0).hold(5, PV=35.0).hold(5, PV=25.0)
    # No deadband, saturated by a manual output past the limit, then a small error back towards
    # range. Integration must resume at once, which separates > 0 from any lower threshold.
    s.hold(2, DEADBAND=0.0, AUTO_MODE=False, MANUAL_OUT=101.0, SP=50.0, PV=50.0).hold(3, AUTO_MODE=True, PV=50.5)
    s.hold(2, AUTO_MODE=False, MANUAL_OUT=-1.0, PV=50.0).hold(3, AUTO_MODE=True, PV=49.5)
    # Saturated with a small error further into saturation, which must not integrate; a following
    # error back into range then reveals the integral through CV.
    s.hold(2, AUTO_MODE=False, MANUAL_OUT=100.0, PV=50.0).hold(2, AUTO_MODE=True, PV=49.5).hold(3, PV=50.5)
    s.hold(2, AUTO_MODE=False, MANUAL_OUT=0.0, PV=50.0).hold(2, AUTO_MODE=True, PV=50.5).hold(3, PV=49.5)
    s.hold(1, DEADBAND=1.0, MANUAL_OUT=0.0)
    s.random_phase(
        400,
        toggle={"AUTO_MODE": 0.01},
        walk={"SP": (0.0, 100.0, 2.0), "PV": (-10.0, 110.0, 4.0), "MANUAL_OUT": (-10.0, 110.0, 5.0)},
    )


def case_sequencer(s: Stimulus) -> None:
    def full_cycle() -> None:
        s.pulse(START_PB=True, after=3).pulse(2, LEVEL_HIGH=True, after=0)
        s.hold(1, LEVEL_HIGH=False).hold(15).hold(2, LEVEL_LOW=True).hold(40, LEVEL_LOW=False).hold(5)

    s.hold(3)
    full_cycle()
    # Held in the timed mix: the timer call is skipped while HOLD, but the clock runs on.
    s.pulse(START_PB=True, after=2).pulse(LEVEL_HIGH=True, after=3)
    s.hold(4, HOLD=True).hold(20, HOLD=False).pulse(LEVEL_LOW=True, after=2)
    s.hold(12, HOLD=True).hold(30, HOLD=False)
    # Abort from each phase, drain, and return to idle only once low and no longer aborting.
    s.pulse(START_PB=True, after=2).pulse(2, ABORT=True, after=3).pulse(LEVEL_LOW=True, after=2)
    s.pulse(START_PB=True, after=2).pulse(LEVEL_HIGH=True, after=3).pulse(ABORT=True, LEVEL_LOW=True, after=2)
    s.hold(2, LEVEL_LOW=True).hold(2, LEVEL_LOW=False)
    s.pulse(START_PB=True, after=2).pulse(LEVEL_HIGH=True, after=15).pulse(LEVEL_LOW=True, after=2)
    s.pulse(ABORT=True, after=3).pulse(LEVEL_LOW=True, after=2)
    s.pulse(START_PB=True, ABORT=True, after=2).pulse(ABORT=True, LEVEL_LOW=True, after=2).pulse(LEVEL_LOW=True, after=2)
    full_cycle()
    s.hold(1, STEP_TIME=30)
    full_cycle()
    s.hold(1, STEP_TIME=80)
    # Abort long enough for a still-running timer to expire, then HOLD from the end of the abort
    # into the next timed step, so that only a reset during the abort can restart the timer.
    s.pulse(START_PB=True, after=2).pulse(LEVEL_HIGH=True, after=3).pulse(ABORT=True, after=15)
    s.pulse(LEVEL_LOW=True, HOLD=True, after=0).hold(1, HOLD=True, START_PB=True).hold(1, START_PB=False, LEVEL_HIGH=True)
    s.hold(1, LEVEL_HIGH=False).hold(15, HOLD=False)
    s.pulse(LEVEL_LOW=True, after=40)
    s.random_phase(
        700,
        toggle={"START_PB": 0.1, "ABORT": 0.004, "HOLD": 0.02, "LEVEL_HIGH": 0.08, "LEVEL_LOW": 0.08},
        choose={"STEP_TIME": (0.005, [30, 80, 130])},
    )


def batch_filling(s: Stimulus) -> None:
    def fill(tare: float, final: float, settle_scans: int = 12) -> None:
        s.hold(2, WEIGHT=tare).pulse(START_PB=True, after=2)
        s.ramp("WEIGHT", tare + 89.875, 10).sweep("WEIGHT", tare + 90.0, dwell=2)
        s.ramp("WEIGHT", tare + 99.875, 10).sweep("WEIGHT", final, dwell=settle_scans)

    s.hold(3)
    fill(0.0, 100.0)
    fill(0.0, 102.0)  # exactly at the upper tolerance limit, accepted
    fill(5.0, 107.125)  # just above, rejected
    fill(5.0, 103.0)  # exactly at the lower limit relative to target, accepted after overshoot
    s.pulse(START_PB=True, after=2).hold(3, WEIGHT=30.0).pulse(ABORT=True, after=3)
    s.pulse(START_PB=True, ABORT=True, after=2)
    fill(10.0, 110.0)
    s.pulse(RESET_COUNT=True, after=3)
    fill(1.0, 101.0, settle_scans=4)  # settle interrupted by abort
    s.pulse(ABORT=True, after=3)
    # A weight drop during settle: below the lower limit, rejected.
    s.hold(2, WEIGHT=0.0).pulse(START_PB=True, after=2).sweep("WEIGHT", 90.0, 100.0, dwell=2).hold(1, WEIGHT=97.875).hold(12)
    s.hold(2, WEIGHT=0.0).pulse(START_PB=True, after=2).sweep("WEIGHT", 90.0, 100.0, dwell=2).hold(1, WEIGHT=98.0).hold(12)
    # Abort after a result: the result flags must clear on the abort, not only on the next start.
    fill(0.0, 100.0)
    s.pulse(ABORT=True, after=3)
    fill(0.0, 110.0)
    s.pulse(ABORT=True, after=3)
    s.hold(1, TARGET=50.0, SLOW_BAND=5.0, TOLERANCE=1.0, SETTLE_TIME=50)
    s.random_phase(
        600,
        toggle={"START_PB": 0.2, "ABORT": 0.005, "RESET_COUNT": 0.005},
        walk={"WEIGHT": (0.0, 70.0, 3.0)},
    )


def duty_standby(s: Stimulus) -> None:
    s.hold(3)
    for _ in range(3):
        s.hold(10, DEMAND=True, FB_A=True, FB_B=True).hold(4, DEMAND=False)
    s.hold(30, DEMAND=True, FB_A=False, FB_B=False)  # no proof: first the lead, then the other fails
    s.hold(3, DEMAND=False).pulse(RESET=True, after=3)
    s.hold(5, FB_A=True, FB_B=True, DEMAND=True).pulse(TRIP_A=True, after=8).pulse(TRIP_B=True, after=8)
    s.pulse(RESET=True, after=4).hold(5, DEMAND=False).hold(5, DEMAND=True).pulse(TRIP_B=True, after=5)
    s.pulse(TRIP_A=True, after=5).pulse(RESET=True, TRIP_A=True, after=3).pulse(RESET=True, after=3)
    # Proof arrives exactly one scan before the time limit, then exactly at it.
    s.hold(3, DEMAND=False, FB_A=False, FB_B=False).hold(10, DEMAND=True).hold(5, FB_A=True, FB_B=True)
    s.hold(3, DEMAND=False, FB_A=False, FB_B=False).hold(11, DEMAND=True).hold(5, FB_A=True, FB_B=True)
    s.hold(3, DEMAND=False).pulse(RESET=True, after=3)
    s.random_phase(
        500,
        toggle={"DEMAND": 0.03, "FB_A": 0.05, "FB_B": 0.05, "TRIP_A": 0.005, "TRIP_B": 0.005, "RESET": 0.05},
    )


def pump_level(s: Stimulus) -> None:
    def cycle() -> None:
        s.ramp("LEVEL", 2.0, 8).sweep("LEVEL", 2.875, 3.0, 2.875).ramp("LEVEL", 1.25, 8)
        s.sweep("LEVEL", 1.125, 1.0, 0.875, 1.5)

    s.hold(3)
    cycle()
    cycle()
    # Lag: on, delayed; level below the lag level restarts the delay.
    s.sweep("LEVEL", 3.0, 3.875).hold(5, LEVEL=4.0).hold(3, LEVEL=3.875).hold(12, LEVEL=4.0).hold(30, LEVEL=4.125)
    s.hold(3, LEVEL=3.0).sweep("LEVEL", 1.0, 2.0)
    # High alarm at the limit, too short and then long enough.
    s.hold(5, LEVEL=5.0).hold(3, LEVEL=4.875).hold(30, LEVEL=5.0).hold(3, LEVEL=4.875).hold(3, LEVEL=5.25)
    # Dry-run protection and manual mode.
    s.sweep("LEVEL", 3.0, 0.625, 0.5, 0.375, 3.0).pulse(4, AUTO_MODE=False, after=4)
    s.pulse(3, AUTO_MODE=False, LEVEL=5.0, after=3).hold(3, LEVEL=1.0).hold(3, LEVEL=2.0)
    s.hold(3, DRY_LEVEL=1.5, LEVEL=3.0).sweep("LEVEL", 1.5, 1.625, 3.0).hold(1, DRY_LEVEL=0.5)
    s.hold(1, LAG_DELAY=0, ALARM_DELAY=0).sweep("LEVEL", 4.0, 5.0, 1.0, 2.0).hold(1, LAG_DELAY=100, ALARM_DELAY=200)
    s.random_phase(1200, toggle={"AUTO_MODE": 0.003}, walk={"LEVEL": (0.25, 5.5, 0.25)})


def pump_protection(s: Stimulus) -> None:
    def run(on: int, off: int) -> None:
        s.hold(on, RUN_REQ=True).hold(off, RUN_REQ=False)

    s.hold(3)
    run(30, 40)  # past prime time and past the cool-down
    run(4, 3)  # short run inside the prime pulse, restart blocked by cool-down
    run(6, 40)
    # Suction boundary and delay.
    s.hold(1, RUN_REQ=True).hold(3, SUCTION=1.0).hold(3, SUCTION=0.875).hold(3, SUCTION=1.0).hold(30, SUCTION=0.875)
    s.hold(3, SUCTION=2.0).pulse(RESET=True, after=2).hold(20, RUN_REQ=False).hold(20)
    # Discharge boundary latches at once; reset while it persists is refused by the RS set priority.
    s.hold(5, RUN_REQ=True).hold(3, DISCHARGE=10.0).hold(3, DISCHARGE=10.125).hold(3, DISCHARGE=5.0)
    s.pulse(RESET=True, after=2).hold(5, RUN_REQ=False)
    s.hold(20).pulse(3, DISCHARGE=11.0, after=0).pulse(RESET=True, DISCHARGE=11.0, after=2).pulse(RESET=True, after=2)
    s.hold(30)
    # Reach the start limit: the running pump is not stopped, the next start is refused.
    s.pulse(RESET_STARTS=True, after=2).hold(1, MAX_STARTS=2)
    run(5, 30)
    run(5, 30)
    run(5, 30)
    s.pulse(RESET_STARTS=True, after=2).hold(1, MAX_STARTS=8)
    run(10, 30)
    s.random_phase(
        900,
        toggle={"RUN_REQ": 0.03, "RESET": 0.03, "RESET_STARTS": 0.01},
        walk={"SUCTION": (0.0, 3.0, 0.25), "DISCHARGE": (6.0, 11.0, 0.5)},
        choose={"MAX_STARTS": (0.005, [3, 5, 8])},
    )


def pump_rotation(s: Stimulus) -> None:
    s.hold(3)
    s.hold(20, REQUIRED=1).hold(10, REQUIRED=2).hold(10, REQUIRED=3).hold(5, REQUIRED=4).hold(5, REQUIRED=0)
    s.hold(10, REQUIRED=1)
    # Availability changes on each pump, including losing a running one.
    for avail in ("AVAIL_1", "AVAIL_2", "AVAIL_3"):
        s.pulse(8, after=8, **{avail: False})
    s.hold(5, REQUIRED=2, AVAIL_1=False).hold(5, AVAIL_2=False).hold(5, AVAIL_3=False).hold(5, AVAIL_1=True)
    s.hold(5, AVAIL_2=True, AVAIL_3=True, REQUIRED=1)
    # Rotation timer, long enough to fire several times, so the running pump changes.
    s.hold(120, REQUIRED=1).hold(120, REQUIRED=2)
    s.pulse(3, RESET_HOURS=True, after=30)
    s.hold(1, ROTATE_TIME=50, REQUIRED=1).hold(40).hold(1, ROTATE_TIME=200)
    s.random_phase(
        800,
        toggle={"AVAIL_1": 0.01, "AVAIL_2": 0.01, "AVAIL_3": 0.01, "RESET_HOURS": 0.003},
        choose={"REQUIRED": (0.02, [0, 1, 1, 2, 2, 3])},
    )


def auto_restart(s: Stimulus) -> None:
    def fault(retry_scans: int) -> None:
        s.pulse(2, DRIVE_FAULT=True, after=retry_scans)

    s.hold(3).hold(5, RUN_REQ=True)
    fault(12)  # waits out the retry delay and restarts
    s.hold(40)  # stable for long enough to refill the budget
    fault(12)
    fault(12)
    fault(12)  # the budget of 3 is used up on this one
    s.hold(5).pulse(OPERATOR_RESET=True, after=12)
    fault(3)  # a fault during the wait
    fault(12)
    s.hold(5, RUN_REQ=False).hold(12, RUN_REQ=True)
    s.pulse(2, DRIVE_FAULT=True, after=0).hold(3, RUN_REQ=False).hold(15, RUN_REQ=True)
    # Stable time boundary: 29 and 30 scans, with a 300 ms stable time.
    fault(10)
    s.hold(29)
    fault(10)
    s.hold(30)
    fault(10)
    s.hold(1, RETRY_BUDGET=1).pulse(OPERATOR_RESET=True, after=3)
    fault(12)
    fault(12)
    s.pulse(OPERATOR_RESET=True, DRIVE_FAULT=True, after=12).hold(1, RETRY_BUDGET=3)
    s.pulse(OPERATOR_RESET=True, after=12)
    s.random_phase(
        800,
        toggle={"RUN_REQ": 0.01, "DRIVE_FAULT": 0.04, "OPERATOR_RESET": 0.01},
        choose={"RETRY_DELAY": (0.01, [50, 100, 150]), "STABLE_TIME": (0.01, [200, 300])},
    )


def pump_supervisor(s: Stimulus) -> None:
    filtered = 0.0

    def walk(target: float, then: int = 1) -> None:
        # The filter moves by a quarter of (raw - filtered) in one pass. With raw exactly 1 away
        # it moves exactly 0.25, so a walk lands exactly on a threshold, and raw == filtered then
        # holds it there. This is what lets the stimulus sit on the REAL boundaries of the ECC.
        nonlocal filtered
        while filtered != target:
            direction = 1.0 if target > filtered else -1.0
            s.hold(1, RAW_LEVEL=filtered + direction)
            filtered += 0.25 * direction
        s.hold(then, RAW_LEVEL=filtered)

    def pump_down() -> None:
        # Filling, proof, running, lag, then pump-down, following the filtered level.
        s.ramp("RAW_LEVEL", 3.5, 12).hold(14, RAW_LEVEL=3.5)
        s.hold(5, FB_1=True, FB_2=True).ramp("RAW_LEVEL", 4.5, 6).hold(25, RAW_LEVEL=4.5)
        s.hold(15, RAW_LEVEL=3.5).hold(25, RAW_LEVEL=1.0).hold(3, FB_1=False, FB_2=False).hold(15)

    # Directed walk with an exact filtered level: every threshold is met with equality.
    walk(3.0, then=30)  # no proof of running: lead fails, lag fails, station fault
    s.pulse(ACK=True, after=3)
    s.hold(1, FB_1=True, FB_2=True)
    walk(3.0, then=5)  # restarts and proves at once
    walk(4.0, then=5)  # lag joins exactly at LAG_LEVEL
    walk(3.75, then=5)  # and leaves just below it
    walk(5.0, then=25)  # high alarm exactly at HIGH_LEVEL, long enough to raise it
    walk(4.75, then=3)
    walk(1.5, then=3)  # just above the stop level
    walk(1.25, then=3)  # exactly on it, so the pump stops and the lead rotates
    walk(2.75, then=3)
    s.hold(1, FB_1=False, FB_2=False)
    # From here the filtered level is no longer exact.
    pump_down()
    pump_down()
    # No proof: each pump fails in turn and the station faults, then is acknowledged.
    s.hold(40, RAW_LEVEL=3.5).pulse(ACK=True, after=20)
    s.hold(30, RAW_LEVEL=1.0).pulse(ACK=True, after=3)
    # Proof arrives just in time, one scan before the limit, then one scan too late.
    s.hold(1, FB_1=False, FB_2=False).hold(9, RAW_LEVEL=3.5).hold(15, FB_1=True, FB_2=True).hold(25, RAW_LEVEL=1.0)
    s.hold(5, FB_1=False, FB_2=False).pulse(ACK=True, after=3)
    # A trip of the lead while running, of the lag while both run, and of both.
    s.hold(15, RAW_LEVEL=3.5, FB_1=True, FB_2=True).pulse(TRIP_1=True, after=10).pulse(ACK=True, after=5)
    s.hold(20, RAW_LEVEL=4.5).pulse(TRIP_2=True, after=8).pulse(ACK=True, after=8)
    s.pulse(TRIP_1=True, after=5).pulse(TRIP_2=True, after=10).pulse(ACK=True, TRIP_1=True, after=5).pulse(ACK=True, after=5)
    # Both pumps running, trip each in turn, so that the lead is tripped in state 4 whichever it is.
    s.hold(20, RAW_LEVEL=4.5).pulse(TRIP_1=True, after=6).pulse(ACK=True, after=10)
    s.hold(5, RAW_LEVEL=4.5).pulse(TRIP_2=True, after=6).pulse(ACK=True, after=10)
    # Only the lag proves running, for either lead: the feedback must come from the lead pump.
    for _ in range(2):
        s.hold(25, RAW_LEVEL=1.0, FB_1=True, FB_2=True).hold(3, FB_1=False, FB_2=False)
        s.hold(1, FB_1=True).hold(14, RAW_LEVEL=3.5).hold(3, FB_1=False, FB_2=True).hold(14).pulse(ACK=True, after=3)
    s.hold(1, FB_1=True, FB_2=True).hold(25, RAW_LEVEL=1.0).hold(3, FB_1=False, FB_2=False)
    # High level alarm: below the limit, then long enough, and a dip that resets the delay.
    s.hold(40, RAW_LEVEL=4.875).hold(40, RAW_LEVEL=5.5).hold(30, RAW_LEVEL=4.0)
    s.hold(12, RAW_LEVEL=6.0).hold(10, RAW_LEVEL=4.0).hold(30, RAW_LEVEL=6.0)
    s.hold(30, RAW_LEVEL=1.0).hold(5, FB_1=False, FB_2=False)
    # Leave auto in each state.
    s.pulse(5, AUTO_MODE=False, after=5).hold(15, RAW_LEVEL=3.5)
    s.pulse(5, AUTO_MODE=False, after=8).hold(5, FB_1=True, FB_2=True)
    s.pulse(5, AUTO_MODE=False, after=8).hold(30, RAW_LEVEL=4.5).pulse(5, AUTO_MODE=False, after=8)
    s.hold(30, RAW_LEVEL=1.0).hold(1, PULSE_SIZE=0.125, FLOW=64.0)
    s.hold(20, RAW_LEVEL=3.5).hold(1, PULSE_SIZE=2.0, FLOW=32.0)
    s.random_phase(
        800,
        toggle={"AUTO_MODE": 0.003, "ACK": 0.04, "FB_1": 0.02, "FB_2": 0.02, "TRIP_1": 0.002, "TRIP_2": 0.002},
        walk={"RAW_LEVEL": (0.5, 6.5, 0.375), "FLOW": (0.0, 200.0, 20.0)},
    )


SCENARIOS: dict[str, tuple[Callable[[Stimulus], None], int, dict[str, Any]]] = {
    "01_motor_start_stop": (motor_start_stop, 10, dict(START_PB=False, STOP_PB=False, OVERLOAD=False, RESET_PB=False)),
    "02_tank_hysteresis": (tank_hysteresis, 100, dict(LEVEL=50.0, START_LEVEL=20.0, STOP_LEVEL=80.0, ALARM_MARGIN=5.0, ENABLE=True)),
    "03_scaling_clamp": (scaling_clamp, 10, dict(RAW=0.0, RAW_MIN=4.0, RAW_MAX=20.0, ENG_MIN=0.0, ENG_MAX=100.0)),
    "04_parts_counter": (parts_counter, 10, dict(SENSOR=False, RESET=False, BATCH_SIZE=5)),
    "05_alarm_debounce_ack": (alarm_debounce, 10, dict(PROCESS_TRIP=False, ACK=False, ON_DELAY=40, OFF_DELAY=60)),
    "06_star_delta": (star_delta, 10, dict(START_PB=False, STOP_PB=False, OVERLOAD=False, STAR_TIME=300)),
    "07_conveyor_interlock": (conveyor_interlock, 10, dict(START_PB=False, STOP_PB=False, ESTOP_OK=True, JAM_C1=False, JAM_C2=False, JAM_C3=False, STAGGER=100)),
    "08_first_out_alarm": (first_out, 10, dict(TRIP_1=False, TRIP_2=False, TRIP_3=False, TRIP_4=False, RESET=False)),
    "09_totalizer": (totalizer, 100, dict(DP=0.0, K_FACTOR=10.0, LOW_CUT=1.0, SCAN_HOURS=0.0078125, PULSE_SIZE=1.0, RESET=False)),
    "10_valve_feedback": (valve_feedback, 10, dict(OPEN_CMD=False, OPENED_LS=False, CLOSED_LS=False, RESET=False, TRAVEL_LIMIT=200)),
    "11_ramp_generator": (ramp_generator, 50, dict(SETPOINT=0.0, RATE_UP=1.0, RATE_DOWN=2.0, HOLD=False, RESET=False, PRESET=2.5)),
    "12_pid_loop": (pid_loop, 100, dict(SP=50.0, PV=50.0, KP=2.0, KI=0.25, KD=0.5, DEADBAND=1.0, OUT_MIN=0.0, OUT_MAX=100.0, AUTO_MODE=True, MANUAL_OUT=0.0)),
    "13_case_sequencer": (case_sequencer, 10, dict(START_PB=False, ABORT=False, HOLD=False, LEVEL_HIGH=False, LEVEL_LOW=False, STEP_TIME=80)),
    "14_batch_filling": (batch_filling, 10, dict(START_PB=False, ABORT=False, WEIGHT=0.0, TARGET=100.0, SLOW_BAND=10.0, TOLERANCE=2.0, SETTLE_TIME=80, RESET_COUNT=False)),
    "15_duty_standby": (duty_standby, 10, dict(DEMAND=False, FB_A=False, FB_B=False, TRIP_A=False, TRIP_B=False, RESET=False, PROOF_TIME=100)),
    "16_pump_station_level": (pump_level, 100, dict(LEVEL=1.5, STOP_LEVEL=1.0, START_LEVEL=3.0, LAG_LEVEL=4.0, HIGH_LEVEL=5.0, DRY_LEVEL=0.5, AUTO_MODE=True, LAG_DELAY=1000, ALARM_DELAY=2000)),
    "17_pump_station_protection": (pump_protection, 10, dict(RUN_REQ=False, SUCTION=2.0, DISCHARGE=5.0, SUCTION_MIN=1.0, DISCHARGE_MAX=10.0, RESET=False, MAX_STARTS=8, RESET_STARTS=False, LOW_DELAY=100, PRIME_TIME=100, COOL_TIME=200)),
    "18_pump_station_rotation": (pump_rotation, 10, dict(REQUIRED=0, AVAIL_1=True, AVAIL_2=True, AVAIL_3=True, RESET_HOURS=False, ROTATE_TIME=500)),
    "19_auto_restart": (auto_restart, 10, dict(RUN_REQ=False, DRIVE_FAULT=False, OPERATOR_RESET=False, RETRY_BUDGET=3, RETRY_DELAY=100, STABLE_TIME=300)),
    "20_pump_station_supervisor": (pump_supervisor, 100, dict(AUTO_MODE=True, ACK=False, RAW_LEVEL=1.0, STOP_LEVEL=1.25, START_LEVEL=3.0, LAG_LEVEL=4.0, HIGH_LEVEL=5.0, FB_1=False, FB_2=False, TRIP_1=False, TRIP_2=False, FLOW=120.0, SCAN_HOURS=0.0078125, PULSE_SIZE=1.0, PROOF_TIME=1000, ALARM_DELAY=2000)),
}


def write_stimulus(name: str, stimulus: Stimulus) -> None:
    rows = ",\n".join("  " + json.dumps(scan) for scan in stimulus.scans)
    text = f'{{"scan_ms": {stimulus.scan_ms}, "scans": [\n{rows}\n]}}\n'
    (CORPUS / name / "stimulus.json").write_text(text)


def main() -> None:
    for name, (scenario, scan_ms, defaults) in SCENARIOS.items():
        stimulus = Stimulus(name, scan_ms, **defaults)
        scenario(stimulus)
        write_stimulus(name, stimulus)
        print(f"{name}: {len(stimulus.scans)} scans at {scan_ms} ms")


if __name__ == "__main__":
    main()
