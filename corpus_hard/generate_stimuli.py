#!/usr/bin/env python3
"""Regenerate the stimuli of corpus_hard/. Same seeds, same files.

    python3 corpus_hard/generate_stimuli.py

For each program this writes four files, from one directed scenario:

    stimulus.json             Tuning. Repair feedback may use it. Seed 61499, the same base as corpus/.
    heldout_stimulus.json     Scored after the migration and never shown to a model. Seed 104729, the tuning scan period, jittered
                              holds, a closing random phase and a retune phase, as corpus/generate_heldout.py builds them, plus a
                              different start and directed phases at parameter values tuning never holds.
    heldout_stimulus_2.json   Scored too, also never shown, and a run must pass both. Seed 104759, another scan period, with holds
                              stretched to the same time, and with parameters pinned to values no other stimulus holds.
    pairing_stimulus.json     Used only to check an oracle pairing in scripts/check_pairing.py. Seed 15485863.

A held-out file adds testing power only if it can fail where tuning passes. So each one starts differently from scan 0, tuning never
holds a parameter value that exists to test generalisation, and `scripts/audit_stimuli.py` lists any numeric input that stays constant.

The classes come from corpus/generate_stimuli.py and corpus/generate_heldout.py, so the two corpora are built the same way.
Each scenario was written from the program's behaviour, and each stimulus was then checked with mutation testing.
REAL inputs are multiples of 1/16, so they are exact in binary. A test pins that.
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "corpus"))

from generate_heldout import CLOSING_SCANS, HeldoutStimulus, render  # noqa: E402
from generate_stimuli import Stimulus  # noqa: E402

HELDOUT_SEED, HELDOUT_2_SEED, PAIRING_SEED = 104729, 104759, 15485863
TUNING_FILE, HELDOUT_FILE, HELDOUT_2_FILE, PAIRING_FILE = "stimulus.json", "heldout_stimulus.json", "heldout_stimulus_2.json", "pairing_stimulus.json"
# The scan period of the second held-out file, for each tuning period. 7 is on no grid of 10, so a preset multiple of 10 no longer lands on a scan.
SECOND_PERIOD = {10: 7, 100: 70}


class ScoredStimulus(HeldoutStimulus):
    """The held-out recipe under a chosen seed. `pinned` inputs keep one value throughout, whatever the scenario asks for.
    `stretch` scales multi-scan holds, so that a scenario written for one scan period spans the same time at another."""

    def __init__(self, name: str, scan_ms: int = 10, seed: int = HELDOUT_SEED, stretch: float = 1.0, pinned: dict[str, Any] | None = None, **defaults: Any) -> None:
        self.pinned = dict(pinned or {})
        self.stretch = stretch
        super().__init__(name, scan_ms, **{**defaults, **self.pinned})
        self.rng = random.Random(f"{seed}:{name}")
        self.jitter = random.Random(f"{seed}:jitter:{name}")

    def hold(self, scans: int = 1, **changes: Any) -> "ScoredStimulus":
        if scans >= 2:
            scans = math.ceil(scans * self.stretch)
        super().hold(scans, **{**changes, **self.pinned})
        return self


# ---- unsupported_st ----


def sensor_voting(s: Stimulus) -> None:
    s.hold(3)
    s.hold(3, ENABLE=True)
    # The middle value of each ordering of the three.
    for a, b, c in ((10.0, 20.0, 30.0), (30.0, 10.0, 20.0), (20.0, 30.0, 10.0), (10.0, 30.0, 20.0), (30.0, 20.0, 10.0), (20.0, 10.0, 30.0)):
        s.hold(2, PT_A=a, PT_B=b, PT_C=c)
    s.hold(2, PT_A=50.0, PT_B=50.0, PT_C=50.0)
    # Exactly on the band edge, and just past it, for each channel.
    s.hold(2, PT_A=52.0).hold(2, PT_A=52.125).hold(2, PT_A=50.0)
    s.hold(2, PT_B=48.0).hold(2, PT_B=47.875).hold(2, PT_B=50.0)
    s.hold(2, PT_C=52.0).hold(2, PT_C=52.125).hold(2, PT_C=50.0)
    # A disagreement long enough for the delay, then short of it.
    s.hold(12, PT_A=70.0).hold(4, PT_A=50.0).hold(5, PT_A=70.0).hold(4, PT_A=50.0)
    # Two channels out: the median still moves, and the trip is blocked while two disagree.
    s.hold(3, PT_A=95.0, PT_B=90.0, PT_C=50.0).hold(3, PT_C=88.0).hold(3, PT_A=50.0, PT_B=50.0, PT_C=50.0)
    s.pulse(RESET=True, after=3)
    s.hold(3, PT_A=80.0, PT_B=80.0, PT_C=80.0)  # Exactly on HIGH_LIMIT, which must not trip.
    s.hold(3, PT_A=80.125, PT_B=80.125, PT_C=80.125).hold(3, PT_A=50.0, PT_B=50.0, PT_C=50.0)
    s.pulse(RESET=True, after=3)
    s.hold(3, PT_A=90.0, PT_B=90.0, PT_C=90.0).hold(2, RESET=True).hold(2, RESET=False).hold(2, PT_A=50.0, PT_B=50.0, PT_C=50.0)
    s.pulse(RESET=True, after=2)
    # Rounding of PERCENT on exact halves, with SPAN 200: 0.5, 1.5, 2.5 and 3.5 percent.
    for value in (1.0, 3.0, 5.0, 7.0):
        s.hold(2, PT_A=value, PT_B=value, PT_C=value)
    # RETURN holds the outputs, and resets the timer while disabled.
    s.hold(8, PT_A=70.0, PT_B=50.0, PT_C=50.0).hold(4, ENABLE=False, PT_A=99.0, PT_B=99.0, PT_C=99.0).hold(4, ENABLE=True, PT_A=70.0, PT_B=50.0, PT_C=50.0)
    s.hold(12)
    s.hold(3, ENABLE=False, HIGH_LIMIT=10.0, RESET=True).hold(2, RESET=False).hold(3, ENABLE=True, PT_A=50.0)
    s.pulse(3, RESET=True, after=2).hold(3, HIGH_LIMIT=80.0)
    s.random_phase(250, toggle={"ENABLE": 0.03, "RESET": 0.06}, walk={"PT_A": (0.0, 100.0, 9.0), "PT_B": (0.0, 100.0, 9.0), "PT_C": (0.0, 100.0, 9.0)})


def valve_manifold(s: Stimulus) -> None:
    s.hold(3)
    # A clean opening, one valve at a time, then closing.
    s.hold(3, RUN_REQ=True).hold(2, AT_CLOSED_1=False).hold(3, AT_OPEN_1=True)
    s.hold(2, AT_CLOSED_2=False).hold(3, AT_OPEN_2=True).hold(2, AT_CLOSED_3=False).hold(4, AT_OPEN_3=True)
    s.hold(2, RUN_REQ=False).hold(2, AT_OPEN_1=False, AT_OPEN_2=False, AT_OPEN_3=False)
    s.hold(3, AT_CLOSED_1=True, AT_CLOSED_2=True, AT_CLOSED_3=True)
    # Valve 1 never arrives, and the reset is refused until the cause goes away.
    s.hold(10, RUN_REQ=True, AT_CLOSED_1=False).pulse(RESET=True, after=3)
    s.hold(2, RUN_REQ=False).hold(9, RESET=False).pulse(RESET=True, after=2).hold(3, AT_CLOSED_1=True)
    s.pulse(RESET=True, after=3)
    # Valve 2 is the one that fails.
    s.hold(2, RUN_REQ=True, AT_CLOSED_1=False, AT_OPEN_1=True).hold(10, AT_CLOSED_2=False)
    s.pulse(RESET=True, after=3).hold(3, AT_OPEN_2=True).hold(9, AT_CLOSED_3=False).hold(3, AT_OPEN_3=True)
    s.pulse(RESET=True, after=3)
    # Both end switches on, which means nothing has opened, and a closing valve that never reaches closed.
    s.hold(3, AT_CLOSED_1=True).hold(2, AT_CLOSED_1=False)
    s.hold(2, RUN_REQ=False).hold(10, AT_OPEN_1=False, AT_CLOSED_1=False, AT_OPEN_2=False, AT_CLOSED_2=True, AT_OPEN_3=True, AT_CLOSED_3=False)
    s.pulse(RESET=True, after=2).hold(3, AT_CLOSED_1=True, AT_OPEN_3=False, AT_CLOSED_3=True).pulse(RESET=True, after=2)
    s.hold(1, TRAVEL=30)
    s.random_phase(300, toggle={"RUN_REQ": 0.05, "RESET": 0.05, "AT_OPEN_1": 0.12, "AT_OPEN_2": 0.12, "AT_OPEN_3": 0.12, "AT_CLOSED_1": 0.12, "AT_CLOSED_2": 0.12, "AT_CLOSED_3": 0.12})


def tank_strapping(s: Stimulus) -> None:
    s.hold(2, DENSITY=1.0)
    # Every table entry, just below it and just above it.
    for level in (0.0, 200.0, 400.0, 800.0, 1200.0, 2000.0):
        s.sweep("LEVEL_MM", level - 0.125, level, level + 0.125, dwell=1)
    s.sweep("LEVEL_MM", -50.0, 2100.0, 100.0, 300.0, 600.0, 1000.0, 1600.0, dwell=2)
    # HOLD keeps every output, however the level moves.
    s.hold(3, HOLD=True, LEVEL_MM=2500.0).hold(3, LEVEL_MM=10.0).hold(2, HOLD=False)
    s.hold(2, DENSITY=0.75).sweep("LEVEL_MM", 1.0, 3.0, 5.0, 7.0, 500.0, dwell=1)
    # MASS_KG rounds half to even, so 1.5 kg and 2.5 kg give 2 and 2. Segment 0 is 0.75 L per mm.
    s.hold(2, DENSITY=1.0)
    s.sweep("LEVEL_MM", 2.0, 4.0, 6.0, dwell=1)
    s.ramp("LEVEL_MM", 2000.0, 80).ramp("LEVEL_MM", 0.0, 80)
    s.random_phase(200, toggle={"HOLD": 0.05}, walk={"LEVEL_MM": (-100.0, 2200.0, 180.0), "DENSITY": (0.5, 1.5, 0.125)})


def alarm_ring(s: Stimulus) -> None:
    s.hold(3)
    # Fill the ring and overwrite: repeated codes count once, zero never counts.
    for code in (11, 11, 0, 12, 13, 0, 14):
        s.hold(2, RAISE_CODE=code)
    s.hold(2, RAISE_CODE=0).pulse(ACK_OLDEST=True, after=2).pulse(ACK_OLDEST=True, after=2)
    for code in (15, 0, 16, 0, 17, 0):
        s.hold(2, RAISE_CODE=code)
    s.pulse(3, ACK_OLDEST=True, after=2)
    for _ in range(5):
        s.pulse(ACK_OLDEST=True, after=1)
    s.hold(2, RAISE_CODE=21).hold(2, RAISE_CODE=0).pulse(CLEAR_ALL=True, after=2)
    # A code raised on the same scan as a clear is lost, and is not seen again while held.
    s.hold(2, CLEAR_ALL=True, RAISE_CODE=31).hold(3, CLEAR_ALL=False).hold(2, RAISE_CODE=0)
    s.hold(1, RAISE_CODE=32, ACK_OLDEST=True).hold(2, ACK_OLDEST=False).hold(2, RAISE_CODE=33).hold(8)
    s.random_phase(350, toggle={"ACK_OLDEST": 0.2, "CLEAR_ALL": 0.012}, choose={"RAISE_CODE": (0.25, [0, 0, 0, 41, 42, 43, 44, 45])})


def pump_duty_records(s: Stimulus) -> None:
    s.hold(2)
    # The weight of a start in the wear score: pump 1 has two starts and no ticks, pump 2 has one start and 7 ticks. Pump 1 wins by 2, which is a matter of what one start weighs.
    s.hold(2, AVAIL_1=True, DEMAND=1).hold(1, DEMAND=0).hold(2, DEMAND=1).hold(1, DEMAND=0)
    s.hold(1, AVAIL_1=False, AVAIL_2=True, DEMAND=1).pulse(RESET_TICKS=True, after=7).hold(1, DEMAND=0).hold(3, AVAIL_1=True, DEMAND=1).hold(2, DEMAND=0, AVAIL_1=False, AVAIL_2=False)
    s.hold(4, AVAIL_1=True, AVAIL_2=True, AVAIL_3=True).hold(6, DEMAND=1).hold(5, DEMAND=2).hold(5, DEMAND=3)
    s.hold(3, DEMAND=4).hold(3, DEMAND=0)  # More demand than pumps, then none.
    # Least wear wins, so the pump that ran least starts first.
    s.hold(8, DEMAND=1).hold(2, DEMAND=0).hold(8, DEMAND=1).hold(2, DEMAND=0).hold(8, DEMAND=1).hold(2, DEMAND=0).hold(8, DEMAND=2)
    # Losing a running pump, a stopped pump, and all of them.
    s.hold(3, AVAIL_1=False).hold(3, AVAIL_1=True).hold(3, AVAIL_2=False).hold(3, AVAIL_3=False).hold(3, AVAIL_1=False)
    s.hold(3, AVAIL_1=True, AVAIL_2=True, AVAIL_3=True).pulse(RESET_TICKS=True, after=4)
    # A pump kept over a reselection does not count as a new start.
    s.hold(5, DEMAND=2).hold(5, DEMAND=1).hold(5, DEMAND=2).hold(5, DEMAND=3).hold(5, DEMAND=1)
    s.hold(3, DEMAND=0).pulse(RESET_TICKS=True, after=1).hold(4, DEMAND=3)
    s.random_phase(600, toggle={"AVAIL_1": 0.03, "AVAIL_2": 0.03, "AVAIL_3": 0.03, "RESET_TICKS": 0.03}, choose={"DEMAND": (0.2, [0, 1, 2, 3, 4])})


def cascade_nested(s: Stimulus) -> None:
    s.hold(2, TEMP_SP=40.0, TEMP_PV=20.0, FLOW_PV=10.0)
    s.hold(8, ENABLE=True).hold(10, MASTER_AUTO=True)
    # Saturate both loops high, then low, and leave saturation.
    s.hold(10, TEMP_SP=200.0, TEMP_PV=0.0, FLOW_PV=0.0).hold(10, TEMP_SP=0.0, TEMP_PV=200.0, FLOW_PV=120.0)
    s.hold(10, TEMP_SP=40.0, TEMP_PV=39.0, FLOW_PV=5.0)
    # A disable keeps each setpoint ramp where it was, since RETURN leaves before it runs.
    s.hold(5, ENABLE=False, TEMP_SP=90.0).hold(5, ENABLE=True).hold(4, MASTER_AUTO=False, MANUAL_FLOW_SP=20.0)
    s.hold(5, MASTER_AUTO=True).hold(3, MASTER_AUTO=False).hold(3, MANUAL_FLOW_SP=60.0, FLOW_PV=58.0)
    # Exactly no error, and a step that lands inside one ramp step.
    s.hold(3, MANUAL_FLOW_SP=58.0).hold(2, MANUAL_FLOW_SP=64.0).hold(2, MANUAL_FLOW_SP=65.0).hold(2, MANUAL_FLOW_SP=50.0)
    # The demand exactly on zero, with no error and no integral, and exactly on the slave's limit, where a saturated flag is the only difference. With an error of 16
    # its demand is 24 and rises by 4 a scan, so it lands exactly on 100.
    s.hold(10, ENABLE=True, MASTER_AUTO=False, MANUAL_FLOW_SP=50.0, FLOW_PV=50.0).hold(2, ENABLE=False).hold(3, ENABLE=True).hold(2, ENABLE=False).hold(24, ENABLE=True, FLOW_PV=34.0)
    s.hold(1, MASTER_AUTO=True, TEMP_SP=40.0, TEMP_PV=39.0)
    s.ramp("TEMP_PV", 80.0, 30)
    s.random_phase(300, toggle={"ENABLE": 0.02, "MASTER_AUTO": 0.03}, walk={"TEMP_SP": (0.0, 120.0, 5.0), "TEMP_PV": (0.0, 120.0, 4.0), "FLOW_PV": (0.0, 100.0, 6.0), "MANUAL_FLOW_SP": (0.0, 100.0, 7.0)})


# ---- siemens_scl ----


def conveyor_starter(s: Stimulus) -> None:
    s.hold(3)
    s.pulse(i_start=True, after=8).hold(5)  # Horn, then run.
    s.pulse(i_stop=True, after=3).hold(10)  # Coast-down runs out.
    s.pulse(i_start=True, after=2).pulse(i_stop=True, after=2)  # A stop during the horn.
    s.hold(2, i_start=True).hold(2, i_stop=True).hold(2, i_start=False).hold(2, i_stop=False)  # A held start does not restart.
    s.pulse(i_start=True, after=8).pulse(i_overload=True, after=2).pulse(i_start=True, after=2)
    s.pulse(i_reset=True, after=2).pulse(i_start=True, after=8)
    s.hold(2, i_overload=True, i_reset=True).hold(2, i_overload=False, i_reset=False).pulse(i_reset=True, after=2)
    s.pulse(i_start=True, after=8).hold(3, i_estopOk=False).hold(2, i_estopOk=True).pulse(i_start=True, after=2).pulse(i_reset=True, after=2)
    s.pulse(i_start=True, after=10).pulse(i_stop=True, after=3).pulse(i_start=True, after=10)  # Restart while still coasting.
    s.pulse(i_stop=True, after=8)
    s.hold(1, i_hornTime=70, i_coastTime=30).pulse(i_start=True, after=12).pulse(i_stop=True, after=6)
    # A horn keeps the length it started with, and a coast-down the time in force when the run dropped, whatever the inputs do meanwhile.
    s.pulse(i_start=True, after=2).hold(4, i_hornTime=30).hold(6, i_hornTime=70).pulse(i_stop=True, after=1).hold(1, i_coastTime=50).hold(6).hold(1, i_coastTime=30)
    s.random_phase(350, toggle={"i_start": 0.1, "i_stop": 0.04, "i_estopOk": 0.015, "i_overload": 0.015, "i_reset": 0.08}, choose={"i_hornTime": (0.01, [30, 50, 70]), "i_coastTime": (0.01, [30, 50])})


def analog_input(s: Stimulus) -> None:
    s.hold(3)
    for raw in (0, 13824, 27648, 6912, 20736):
        s.hold(2, i_raw=raw)
    s.hold(2, i_raw=30000).hold(2, i_raw=-100).hold(2, i_raw=13824)
    # Limit alarms: on the limit, just past it, too short, and long enough.
    s.hold(1, i_highLimit=100.0, i_lowLimit=20.0, i_alarmDelay=30, i_scaleMin=0.0, i_scaleMax=200.0)
    s.hold(5, i_raw=13824).hold(6, i_raw=13825).hold(2, i_raw=13824).hold(2, i_raw=13825).hold(2, i_raw=13824)
    s.hold(6, i_raw=2765).hold(6, i_raw=2764).hold(2, i_raw=13824)
    # Exactly on each limit, through the simulated value.
    s.hold(6, i_simulate=True, i_simValue=20.0).hold(6, i_simValue=100.0).hold(2, i_simulate=False)
    s.hold(2, i_raw=-1000).hold(2, i_raw=13824)
    # Wire break holds the last good value, and raises its own alarm after the delay.
    s.hold(2, i_raw=32767).hold(2, i_raw=13824).hold(6, i_raw=32767).hold(3, i_raw=13824)
    # Simulation overrides the value, and the percent still follows the channel.
    s.hold(3, i_simulate=True, i_simValue=150.0, i_raw=27648).hold(6).hold(5, i_simValue=5.0).hold(4, i_simulate=False)
    s.hold(1, i_scaleMin=-50.0, i_scaleMax=150.0).hold(2, i_raw=0).hold(2, i_raw=27648)
    # Half of a percent: 138 of 27648 is 0.499, and 139 of 27648 is 0.503.
    s.sweep("i_raw", 138, 139, 415, 691, 692, dwell=1)
    s.random_phase(260, toggle={"i_simulate": 0.02}, choose={"i_raw": (0.3, [0, 1000, 5000, 13824, 20000, 27648, 30000, 32767, 13000, 14000]), "i_simValue": (0.04, [5.0, 150.0, 110.0, 10.0])})


def valve_monitor(s: Stimulus) -> None:
    s.hold(3)
    s.hold(3, i_openCmd=True, i_atClosed=False).hold(3, i_atOpen=True).hold(3, i_openCmd=False, i_atOpen=False).hold(3, i_atClosed=True)
    # Opening runs out of time. Travel 30 and margin 20 is five scans.
    s.hold(9, i_openCmd=True, i_atClosed=False).pulse(i_ack=True, after=2).hold(2, i_openCmd=False)
    s.pulse(i_ack=True, after=3)
    s.hold(9, i_atClosed=False).pulse(i_ack=True, after=2).hold(2, i_atClosed=True).pulse(i_ack=True, after=3)
    # Both limit switches on is a fault at once.
    s.hold(3, i_atOpen=True).hold(2, i_atOpen=False).pulse(i_ack=True, after=3)
    # Exactly on the budget: one scan short, and the scan on which it expires.
    s.hold(5, i_openCmd=True, i_atClosed=False).hold(3, i_atOpen=True).hold(2, i_openCmd=False, i_atOpen=False).hold(2, i_atClosed=True)
    # Maintenance freezes everything, including a timer's elapsed output and a fault in progress.
    s.hold(2, i_openCmd=True, i_atClosed=False).hold(4, i_maintenance=True, i_atOpen=True, i_atClosed=True, i_ack=True).hold(3, i_maintenance=False, i_atOpen=False, i_atClosed=False, i_ack=False)
    s.hold(6).pulse(i_ack=True, after=2)
    s.hold(1, i_travelTime=50, i_margin=30).hold(10).hold(2, i_openCmd=False)
    s.pulse(i_ack=True, after=2).hold(3, i_atClosed=True)
    s.random_phase(350, toggle={"i_openCmd": 0.07, "i_atOpen": 0.1, "i_atClosed": 0.1, "i_ack": 0.09, "i_maintenance": 0.02}, choose={"i_margin": (0.01, [10, 20, 30]), "i_travelTime": (0.01, [20, 30, 50])})


def batch_steps(s: Stimulus) -> None:
    s.hold(3)
    def cycle() -> None:
        s.pulse(i_start=True, after=2).hold(3).hold(2, i_doseDone=True).hold(1, i_doseDone=False)
        s.hold(8).hold(3).hold(2, i_tempReached=True).hold(3, i_tempReached=False).hold(9)
        s.hold(3).hold(3, i_tankEmpty=True).hold(2, i_tankEmpty=False)
    cycle()
    cycle()
    # Abort from each step, in turn, and an abort held with the tank empty.
    s.pulse(i_start=True, after=2).pulse(i_abort=True, after=2).hold(2, i_tankEmpty=True).hold(2, i_tankEmpty=False)
    s.pulse(i_start=True, after=1).hold(1, i_doseDone=True).hold(1, i_doseDone=False).hold(2).pulse(i_abort=True, after=2).hold(2, i_tankEmpty=True).hold(2, i_tankEmpty=False)
    s.pulse(i_start=True, after=1).hold(1, i_doseDone=True).hold(1, i_doseDone=False).hold(8).hold(1, i_tempReached=True).hold(1, i_tempReached=False).hold(2)
    s.hold(2, i_abort=True, i_tankEmpty=True).hold(2, i_abort=False).hold(2, i_tankEmpty=False)
    # A start while aborting does nothing, and abort while idle does not leave idle.
    s.hold(2, i_abort=True).hold(2, i_start=True).hold(2, i_abort=False, i_start=False)
    # Different times, so the shared timer's preset matters.
    s.hold(1, i_mixTime=80, i_holdTime=30)
    cycle()
    s.hold(1, i_mixTime=30, i_holdTime=80)
    s.pulse(i_start=True, after=2).hold(1, i_doseDone=True).hold(1, i_doseDone=False).hold(6).hold(2, i_tempReached=True).hold(12, i_tempReached=False).hold(2, i_tankEmpty=True).hold(2, i_tankEmpty=False)
    s.random_phase(500, toggle={"i_start": 0.12, "i_abort": 0.012, "i_doseDone": 0.12, "i_tempReached": 0.1, "i_tankEmpty": 0.12})


def lead_lag_array(s: Stimulus) -> None:
    s.hold(2)
    s.hold(2, i_avail2=True).hold(2, i_avail1=True, i_avail3=True)
    for _ in range(4):
        s.pulse(i_rotate=True, after=2)
    s.hold(2, i_lagDemand=True)
    for _ in range(4):
        s.pulse(i_rotate=True, after=2)
    # Each pump lost in turn, as lead and as lag, and rotation with one pump left.
    s.hold(2, i_avail1=False).hold(2, i_avail2=False).pulse(i_rotate=True, after=2).hold(2, i_avail3=False).hold(2, i_avail1=True)
    s.pulse(i_rotate=True, after=2).hold(2, i_avail2=True).hold(2, i_avail3=True).hold(2, i_lagDemand=False)
    s.hold(2, i_avail1=False, i_avail2=False, i_avail3=False).hold(2, i_avail3=True).hold(2, i_lagDemand=True, i_avail2=True)
    s.hold(2, i_avail3=False).hold(2, i_avail3=True, i_avail1=True)
    s.random_phase(300, toggle={"i_rotate": 0.15, "i_lagDemand": 0.06, "i_avail1": 0.05, "i_avail2": 0.05, "i_avail3": 0.05})


def status_word(s: Stimulus) -> None:
    s.hold(2)
    for word in (1, 2, 3, 4, 5, 6, 7, 128, 3, 7, 0, 255, 8, 11, 16, 256, 259):
        s.hold(2, i_controlWord=word)
    s.hold(2, i_controlWord=3, i_speedRef=8192, i_atSpeed=True).hold(2, i_controlWord=7).hold(2, i_speedRef=16384)
    s.hold(2, i_atSpeed=False).hold(2, i_speedRef=-4096, i_atSpeed=True).hold(1, i_speedRef=1)
    # A fault latches. The reset bit is refused while the fault is present, and the edge counts once.
    s.hold(2, i_controlWord=3, i_driveFault=True).hold(2, i_controlWord=131).hold(2, i_driveFault=False)
    s.hold(2, i_controlWord=3).hold(1, i_controlWord=131).hold(2, i_controlWord=3)
    s.pulse(i_driveFault=True, after=2).pulse(i_driveFault=True, after=2).hold(1, i_controlWord=135).hold(2, i_controlWord=7)
    # Only bit 7 resets: 127 has every lower bit set, and 255 has bit 7 and every lower bit.
    s.pulse(i_driveFault=True, after=1).hold(2, i_controlWord=127).hold(2, i_controlWord=255).hold(2, i_controlWord=3)
    s.random_phase(250, toggle={"i_driveFault": 0.05, "i_atSpeed": 0.1}, choose={"i_controlWord": (0.25, [0, 1, 2, 3, 5, 7, 128, 131, 135, 255, 256]), "i_speedRef": (0.1, [0, 4096, 8192, 16384, -4096, 12288])})


def heater_pi(s: Stimulus) -> None:
    s.hold(2, i_setpoint=60.0, i_measured=20.0)
    # The first enabled scan loads the integral from the output, so run while disabled first.
    s.hold(6, i_enable=True).hold(4, i_measured=59.0).hold(5, i_measured=61.0).hold(6, i_measured=60.0)
    # Deadband, exactly on its edge and just inside it.
    s.hold(1, i_deadband=2.0).hold(2, i_measured=58.0).hold(2, i_measured=58.125).hold(2, i_measured=62.0).hold(2, i_measured=61.875).hold(1, i_deadband=0.0)
    # Saturate high and low, and leave saturation. The integral must not wind up.
    s.hold(5, i_measured=0.0).hold(5, i_measured=200.0).hold(5, i_measured=60.0).hold(5, i_measured=61.0)
    # A disable holds output and integral, but clears the saturated flag.
    s.hold(4, i_measured=-100.0).hold(4, i_enable=False, i_measured=30.0).hold(4, i_enable=True)
    s.hold(1, i_kp=0.25, i_ki=0.125).ramp("i_measured", 80.0, 25).ramp("i_measured", 40.0, 25)
    # ROUND on exact halves of a tick: outputs 2.25 and 2.75 are ticks 22.5 and 27.5.
    s.hold(1, i_kp=1.0, i_ki=0.0, i_setpoint=10.0).hold(2, i_measured=7.75).hold(2, i_measured=7.25).hold(2, i_measured=8.125).hold(1, i_ki=0.125)
    s.random_phase(250, toggle={"i_enable": 0.02}, walk={"i_setpoint": (20.0, 90.0, 4.0), "i_measured": (10.0, 100.0, 5.0), "i_outMax": (50.0, 100.0, 5.0), "i_deadband": (0.0, 3.0, 0.5)})


def packaging_counter(s: Stimulus) -> None:
    s.hold(3)
    for _ in range(3):
        s.pulse(i_photoEye=True, after=2)  # Batch full at 3, and on the falling edges.
    s.pulse(i_photoEye=True, after=2).pulse(i_resetCount=True, after=2)
    s.pulse(i_photoEye=True, after=2)
    # Reject on the falling edge of the request. A pulse ignores a new request.
    s.pulse(i_rejectRequest=True, after=2).hold(6).pulse(i_rejectRequest=True, after=1).pulse(i_rejectRequest=True, after=5)
    s.hold(3)
    # Jam: too long on the eye, latching, blocking rejects, stopping the belt, and then cleared.
    s.hold(10, i_photoEye=True).hold(2, i_photoEye=False).pulse(i_rejectRequest=True, after=4).pulse(i_clearJam=True, after=2)
    s.hold(4, i_photoEye=True).hold(2, i_photoEye=False).hold(2, i_clearJam=True, i_photoEye=True).hold(8, i_clearJam=False).hold(2, i_photoEye=False)
    s.pulse(i_clearJam=True, after=2)
    # Speed limit, and the batch size changing under the counter.
    s.hold(2, i_speedRef=60.0).hold(2, i_speedRef=120.0).hold(2, i_batchSize=2).hold(2, i_batchSize=100).hold(2, i_resetCount=True).hold(1, i_resetCount=False)
    s.random_phase(450, toggle={"i_photoEye": 0.18, "i_rejectRequest": 0.15, "i_resetCount": 0.01, "i_clearJam": 0.04}, choose={"i_batchSize": (0.01, [3, 5, 100]), "i_speedRef": (0.03, [20.0, 60.0, 120.0]), "i_jamTime": (0.01, [40, 80, 120]), "i_rejectPulse": (0.01, [30, 50])})


# ---- rockwell_st ----


def motor_aoi(s: Stimulus) -> None:
    s.hold(3)
    s.pulse(StartPB=True, after=8).hold(2, RunFeedback=True).hold(3).pulse(StopPB=True, after=2).hold(2, RunFeedback=False)
    # Feedback never arrives: fault, then reset. A reset is refused during an overload.
    s.pulse(StartPB=True, after=6).hold(10).pulse(FaultReset=True, after=2)
    s.pulse(StartPB=True, after=6).hold(2, RunFeedback=True).hold(2, Overload=True).pulse(FaultReset=True, after=1).hold(2, Overload=False).pulse(FaultReset=True, after=2).hold(1, RunFeedback=False)
    # Feedback lost while running.
    s.pulse(StartPB=True, after=5).hold(2, RunFeedback=True).hold(2, RunFeedback=False).hold(2, RunFeedback=True).hold(3, RunFeedback=False).hold(8).pulse(FaultReset=True, after=2)
    # Preset exactly on the task period, and start and stop together.
    s.pulse(StopPB=True, after=2).hold(1, StartDelayMs=10).pulse(StartPB=True, after=4).hold(1, StartDelayMs=35).pulse(StopPB=True, after=2).pulse(StartPB=True, StopPB=True, after=2)
    s.pulse(StartPB=True, after=8).hold(1, RunFeedback=True).hold(2, StartDelayMs=20, FeedbackTimeoutMs=20).hold(2, RunFeedback=False).hold(3).pulse(FaultReset=True, after=2)
    # A reset held through a feedback timeout: the reset on the same scan as the timeout has to clear what the timer holds, or the next scan faults again.
    s.hold(1, StartDelayMs=35, FeedbackTimeoutMs=40).pulse(StartPB=True, after=5).hold(12, FaultReset=True).hold(3, FaultReset=False).pulse(StopPB=True, after=2)
    # A one-scan reset at each moment around the timeout, one of which falls on the very scan the timer expires.
    for offset in range(6, 14):
        s.pulse(StartPB=True, after=1)
        for _ in range(offset):
            s.hold(1)
        s.pulse(FaultReset=True, after=1)
        for _ in range(6):
            s.hold(1)
        s.pulse(FaultReset=True, after=1).pulse(StopPB=True, after=2)
    s.random_phase(300, toggle={"StartPB": 0.1, "StopPB": 0.03, "Overload": 0.012, "RunFeedback": 0.08, "FaultReset": 0.06}, choose={"StartDelayMs": (0.01, [20, 35, 50]), "FeedbackTimeoutMs": (0.01, [20, 40, 60])})


def fill_retry_aoi(s: Stimulus) -> None:
    s.hold(3, LevelPct=50.0)
    # Hysteresis: on each limit, and between them.
    s.hold(2, FillRequest=True).sweep("LevelPct", 20.0, 20.125, 60.0, 80.0, 79.875, 50.0, 20.0, dwell=2)
    s.hold(4, ValveOpen=True).hold(2, ValveOpen=False)
    s.hold(1, LevelPct=20.0)
    # Timeout, wait, retry, until locked out.
    s.hold(8).hold(4).hold(10).hold(4).hold(10).hold(4).pulse(Acknowledge=True, after=3).hold(2, FillRequest=False)
    # A success after a retry keeps the retry count, and an acknowledge during the wait clears everything.
    s.hold(1, FillRequest=True).hold(6).hold(2).pulse(Acknowledge=True, after=3).hold(3, ValveOpen=True).hold(1, ValveOpen=False)
    s.hold(8).hold(2, ValveOpen=True).hold(4).hold(3, ValveOpen=False)
    s.hold(1, MaxRetries=1).hold(8).pulse(Acknowledge=True, after=2).hold(1, MaxRetries=3)
    s.hold(2, FillRequest=False, InflowPerSec=4.0).hold(2, FillRequest=True, ValveOpen=True).hold(1, OpenTimeoutMs=20, RetryWaitMs=30).hold(3, LevelPct=80.0).hold(3, LevelPct=20.0, ValveOpen=False)
    # A one-scan acknowledge at each moment around an open timeout, one of which falls on the very scan the timer expires.
    s.hold(2, FillRequest=False, ValveOpen=False, LevelPct=20.0, OpenTimeoutMs=40, RetryWaitMs=20, MaxRetries=3).pulse(Acknowledge=True, after=1)
    for offset in range(2, 10):
        s.hold(1, FillRequest=True)
        for _ in range(offset):
            s.hold(1)
        s.pulse(Acknowledge=True, after=1)
        for _ in range(4):
            s.hold(1)
        s.hold(1, FillRequest=False).pulse(Acknowledge=True, after=1)
    s.random_phase(450, toggle={"FillRequest": 0.03, "ValveOpen": 0.08, "Acknowledge": 0.04}, walk={"LevelPct": (0.0, 100.0, 12.0)}, choose={"MaxRetries": (0.01, [1, 2, 3]), "OpenTimeoutMs": (0.01, [20, 40]), "RetryWaitMs": (0.01, [20, 30])})


def sequence_aoi(s: Stimulus) -> None:
    s.hold(3)
    def cycle() -> None:
        s.pulse(StartCmd=True, after=6).hold(3).hold(8, ConductivityOk=False).hold(10, ConductivityOk=True).hold(6)
    s.hold(1, ConductivityOk=True)
    cycle()
    cycle()
    # Out of conductivity for long enough to raise the deviation alarm, which takes 20 scans.
    s.pulse(StartCmd=True, after=6).hold(1, ConductivityOk=False).hold(30).hold(10, ConductivityOk=True).hold(6)
    # Hold freezes nothing but the timer, which restarts from zero.
    s.pulse(StartCmd=True, after=3).pulse(2, HoldCmd=True, after=6)
    s.hold(4, ConductivityOk=False).hold(2, ConductivityOk=True).hold(6)
    s.pulse(2, HoldCmd=True, after=8).hold(6)
    # Abort from each step, and a start held through an abort.
    s.pulse(StartCmd=True, after=2).pulse(AbortCmd=True, after=2)
    s.pulse(StartCmd=True, after=6).pulse(AbortCmd=True, after=2)
    s.pulse(StartCmd=True, after=14).pulse(AbortCmd=True, after=2)
    s.hold(2, AbortCmd=True, StartCmd=True).hold(2, AbortCmd=False).hold(2, StartCmd=False)
    s.hold(1, RinseMs=20, WashMs=70)
    cycle()
    s.random_phase(450, toggle={"StartCmd": 0.1, "HoldCmd": 0.04, "AbortCmd": 0.01, "ConductivityOk": 0.06}, choose={"RinseMs": (0.01, [20, 40]), "WashMs": (0.01, [30, 70])})


def alarm_word_aoi(s: Stimulus) -> None:
    s.hold(3)
    # Each alarm alone: too short, then long enough, then acknowledged.
    for name in ("Cond0", "Cond1", "Cond2"):
        s.pulse(2, **{name: True}, after=2).hold(5, **{name: True}).pulse(AckPB=True, after=2).hold(2, **{name: False}).pulse(AckPB=True, after=2)
    # First out: the lower bit wins on a tie, and the first one stays.
    s.hold(5, Cond1=True, Cond2=True).hold(5, Cond0=True).pulse(AckPB=True, after=2).hold(3, Cond0=False, Cond1=False, Cond2=False).pulse(AckPB=True, after=2)
    s.hold(5, Cond2=True).hold(2, Cond1=True).hold(4).hold(2, Cond2=False, Cond1=False).pulse(AckPB=True, after=2)
    # Mask bits, one at a time, including bits above the three in use.
    for mask in (1, 2, 4, 8, 7, 5, 3, 6, 16, 20):
        s.hold(5, MaskWord=mask, Cond0=True, Cond1=True, Cond2=True).hold(1, Cond0=False, Cond1=False, Cond2=False).pulse(AckPB=True, after=2)
    s.hold(1, MaskWord=0, DelayMs=20).hold(4, Cond0=True).hold(1, DelayMs=60).hold(3).hold(2, Cond0=False).pulse(AckPB=True, after=2)
    s.random_phase(300, toggle={"Cond0": 0.07, "Cond1": 0.07, "Cond2": 0.07, "AckPB": 0.1}, choose={"MaskWord": (0.02, [0, 1, 2, 4, 3, 5]), "DelayMs": (0.01, [20, 30, 50])})


# ---- stress ----


def pump_station(s: Stimulus) -> None:
    def feedback(value: bool, *pumps: int) -> dict[str, bool]:
        return {f"FEEDBACK_{pump}": value for pump in pumps}

    s.hold(3)
    # Staged start: level 1, 2 and 3, one stage at a time, with feedback arriving.
    s.hold(3, AUTO=True, LEVEL=30.0).hold(6, LEVEL=40.0).hold(1, **feedback(True, 1)).hold(4)
    s.hold(4, LEVEL=60.0).hold(1, **feedback(True, 2)).hold(3).hold(4, LEVEL=80.0).hold(1, **feedback(True, 3)).hold(4)
    # Hysteresis on the way down, and a stop drops all stages at once.
    s.hold(3, LEVEL=45.0).hold(3, LEVEL=25.0).hold(2, LEVEL=20.0).hold(2, LEVEL=19.875).hold(3, **feedback(False, 1, 2, 3))
    # Exactly on each start level, each entered from below after a stop.
    s.hold(8, LEVEL=35.0, **feedback(True, 1, 2, 3)).hold(8, LEVEL=20.0).hold(8, LEVEL=55.0).hold(8, LEVEL=20.0).hold(8, LEVEL=34.875).hold(8, LEVEL=54.875).hold(12, LEVEL=75.0).hold(8, LEVEL=74.875).hold(4, LEVEL=20.0)
    s.hold(3, **feedback(False, 1, 2, 3))
    # Rotation: the pump with the fewest ticks takes over on the rotation timer.
    s.hold(6, LEVEL=40.0, **feedback(True, 1, 2, 3)).hold(40).hold(30, LEVEL=20.0)
    # Proof failure on each pump: retry after the delay, then lockout, and reset.
    s.hold(3, **feedback(False, 1, 2, 3)).hold(3, LEVEL=40.0)
    s.hold(60).pulse(RESET=True, after=2)
    # A thermal trip on the running pump, which also moves duty and refuses reset.
    s.hold(12, **feedback(True, 1, 2, 3)).hold(4, THERMAL_1=True, THERMAL_2=True).hold(1, RESET=True).hold(1, RESET=False).hold(2, THERMAL_1=False, THERMAL_2=False).hold(6).pulse(RESET=True, after=3)
    # Feedback lost while running.
    s.hold(4, FEEDBACK_1=False, FEEDBACK_2=False, FEEDBACK_3=False).hold(8, FEEDBACK_1=True, FEEDBACK_2=True, FEEDBACK_3=True).pulse(RESET=True, after=2)
    # Interlocks stop everything without counting as failures, and each is enough alone.
    for name, value in (("ESTOP_OK", False), ("SUCTION_OK", False), ("DISCHARGE_HIGH", True)):
        s.hold(4, **{name: value}).hold(8, **{name: not value})
    # Maintenance takes a pump out of the choice. More stages wanted than pumps left gives UNMET and an alarm.
    s.hold(8, LEVEL=80.0).hold(4, MAINT_2=True).hold(8, MAINT_1=True).hold(4, MAINT_3=True).hold(4, MAINT_1=False, MAINT_2=False, MAINT_3=False)
    s.pulse(RESET=True, after=3)
    s.hold(4, AUTO=False).hold(4, AUTO=True).hold(6, LEVEL=20.0).pulse(RESET=True, after=2)
    s.hold(1, MAX_RETRIES=1, PROOF_TIME=30).hold(4, LEVEL=40.0).hold(3, FEEDBACK_1=False, FEEDBACK_2=False, FEEDBACK_3=False).hold(12).pulse(RESET=True, after=2).hold(1, MAX_RETRIES=2, PROOF_TIME=50)

    def settle() -> None:
        """Everything healthy, nothing wanted, and every latch and retry count cleared."""
        s.hold(3, AUTO=True, LEVEL=20.0, ESTOP_OK=True, SUCTION_OK=True, DISCHARGE_HIGH=False, THERMAL_1=False, THERMAL_2=False, THERMAL_3=False, MAINT_1=False, MAINT_2=False, MAINT_3=False, **feedback(False, 1, 2, 3))
        s.pulse(RESET=True, after=2)

    # Lockout, then an interlock drop: a locked pump stays locked, and only a reset clears it. All three lock, one after the other.
    settle()
    s.hold(1, MAX_RETRIES=1).hold(60, LEVEL=40.0).hold(5, ESTOP_OK=False).hold(5, ESTOP_OK=True).hold(5, SUCTION_OK=False).hold(5, SUCTION_OK=True)
    # An interlock during the wait before a retry cancels the wait without clearing the retry count.
    settle()
    s.hold(1, MAX_RETRIES=3).hold(10, LEVEL=40.0).hold(4, DISCHARGE_HIGH=True).hold(6, DISCHARGE_HIGH=False)
    # Three failed attempts on each pump before lockout, so a retry count passes 2.
    settle()
    s.hold(130, LEVEL=80.0).pulse(RESET=True, after=2)
    # Long holds exactly on each start level, entered from below, so that one stage more shows on a timer that needs the time to run.
    for level in (35.0, 55.0, 75.0):
        settle()
        s.hold(24, LEVEL=level, **feedback(True, 1, 2, 3))
    settle()

    # Random operation. Interlocks and trips come as short events, so the pumps can reach their deep states between them: a toggled interlock
    # would stay low for about half of the phase, which is what kept the station idle before.
    feedback_toggle = {"FEEDBACK_1": 0.02, "FEEDBACK_2": 0.02, "FEEDBACK_3": 0.02}
    events = [
        dict(ESTOP_OK=False), dict(SUCTION_OK=False), dict(DISCHARGE_HIGH=True), dict(THERMAL_1=True), dict(THERMAL_2=True), dict(THERMAL_3=True),
        dict(MAINT_1=True), dict(MAINT_2=True), dict(MAINT_3=True), dict(AUTO=False), dict(RESET=True), dict(RESET=True), dict(MAX_RETRIES=1), dict(MAX_RETRIES=2), dict(MAX_RETRIES=3),
    ]
    s.hold(1, **feedback(True, 1, 2, 3))
    for _ in range(25):
        s.random_phase(40, toggle=feedback_toggle, walk={"LEVEL": (0.0, 100.0, 6.0)})
        event = s.rng.choice(events)
        if "MAX_RETRIES" in event:
            s.hold(1, **event)
        else:
            s.pulse(s.rng.choice([1, 3, 6]), **event)
        if s.rng.random() < 0.6:
            s.hold(5, RESET=False, FEEDBACK_1=True, FEEDBACK_2=True, FEEDBACK_3=True).pulse(RESET=True)


# ---- public_st ----


def bistable_device(s: Stimulus) -> None:
    s.hold(3)
    s.hold(6, ActivateCmd=True).hold(3, ActivateCmd=False).hold(6, DeactivateCmd=True).hold(3, DeactivateCmd=False)
    s.hold(2, ActivateCmd=True).hold(1, ActivateCmd=False).hold(2)  # Too short to activate.
    s.hold(6, ActivateCmd=True, simActFail=True).hold(6, simActFail=False).hold(2, ActivateCmd=False)
    s.hold(6, DeactivateCmd=True, simDeactFail=True).hold(6, simDeactFail=False).hold(2, DeactivateCmd=False)
    # Commands held together make the device cycle, with the entry reset of the timer on each change.
    s.hold(30, ActivateCmd=True, DeactivateCmd=True).hold(2, ActivateCmd=False, DeactivateCmd=False)
    s.hold(1, cfgActTime=20, cfgDeactTime=60).hold(20, ActivateCmd=True, DeactivateCmd=True).hold(2, ActivateCmd=False, DeactivateCmd=False)
    s.random_phase(350, toggle={"ActivateCmd": 0.12, "DeactivateCmd": 0.12, "simActFail": 0.03, "simDeactFail": 0.03}, choose={"cfgActTime": (0.01, [20, 30, 50]), "cfgDeactTime": (0.01, [30, 60])})


def pi_controller(s: Stimulus) -> None:
    s.hold(3, Setpoint=50.0, ProcessVariable=40.0)
    s.hold(10).hold(1, RepeatsPerMinute=False).hold(10).hold(1, RepeatsPerMinute=True)
    s.hold(4, Reset=True).hold(4, Reset=False)
    # Each output clamp, with error in each direction, which is when integration pauses.
    s.hold(10, Setpoint=500.0).hold(6, ProcessVariable=600.0).hold(10, Setpoint=-500.0).hold(6, ProcessVariable=-600.0).hold(4, Setpoint=50.0, ProcessVariable=50.0)
    s.hold(4, IntegralConstant=0.0).hold(4, IntegralConstant=-1.0).hold(3, IntegralConstant=60.0)
    s.hold(4, Bias=20.0, ProcessVariable=45.0).hold(2, Bias=0.0).hold(4, Kp=0.25, CycleTimeInSecs=0.5)
    s.hold(3, MaxLoopOutput=20.0).hold(3, MinLoopOutput=10.0).hold(2, MaxLoopOutput=100.0, MinLoopOutput=-100.0)
    # The integral's own limits, plus or minus 1000, with a big gain and no clamping of the loop.
    s.hold(1, MaxLoopOutput=5000.0, MinLoopOutput=-5000.0, IntegralConstant=6000.0, Kp=0.0, Setpoint=60.0, ProcessVariable=50.0).hold(6).hold(6, ProcessVariable=70.0).hold(1, IntegralConstant=60.0, Kp=1.0, MaxLoopOutput=100.0, MinLoopOutput=-100.0)
    # The pre-clamped output landing exactly on each limit. With no P term and no bias it is the integral, which moves by exactly 2 a scan here, so it reaches 10 and -10
    # exactly. Whether integration pauses on that scan only shows later, when the error turns and the output leaves the limit.
    s.hold(1, Reset=True, Kp=0.0, Bias=0.0, IntegralConstant=60.0, RepeatsPerMinute=True, CycleTimeInSecs=0.125, MaxLoopOutput=10.0, MinLoopOutput=-10.0, Setpoint=66.0, ProcessVariable=50.0)
    s.hold(1, Reset=False).hold(8).hold(16, Setpoint=34.0).hold(8, Setpoint=66.0).hold(1, Kp=0.5, MaxLoopOutput=100.0, MinLoopOutput=-100.0, Setpoint=50.0, CycleTimeInSecs=0.125)
    s.random_phase(300, toggle={"Reset": 0.015, "RepeatsPerMinute": 0.01}, walk={"Setpoint": (0.0, 100.0, 5.0), "ProcessVariable": (0.0, 100.0, 5.0), "Bias": (-5.0, 5.0, 1.0)})


def alpha_beta_filter(s: Stimulus) -> None:
    s.hold(3, measurement=10.0).hold(5, measurement=20.0).hold(5, measurement=5.0)
    s.hold(1, deltaInSecond=0.0, measurement=30.0).hold(1, deltaInSecond=0.5).hold(5)
    s.hold(5, alpha=0.25, beta=0.125, measurement=40.0).hold(5, alpha=1.0, beta=0.0).hold(5, alpha=0.0, beta=0.25, measurement=-5.0)
    s.hold(1, alpha=0.5, beta=0.0625).ramp("measurement", 60.0, 20).ramp("measurement", -20.0, 20)
    s.random_phase(200, walk={"measurement": (-50.0, 50.0, 8.0), "alpha": (0.25, 0.75, 0.125), "beta": (0.0, 0.25, 0.125)}, choose={"deltaInSecond": (0.03, [0.125, 0.5, 1.0])})


def debounce_bool(s: Stimulus) -> None:
    s.hold(3)
    s.hold(1, inputSignal=True).hold(1, inputSignal=False).hold(2)
    s.hold(6, inputSignal=True).hold(3).hold(1, inputSignal=False).hold(1, inputSignal=True).hold(3)
    s.hold(8, inputSignal=False).hold(3).hold(2, inputSignal=True).hold(2, inputSignal=False)
    s.hold(1, onDelay=20, offDelay=60).hold(5, inputSignal=True).hold(10, inputSignal=False).hold(1, onDelay=60, offDelay=20).hold(9, inputSignal=True).hold(5, inputSignal=False)
    s.random_phase(350, toggle={"inputSignal": 0.2}, choose={"onDelay": (0.01, [20, 30, 60]), "offDelay": (0.01, [20, 30, 60])})


SCENARIOS: dict[str, tuple[Callable[[Stimulus], None], int, dict[str, Any]]] = {
    "unsupported_st/u01_sensor_voting": (sensor_voting, 10, dict(ENABLE=False, PT_A=0.0, PT_B=0.0, PT_C=0.0, BAND=2.0, HIGH_LIMIT=80.0, SPAN=200.0, DISAGREE_DELAY=70, RESET=False)),
    "unsupported_st/u02_valve_manifold": (valve_manifold, 10, dict(RUN_REQ=False, RESET=False, AT_OPEN_1=False, AT_OPEN_2=False, AT_OPEN_3=False, AT_CLOSED_1=True, AT_CLOSED_2=True, AT_CLOSED_3=True, TRAVEL=50)),
    "unsupported_st/u03_tank_strapping": (tank_strapping, 100, dict(LEVEL_MM=0.0, DENSITY=1.0, HOLD=False)),
    "unsupported_st/u04_alarm_ring": (alarm_ring, 10, dict(RAISE_CODE=0, ACK_OLDEST=False, CLEAR_ALL=False)),
    "unsupported_st/u05_pump_duty_records": (pump_duty_records, 100, dict(DEMAND=0, AVAIL_1=False, AVAIL_2=False, AVAIL_3=False, RESET_TICKS=False)),
    "unsupported_st/u06_cascade_nested": (cascade_nested, 100, dict(ENABLE=False, MASTER_AUTO=False, TEMP_SP=0.0, TEMP_PV=0.0, FLOW_PV=0.0, MANUAL_FLOW_SP=0.0)),
    "siemens_scl/s01_conveyor_starter": (conveyor_starter, 10, dict(i_start=False, i_stop=False, i_estopOk=True, i_overload=False, i_reset=False, i_hornTime=50, i_coastTime=40)),
    "siemens_scl/s02_analog_input": (analog_input, 10, dict(i_raw=0, i_scaleMin=0.0, i_scaleMax=100.0, i_highLimit=90.0, i_lowLimit=10.0, i_alarmDelay=30, i_simulate=False, i_simValue=0.0)),
    "siemens_scl/s03_valve_monitor": (valve_monitor, 10, dict(i_openCmd=False, i_atOpen=False, i_atClosed=True, i_maintenance=False, i_ack=False, i_travelTime=30, i_margin=20)),
    "siemens_scl/s04_batch_steps": (batch_steps, 10, dict(i_start=False, i_abort=False, i_doseDone=False, i_tempReached=False, i_tankEmpty=False, i_mixTime=50, i_holdTime=60)),
    "siemens_scl/s05_lead_lag_array": (lead_lag_array, 100, dict(i_rotate=False, i_lagDemand=False, i_avail1=False, i_avail2=False, i_avail3=False)),
    "siemens_scl/s06_status_word": (status_word, 10, dict(i_controlWord=0, i_speedRef=0, i_driveFault=False, i_atSpeed=False)),
    "siemens_scl/s07_heater_pi": (heater_pi, 100, dict(i_enable=False, i_setpoint=0.0, i_measured=0.0, i_kp=0.5, i_ki=0.25, i_outMax=100.0, i_deadband=0.0)),
    "siemens_scl/s08_packaging_counter": (packaging_counter, 10, dict(i_photoEye=False, i_rejectRequest=False, i_resetCount=False, i_batchSize=3, i_rejectPulse=30, i_jamTime=80, i_clearJam=False, i_maxSpeed=100.0, i_speedRef=60.0)),
    "rockwell_st/r01_motor_aoi": (motor_aoi, 10, dict(StartPB=False, StopPB=False, Overload=False, RunFeedback=False, FaultReset=False, StartDelayMs=35, FeedbackTimeoutMs=40, TaskPeriodMs=10)),
    "rockwell_st/r02_fill_retry_aoi": (fill_retry_aoi, 10, dict(FillRequest=False, LevelPct=50.0, StartPct=20.0, StopPct=80.0, ValveOpen=False, InflowPerSec=2.0, OpenTimeoutMs=40, RetryWaitMs=20, MaxRetries=3, Acknowledge=False, TaskPeriodMs=10)),
    "rockwell_st/r03_sequence_aoi": (sequence_aoi, 10, dict(StartCmd=False, HoldCmd=False, AbortCmd=False, ConductivityOk=False, RinseMs=40, WashMs=50, TaskPeriodMs=10)),
    "rockwell_st/r04_alarm_word_aoi": (alarm_word_aoi, 10, dict(Cond0=False, Cond1=False, Cond2=False, MaskWord=0, DelayMs=30, AckPB=False, TaskPeriodMs=10)),
    "stress/x01_pump_station": (pump_station, 10, dict(
        AUTO=False, ESTOP_OK=True, SUCTION_OK=True, DISCHARGE_HIGH=False, RESET=False, LEVEL=0.0, LEVEL_STOP=20.0, LEVEL_1=35.0, LEVEL_2=55.0, LEVEL_3=75.0,
        FEEDBACK_1=False, FEEDBACK_2=False, FEEDBACK_3=False, THERMAL_1=False, THERMAL_2=False, THERMAL_3=False, MAINT_1=False, MAINT_2=False, MAINT_3=False,
        PROOF_TIME=50, RETRY_DELAY=30, STAGE_DELAY=40, ROTATE_TIME=300, MAX_RETRIES=2,
    )),
    "public_st/p01_bistable_device": (bistable_device, 10, dict(ActivateCmd=False, DeactivateCmd=False, cfgActTime=30, cfgDeactTime=30, simActFail=False, simDeactFail=False)),
    "public_st/p02_pi_controller": (pi_controller, 100, dict(Reset=False, ProcessVariable=0.0, Setpoint=0.0, Kp=0.5, IntegralConstant=60.0, RepeatsPerMinute=True, MaxLoopOutput=100.0, MinLoopOutput=-100.0, Bias=0.0, CycleTimeInSecs=0.125)),
    "public_st/p03_alpha_beta_filter": (alpha_beta_filter, 100, dict(measurement=0.0, deltaInSecond=0.125, alpha=0.5, beta=0.125)),
    "public_st/p04_debounce_bool": (debounce_bool, 10, dict(inputSignal=False, onDelay=30, offDelay=30)),
}


# ---- what only held-out holds ----
#
# Every value below is one that no tuning stimulus holds, on purpose: a migration that froze a tuned value fails here. `first` runs in
# heldout_stimulus.json, at the tuning period. `second` runs in heldout_stimulus_2.json, where `pinned` also holds for the whole file.


def status_word_new_bits(s: Stimulus) -> None:
    """Bits above the ones in use, alone and beside bit 7. A latched fault shows whether bit 7 was read correctly."""
    for word in (384, 387, 512, 515, 640, 643):
        s.hold(2, i_driveFault=True, i_controlWord=3, i_atSpeed=True, i_speedRef=2048).hold(2, i_driveFault=False, i_controlWord=word).hold(2, i_controlWord=3)


def analog_input_new_delay(s: Stimulus, delay: int, other: int) -> None:
    s.hold(2, i_simulate=False, i_scaleMin=-25.0, i_scaleMax=75.0, i_highLimit=60.0, i_lowLimit=-15.0, i_raw=13824, i_alarmDelay=delay)
    # Too short for this delay, then long enough, for each alarm.
    for raw in (27000, 1000, 32767):
        s.hold(2, i_raw=raw).hold(3, i_raw=13824).hold(9, i_raw=raw).hold(3, i_raw=13824)
    # A new delay asked for while a timer runs waits until no timer is running.
    s.hold(2, i_raw=27000).hold(1, i_alarmDelay=other).hold(9).hold(3, i_raw=13824).hold(9, i_raw=27000).hold(3, i_raw=13824)
    s.hold(4, i_simulate=True, i_simValue=65.0).hold(9).hold(4, i_simValue=-20.0).hold(9).hold(2, i_simulate=False)


def packaging_new_values(s: Stimulus, max_speed: float, batch: int, pulse: int, jam: int) -> None:
    s.hold(2, i_photoEye=False, i_rejectRequest=False).pulse(i_clearJam=True, i_resetCount=True, after=1)
    s.hold(2, i_batchSize=100, i_maxSpeed=max_speed, i_speedRef=max_speed + 10.0).hold(2, i_speedRef=max_speed - 10.0).hold(2, i_speedRef=max_speed)
    s.hold(1, i_batchSize=batch, i_rejectPulse=pulse, i_jamTime=jam)
    for _ in range(batch + 1):
        s.pulse(i_photoEye=True, after=1)
    s.pulse(i_resetCount=True, after=1).pulse(i_rejectRequest=True, after=9).hold(14, i_photoEye=True).hold(2, i_photoEye=False)
    s.pulse(i_clearJam=True, after=2).hold(1, i_batchSize=100)


def fill_new_limits(s: Stimulus, start: float, stop: float, inflow: float) -> None:
    s.hold(2, FillRequest=True, ValveOpen=True, LevelPct=50.0, StartPct=start, StopPct=stop, InflowPerSec=inflow, MaxRetries=4).pulse(Acknowledge=True, after=1)
    s.sweep("LevelPct", start + 0.125, start, start + 0.125, 50.0, stop - 0.125, stop, stop - 0.125, 50.0, start, dwell=2)
    s.hold(40, ValveOpen=False).pulse(Acknowledge=True, after=2).hold(2, ValveOpen=True)


def voter_new_settings(s: Stimulus, band: float, span: float, delay: int) -> None:
    s.hold(2, ENABLE=True, BAND=band, SPAN=span, DISAGREE_DELAY=delay, PT_A=50.0, PT_B=50.0, PT_C=50.0).pulse(RESET=True, after=1)
    # On the band edge and just past it, then a disagreement too short for this delay and one long enough.
    s.hold(2, PT_A=50.0 + band).hold(2, PT_A=50.0 + band + 0.125).hold(2, PT_A=50.0)
    s.hold(4, PT_A=70.0).hold(3, PT_A=50.0).hold(18, PT_A=70.0).hold(3, PT_A=50.0).pulse(RESET=True, after=1)
    s.sweep("PT_B", 10.0, 30.0, 50.0, dwell=1)
    for value in (span / 100.0, 3.0 * span / 200.0, 5.0 * span / 200.0):
        s.hold(1, PT_A=value, PT_B=value, PT_C=value)
    s.hold(2, HIGH_LIMIT=70.0, PT_A=50.0, PT_B=50.0, PT_C=50.0).pulse(RESET=True, after=1)
    s.hold(3, PT_A=70.0, PT_B=70.0, PT_C=70.0).hold(3, PT_A=70.125, PT_B=70.125, PT_C=70.125).hold(2, PT_A=50.0, PT_B=50.0, PT_C=50.0).pulse(RESET=True, after=1)
    s.hold(1, HIGH_LIMIT=80.0)


def station_new_settings(s: Stimulus, stop: float, one: float, two: float, three: float, retry: int, stage: int, rotate: int, proof: int) -> None:
    feedback = {f"FEEDBACK_{pump}": True for pump in (1, 2, 3)}
    healthy = dict(ESTOP_OK=True, SUCTION_OK=True, DISCHARGE_HIGH=False, THERMAL_1=False, THERMAL_2=False, THERMAL_3=False, MAINT_1=False, MAINT_2=False, MAINT_3=False)
    settings = dict(LEVEL_STOP=stop, LEVEL_1=one, LEVEL_2=two, LEVEL_3=three, RETRY_DELAY=retry, STAGE_DELAY=stage, ROTATE_TIME=rotate, PROOF_TIME=proof, MAX_RETRIES=4)
    s.hold(3, AUTO=True, LEVEL=stop, **healthy, **settings, **feedback).pulse(RESET=True, after=2)
    # Exactly on each start level from below, long enough for the stages to climb, then on the stop level and just above it.
    for level in (one, two, three):
        s.hold(3, LEVEL=stop).hold(30, LEVEL=level).hold(3, LEVEL=stop + 0.125).hold(3, LEVEL=stop)
    # Just under each start level.
    for level in (one, two, three):
        s.hold(12, LEVEL=level - 0.125).hold(3, LEVEL=stop)
    # Rotation on this period, with the duty pump and its ticks moving.
    s.hold(60, LEVEL=one)
    # Retries on this delay, then lockout, with no feedback at all.
    s.hold(3, LEVEL=stop, FEEDBACK_1=False, FEEDBACK_2=False, FEEDBACK_3=False).hold(150, LEVEL=one).pulse(RESET=True, after=2).hold(3, LEVEL=stop)


@dataclass(frozen=True)
class HeldoutPlan:
    start: list[dict[str, Any]]  # One entry per scan, from scan 0, each differing from tuning's scan 0. The defaults are restored after them.
    first: Callable[[Stimulus], None] | None = None
    second: Callable[[Stimulus], None] | None = None
    pinned: dict[str, Any] = field(default_factory=dict)
    second_seed: int = HELDOUT_2_SEED


def _both(**changes: Any) -> Callable[[Stimulus], None]:
    return lambda s: s.hold(4, **changes)


def _level(values: tuple[float, ...]) -> Callable[[Stimulus], None]:
    return lambda s: s.sweep("LEVEL_MM", *values, dwell=2)


PLANS: dict[str, HeldoutPlan] = {
    "unsupported_st/u01_sensor_voting": HeldoutPlan(
        [dict(ENABLE=True, PT_A=90.0, PT_B=90.0, PT_C=90.0)] * 3 + [dict(ENABLE=True, PT_A=50.0, PT_B=50.0, PT_C=50.0, RESET=True)],
        lambda s: voter_new_settings(s, 3.0, 100.0, 50), lambda s: voter_new_settings(s, 1.5, 400.0, 105), dict(BAND=1.5, SPAN=400.0, DISAGREE_DELAY=105),
    ),
    "unsupported_st/u02_valve_manifold": HeldoutPlan(
        [dict(RUN_REQ=True, AT_CLOSED_1=False)] * 2 + [dict(RESET=True)],
        lambda s: s.hold(1, TRAVEL=40, RUN_REQ=False).pulse(RESET=True, after=2).hold(8, RUN_REQ=True, AT_CLOSED_1=False, AT_OPEN_1=False, AT_CLOSED_2=True, AT_OPEN_2=False, AT_CLOSED_3=True, AT_OPEN_3=False),
        None, dict(TRAVEL=36),
    ),
    "unsupported_st/u03_tank_strapping": HeldoutPlan([dict(LEVEL_MM=500.0, DENSITY=0.875)] * 2, lambda s: s.hold(1, DENSITY=1.0625).sweep("LEVEL_MM", 150.0, 350.0, 700.0, 1100.0, 1900.0, dwell=2), lambda s: s.hold(1, DENSITY=0.5625).sweep("LEVEL_MM", 250.0, 450.0, 900.0, 1300.0, 1800.0, dwell=2)),
    "unsupported_st/u04_alarm_ring": HeldoutPlan(
        [dict(RAISE_CODE=9), dict(RAISE_CODE=9), dict(CLEAR_ALL=True)],
        lambda s: [s.hold(2, RAISE_CODE=code).hold(1, RAISE_CODE=0) for code in (51, 52, 53, 54, 55)], lambda s: [s.hold(2, RAISE_CODE=code).hold(1, RAISE_CODE=0) for code in (61, 62, 63)],
    ),
    "unsupported_st/u05_pump_duty_records": HeldoutPlan([dict(AVAIL_1=True, AVAIL_3=True, DEMAND=1)] * 2, lambda s: s.hold(3, DEMAND=5, AVAIL_1=True, AVAIL_2=True, AVAIL_3=True).hold(3, DEMAND=0), lambda s: s.hold(3, DEMAND=6, AVAIL_1=True, AVAIL_2=True, AVAIL_3=True).hold(3, DEMAND=0)),
    "unsupported_st/u06_cascade_nested": HeldoutPlan([dict(ENABLE=True, TEMP_SP=30.0, TEMP_PV=25.0, FLOW_PV=5.0)] * 2, lambda s: s.hold(6, ENABLE=True, MASTER_AUTO=True, TEMP_SP=35.0, TEMP_PV=33.0, FLOW_PV=12.0), lambda s: s.hold(6, ENABLE=True, MASTER_AUTO=False, MANUAL_FLOW_SP=33.0, FLOW_PV=31.0),
        # Not the usual seed. Under it, one scan's demand cancels to about 0.09, and matiec's `** 0.5` and FORTE's are one unit in the last place apart, which cancellation lifts over the
        # comparison's relative tolerance. So no correct FB could pass that file, and hard_check's solvability control showed it. This seed changes nothing else about the recipe.
        second_seed=104761),
    "siemens_scl/s01_conveyor_starter": HeldoutPlan(
        [dict(i_start=True), dict(i_stop=True), dict(i_stop=True)],
        lambda s: s.hold(1, i_hornTime=90, i_coastTime=60, i_stop=False, i_overload=False, i_reset=True, i_estopOk=True).pulse(i_start=True, after=12).pulse(i_stop=True, after=9),
        None, dict(i_hornTime=64, i_coastTime=36),
    ),
    "siemens_scl/s02_analog_input": HeldoutPlan(
        [dict(i_raw=13000)] * 2 + [dict(i_raw=2000)],
        lambda s: analog_input_new_delay(s, 50, 70), lambda s: analog_input_new_delay(s, 45, 45), dict(i_alarmDelay=45),
    ),
    "siemens_scl/s03_valve_monitor": HeldoutPlan(
        [dict(i_openCmd=True, i_atClosed=False)] * 2 + [dict(i_ack=True)],
        lambda s: s.hold(1, i_travelTime=40, i_margin=40, i_maintenance=False, i_ack=True, i_openCmd=False, i_atOpen=False, i_atClosed=True).hold(1, i_ack=False).hold(11, i_openCmd=True, i_atClosed=False).pulse(i_ack=True, after=1).hold(2, i_openCmd=False),
        None, dict(i_travelTime=29, i_margin=15),
    ),
    "siemens_scl/s04_batch_steps": HeldoutPlan(
        [dict(i_start=True), dict(i_abort=True), dict(i_tankEmpty=True)],
        lambda s: s.hold(2, i_mixTime=40, i_holdTime=100, i_abort=False, i_start=False, i_doseDone=False, i_tempReached=False, i_tankEmpty=False).pulse(i_abort=True, after=1).hold(2, i_tankEmpty=True).hold(2, i_tankEmpty=False).pulse(i_start=True, after=2).hold(1, i_doseDone=True).hold(1, i_doseDone=False).hold(8).hold(1, i_tempReached=True).hold(14, i_tempReached=False).hold(2, i_tankEmpty=True).hold(2, i_tankEmpty=False),
        None, dict(i_mixTime=43, i_holdTime=71),
    ),
    "siemens_scl/s05_lead_lag_array": HeldoutPlan([dict(i_avail3=True, i_lagDemand=True)] * 2),
    "siemens_scl/s06_status_word": HeldoutPlan([dict(i_controlWord=3, i_speedRef=4096)] * 2, status_word_new_bits, lambda s: (status_word_new_bits(s), s.hold(2, i_controlWord=1152), s.hold(2, i_controlWord=1155))),
    "siemens_scl/s07_heater_pi": HeldoutPlan(
        [dict(i_enable=True, i_setpoint=40.0, i_measured=30.0)] * 2,
        lambda s: s.hold(1, i_enable=True, i_kp=0.75, i_ki=0.0625, i_outMax=60.0, i_deadband=1.5).hold(4, i_setpoint=50.0, i_measured=40.0).hold(4, i_measured=48.5).hold(4, i_measured=48.625),
        None, dict(i_kp=0.375, i_ki=0.1875, i_outMax=75.0),
    ),
    "siemens_scl/s08_packaging_counter": HeldoutPlan(
        [dict(i_photoEye=True, i_rejectRequest=True)] * 2 + [dict()] * 2 + [dict(i_resetCount=True)],
        lambda s: packaging_new_values(s, 80.0, 7, 70, 60), lambda s: packaging_new_values(s, 75.0, 4, 41, 61), dict(i_maxSpeed=75.0),
    ),
    "rockwell_st/r01_motor_aoi": HeldoutPlan(
        [dict(StartPB=True), dict(StopPB=True), dict(StopPB=True)],
        lambda s: s.hold(1, StartDelayMs=45, FeedbackTimeoutMs=33, StopPB=False, Overload=False, RunFeedback=False, FaultReset=True).hold(1, FaultReset=False).pulse(StartPB=True, after=12).pulse(FaultReset=True, after=2).pulse(StopPB=True, after=2),
        None, dict(StartDelayMs=36, FeedbackTimeoutMs=29),
    ),
    "rockwell_st/r02_fill_retry_aoi": HeldoutPlan(
        [dict(FillRequest=True, LevelPct=10.0)] * 2 + [dict(Acknowledge=True)],
        lambda s: fill_new_limits(s, 30.0, 70.0, 3.0), lambda s: fill_new_limits(s, 25.0, 75.0, 1.5), dict(StartPct=25.0, StopPct=75.0, OpenTimeoutMs=29, RetryWaitMs=15),
    ),
    "rockwell_st/r03_sequence_aoi": HeldoutPlan(
        [dict(StartCmd=True, ConductivityOk=True), dict(AbortCmd=True, ConductivityOk=True), dict(ConductivityOk=True)],
        lambda s: s.hold(1, RinseMs=60, WashMs=90, AbortCmd=True, StartCmd=False, HoldCmd=False, ConductivityOk=True).hold(1, AbortCmd=False).pulse(StartCmd=True, after=9).hold(14).hold(10),
        None, dict(RinseMs=36, WashMs=57),
    ),
    "rockwell_st/r04_alarm_word_aoi": HeldoutPlan(
        [dict(Cond2=True)] * 2 + [dict(AckPB=True)],
        lambda s: s.hold(2, DelayMs=40, MaskWord=9, Cond0=True, Cond1=True, Cond2=True).hold(5).hold(2, Cond0=False, Cond1=False, Cond2=False).pulse(AckPB=True, after=1).hold(5, MaskWord=34, Cond1=True).hold(2, Cond1=False).pulse(AckPB=True, after=1).hold(1, MaskWord=0),
        None, dict(DelayMs=29),
    ),
    "stress/x01_pump_station": HeldoutPlan(
        [dict(AUTO=True, LEVEL=40.0)] * 2 + [dict(RESET=True)],
        lambda s: station_new_settings(s, 25.0, 40.0, 60.0, 80.0, 50, 20, 150, 64),
        lambda s: station_new_settings(s, 15.0, 30.0, 50.0, 70.0, 41, 29, 211, 57),
        dict(LEVEL_STOP=15.0, LEVEL_1=30.0, LEVEL_2=50.0, LEVEL_3=70.0, RETRY_DELAY=41, STAGE_DELAY=29, ROTATE_TIME=211),
    ),
    "public_st/p01_bistable_device": HeldoutPlan(
        [dict(ActivateCmd=True), dict(ActivateCmd=True, simActFail=True)],
        lambda s: s.hold(1, cfgActTime=40, cfgDeactTime=80, ActivateCmd=False, DeactivateCmd=False, simActFail=False, simDeactFail=False).hold(6, ActivateCmd=True).hold(2, ActivateCmd=False).hold(10, DeactivateCmd=True).hold(2, DeactivateCmd=False),
        None, dict(cfgActTime=36, cfgDeactTime=57),
    ),
    "public_st/p02_pi_controller": HeldoutPlan(
        [dict(Setpoint=10.0, ProcessVariable=5.0)] * 2 + [dict(Reset=True)],
        lambda s: s.hold(1, CycleTimeInSecs=0.25, IntegralConstant=120.0, Kp=0.75, Reset=False, MaxLoopOutput=90.0, MinLoopOutput=-90.0, Bias=2.0).hold(8, Setpoint=40.0, ProcessVariable=30.0).hold(4, RepeatsPerMinute=False),
        None, dict(CycleTimeInSecs=0.0625, Kp=0.375),
    ),
    "public_st/p03_alpha_beta_filter": HeldoutPlan([dict(measurement=25.0)] * 2, lambda s: s.hold(6, alpha=0.6875, beta=0.1875, deltaInSecond=0.25, measurement=12.0), lambda s: s.hold(6, alpha=0.3125, beta=0.3125, deltaInSecond=0.375, measurement=-7.0)),
    "public_st/p04_debounce_bool": HeldoutPlan(
        [dict(inputSignal=True)] * 2,
        lambda s: s.hold(1, onDelay=40, offDelay=50).hold(7, inputSignal=True).hold(8, inputSignal=False),
        None, dict(onDelay=36, offDelay=57),
    ),
}


def _scored(key: str, scan_ms: int, seed: int, phase: Callable[[Stimulus], None] | None, pinned: dict[str, Any], stretch: float = 1.0) -> ScoredStimulus:
    scenario, base_ms, defaults = SCENARIOS[key]
    stimulus = ScoredStimulus(key.split("/")[1], scan_ms, seed=seed, stretch=stretch, pinned=pinned, **defaults)
    for row in PLANS[key].start:
        stimulus.hold(1, **row)
        stimulus.current.update(defaults)
    stimulus.hold(1)  # Back at the defaults, and the scenario starts from there.
    scenario(stimulus)
    if phase is not None:
        phase(stimulus)
    stimulus.closing_phase(CLOSING_SCANS).retune_phase()
    return stimulus


def build(key: str) -> dict[str, Stimulus]:
    """All four stimuli of one program, in memory."""
    scenario, scan_ms, defaults = SCENARIOS[key]
    tuning = Stimulus(key.split("/")[1], scan_ms, **defaults)
    scenario(tuning)
    plan = PLANS[key]
    period = SECOND_PERIOD[scan_ms]
    pinned = dict(plan.pinned)
    if "TaskPeriodMs" in defaults:
        pinned["TaskPeriodMs"] = period  # The block is told its scan period, so this input follows the period of the file.
    first = _scored(key, scan_ms, HELDOUT_SEED, plan.first, {})
    second = _scored(key, period, plan.second_seed, plan.second, pinned, scan_ms / period)
    pairing = _scored(key, scan_ms, PAIRING_SEED, plan.first, {})
    return {TUNING_FILE: tuning, HELDOUT_FILE: first, HELDOUT_2_FILE: second, PAIRING_FILE: pairing}


def main() -> None:
    for key in sorted(SCENARIOS):
        directory = ROOT / key
        built = build(key)
        for file_name, stimulus in built.items():
            (directory / file_name).write_text(render(stimulus))
        print(f"{key}: {' / '.join(str(len(s.scans)) for s in built.values())} scans at {built[TUNING_FILE].scan_ms} and {built[HELDOUT_2_FILE].scan_ms} ms")


if __name__ == "__main__":
    main()
