#!/usr/bin/env python3
"""Two checks of the oracle pairings. Neither is independent of how this project reads the vendor language.

    python3 scripts/check_pairing.py

reference.st is a hand translation of program.scl or program.l5k, and neither TIA Portal nor Studio 5000 is available to check it.

Check A, all 12 paired programs. st2fb/vendor_frontend.py rewrites the vendor file by rule, without reading reference.st. matiec runs that and reference.st on every stimulus,
pairing_stimulus.json included, and the traces must match. It shares matiec with the oracle, and it shares the reading of the dialect file with the reference.

Check B, 5 programs. A Python model written from the vendor file, statement by statement, against matiec on reference.st, on pairing_stimulus.json. It is independent of matiec's
execution and NOT independent of the reading of the vendor language: the same author wrote both, and the models read each vendor timer as the dialect prompt does.

So a shared misreading would not show in either. These check the translation of the logic, and not whether a reading matches a real S7 or Logix controller. Neither is the oracle, and a
Python simulation never scores anything.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from st2fb import compare, reference_run, vendor_frontend  # noqa: E402

HARD = REPO / "corpus_hard"


class Ton:
    """lib/timer.txt, as tabulated in docs/CORPUS.md."""

    def __init__(self) -> None:
        self.state, self.prev, self.start, self.q, self.et = 0, False, 0, False, 0

    def __call__(self, now: int, in_: bool, pt: int) -> None:
        if self.state == 0 and not self.prev and in_:
            self.state, self.q, self.start = 1, False, now
        elif not in_:
            self.et, self.q, self.state = 0, False, 0
        elif self.state == 1:
            if self.start + pt <= now:
                self.state, self.q, self.et = 2, True, pt
            else:
                self.et = now - self.start
        self.prev = in_


class Tof:
    def __init__(self) -> None:
        self.state, self.prev, self.start, self.q, self.et = 0, False, 0, False, 0

    def __call__(self, now: int, in_: bool, pt: int) -> None:
        if self.state == 0 and self.prev and not in_:
            self.state, self.start = 1, now
        elif in_:
            self.et, self.state = 0, 0
        elif self.state == 1:
            if self.start + pt <= now:
                self.state, self.et = 2, pt
            else:
                self.et = now - self.start
        self.q = in_ or self.state == 1
        self.prev = in_


class Edge:
    def __init__(self) -> None:
        self.m, self.q = False, False

    def __call__(self, clk: bool) -> None:
        self.q, self.m = clk and not self.m, clk


class Tonr:
    """The dialect prompt's FBD_TIMER."""

    def __init__(self) -> None:
        self.en, self.tt, self.dn, self.prev, self.acc = False, False, False, False, 0

    def __call__(self, enable: bool, pre: int, period: int) -> None:
        self.en = enable
        if self.en:
            if self.prev and not self.dn:
                self.acc += period
                if self.acc >= pre:
                    self.acc, self.dn = pre, True
        else:
            self.acc, self.dn = 0, False
        self.tt = self.en and not self.dn
        self.prev = self.en

    def res(self) -> None:
        self.en, self.tt, self.dn, self.prev, self.acc = False, False, False, False, 0


def conveyor_starter(scans: list[dict[str, Any]], scan_ms: int) -> Iterator[dict[str, Any]]:
    """siemens_scl/s01_conveyor_starter/program.scl"""
    run_request = trip = o_run = False
    horn_preset = coast_preset = 0
    start_edge, horn, coast = Edge(), Ton(), Tof()
    for index, s in enumerate(scans):
        now = index * scan_ms
        if s["i_overload"] or not s["i_estopOk"]:
            trip = True
        elif s["i_reset"]:
            trip = False
        permit = s["i_estopOk"] and not trip
        if not run_request:
            horn_preset = s["i_hornTime"]
        if o_run:
            coast_preset = s["i_coastTime"]
        start_edge(s["i_start"])
        if s["i_stop"] or not permit:
            run_request = False
        elif start_edge.q:
            run_request = True
        horn(now, run_request, horn_preset)
        o_run = run_request and horn.q
        coast(now, o_run, coast_preset)
        yield {
            "o_run": o_run, "o_horn": run_request and not horn.q, "o_tripped": trip,
            "o_coasting": coast.q and not o_run, "o_hornElapsed": horn.et,
        }


def valve_monitor(scans: list[dict[str, Any]], scan_ms: int) -> Iterator[dict[str, Any]]:
    """siemens_scl/s03_valve_monitor/program.scl. RETURN freezes every output, since outputs keep their values."""
    open_t, close_t, fault_edge = Ton(), Ton(), Edge()
    open_budget = close_budget = 0
    out = {"o_coil": False, "o_fault": False, "o_opening": False, "o_closing": False, "o_openElapsed": 0, "o_closeElapsed": 0, "o_faultCount": 0}
    for index, s in enumerate(scans):
        now = index * scan_ms
        if not s["i_maintenance"]:
            budget = s["i_travelTime"] + s["i_margin"]
            out["o_coil"] = s["i_openCmd"] and not out["o_fault"]
            if not out["o_opening"]:
                open_budget = budget
            if not out["o_closing"]:
                close_budget = budget
            out["o_opening"] = out["o_coil"] and not s["i_atOpen"]
            out["o_closing"] = not out["o_coil"] and not s["i_atClosed"]
            open_t(now, out["o_opening"], open_budget)
            out["o_openElapsed"] = open_t.et
            close_t(now, out["o_closing"], close_budget)
            out["o_closeElapsed"] = close_t.et
            set_ = open_t.q or close_t.q or (s["i_atOpen"] and s["i_atClosed"])
            if s["i_ack"]:
                out["o_fault"] = False
            elif set_:
                out["o_fault"] = True
            fault_edge(out["o_fault"])
            if fault_edge.q:
                out["o_faultCount"] += 1
        yield dict(out)


def status_word(scans: list[dict[str, Any]], scan_ms: int) -> Iterator[dict[str, Any]]:
    """siemens_scl/s06_status_word/program.scl, with real bit operations on the words."""
    latched = False
    fault_edge = Edge()
    fault_count = 0
    for s in scans:
        ctl = s["i_controlWord"] & 0xFFFF
        fault_edge(s["i_driveFault"])
        if fault_edge.q:
            fault_count += 1
        if s["i_driveFault"]:
            latched = True
        elif ctl >> 7 & 1:
            latched = False
        enable, run, reverse = bool(ctl & 1), bool(ctl >> 1 & 1), bool(ctl >> 2 & 1)
        forward_cmd = enable and run and not reverse and not latched
        reverse_cmd = enable and run and reverse and not latched
        running = forward_cmd or reverse_cmd
        speed = s["i_speedRef"] * 100.0 / 16384.0 if running else 0.0
        stat = 0
        stat |= int(enable and not latched) << 0
        stat |= int(running) << 1
        stat |= int(reverse_cmd) << 2
        stat |= int(latched) << 3
        stat |= int(s["i_atSpeed"] and running) << 4
        yield {
            "o_statusWord": stat, "o_runForward": forward_cmd, "o_runReverse": reverse_cmd,
            "o_speedPercent": speed, "o_faultCount": fault_count,
        }


def motor_aoi(scans: list[dict[str, Any]], scan_ms: int) -> Iterator[dict[str, Any]]:
    """rockwell_st/r01_motor_aoi/program.l5k"""
    one_shot = Edge()
    delay, feedback = Tonr(), Tonr()
    run_latch = fault_latch = False
    for s in scans:
        period = s["TaskPeriodMs"]
        one_shot(s["StartPB"])
        if s["StopPB"] or s["Overload"] or fault_latch:
            run_latch = False
        elif one_shot.q:
            run_latch = True
        delay(run_latch, s["StartDelayMs"], period)
        run_cmd = delay.dn
        feedback(run_cmd and not s["RunFeedback"], s["FeedbackTimeoutMs"], period)
        if feedback.dn or s["Overload"]:
            fault_latch = True
        if s["FaultReset"] and not s["Overload"]:
            fault_latch = False
            feedback.res()
        yield {
            "RunCmd": run_cmd, "Starting": delay.tt, "Faulted": fault_latch,
            "DelayEnabled": delay.en, "DelayElapsedMs": delay.acc,
        }


def fill_retry_aoi(scans: list[dict[str, Any]], scan_ms: int) -> Iterator[dict[str, Any]]:
    """rockwell_st/r02_fill_retry_aoi/program.l5k"""
    demand = wait_active = False
    open_t, wait_t = Tonr(), Tonr()
    retries_acc = 0
    retries_prev = False
    retries_dn = False
    ack = Edge()
    total = 0.0
    for s in scans:
        period = s["TaskPeriodMs"]
        if s["LevelPct"] <= s["StartPct"]:
            demand = True
        elif s["LevelPct"] >= s["StopPct"]:
            demand = False
        counter_input = open_t.dn
        if counter_input and not retries_prev:
            retries_acc += 1
        retries_prev = counter_input
        retries_dn = retries_acc >= s["MaxRetries"]
        retry_count, locked = retries_acc, retries_dn
        if open_t.dn and not locked:
            wait_active = True
        wait_t(wait_active, s["RetryWaitMs"], period)
        waiting = wait_t.tt
        if wait_t.dn:
            wait_active = False
        valve = s["FillRequest"] and demand and not locked and not wait_active
        open_t(valve and not s["ValveOpen"], s["OpenTimeoutMs"], period)
        if valve and s["ValveOpen"]:
            total = _single(total + _single(_single(s["InflowPerSec"] * period) / 1000.0))
        ack(s["Acknowledge"])
        if ack.q:
            retries_acc, retries_dn = 0, False
            open_t.res()
            wait_t.res()
            wait_active = False
        yield {"ValveCmd": valve, "WaitingRetry": waiting, "LockedOut": locked, "RetryCount": retry_count, "Totalised": total}


def _single(value: float) -> float:
    """Round to IEEE 754 single, since REAL accumulates in single precision."""
    import struct

    return struct.unpack("f", struct.pack("f", value))[0]


MODELS: dict[str, Callable[[list[dict[str, Any]], int], Iterator[dict[str, Any]]]] = {
    "siemens_scl/s01_conveyor_starter": conveyor_starter,
    "siemens_scl/s03_valve_monitor": valve_monitor,
    "siemens_scl/s06_status_word": status_word,
    "rockwell_st/r01_motor_aoi": motor_aoi,
    "rockwell_st/r02_fill_retry_aoi": fill_retry_aoi,
}


PAIRED = tuple(f"siemens_scl/{path.parent.name}" for path in sorted((HARD / "siemens_scl").glob("*/program.scl"))) + tuple(
    f"rockwell_st/{path.parent.name}" for path in sorted((HARD / "rockwell_st").glob("*/program.l5k"))
)
ALL_STIMULI = ("stimulus.json", "heldout_stimulus.json", "heldout_stimulus_2.json", "pairing_stimulus.json")


def frontend_source(key: str) -> str:
    directory = HARD / key
    source = directory / ("program.scl" if key.startswith("siemens") else "program.l5k")
    return vendor_frontend.to_plain_st(source.read_text(encoding="utf-8"), "siemens_scl" if key.startswith("siemens") else "rockwell_logix")


def frontend_against_reference(key: str, container: reference_run.Container) -> dict[str, dict[str, Any]]:
    directory = HARD / key
    plain = frontend_source(key)
    reference = (directory / "reference.st").read_text(encoding="utf-8")
    reports = {}
    for name in ALL_STIMULI:
        stimulus = json.loads((directory / name).read_text(encoding="utf-8"))
        reports[name] = compare.compare_traces(reference_run.run_reference(reference, stimulus, container), reference_run.run_reference(plain, stimulus, container))
    return reports


def main() -> int:
    reference_run.ensure_image()
    failed = False
    with reference_run.Container() as container:
        print("Check A: matiec on the front-end's rewrite of the vendor file, against matiec on reference.st. Independent of the hand translation. Not independent of matiec or of the dialect file's reading.")
        for key in PAIRED:
            reports = frontend_against_reference(key, container)
            cells = " ".join(f"{name.replace('_stimulus', '').replace('.json', '')}:{report['scans_compared']}{'=' if report['equal'] else '!'}" for name, report in reports.items())
            print(f"{key}: {cells}")
            for name, report in reports.items():
                if not report["equal"]:
                    print(f"  {name}: first {report['first_divergence']}")
                    failed = True
        print("Check B: Python models from the vendor file, against matiec on reference.st. Independent of matiec's execution. NOT independent of the reading of the vendor language.")
        for key, model in MODELS.items():
            directory = HARD / key
            stimulus = json.loads((directory / "pairing_stimulus.json").read_text(encoding="utf-8"))
            trace = reference_run.run_reference((directory / "reference.st").read_text(encoding="utf-8"), stimulus, container)
            scan_ms = stimulus["scan_ms"]
            rows = [{"t_ms": index * scan_ms, **row} for index, row in enumerate(model(stimulus["scans"], scan_ms))]
            mine = {"source": "forte", "scan_ms": scan_ms, "outputs": trace["outputs"], "scans": rows}
            report = compare.compare_traces(trace, mine)
            print(f"{key}: scans {report['scans_compared']} equal {report['equal']} divergences {report['divergences']} first {report['first_divergence']} shape {report.get('shape_errors')}")
            failed = failed or not report["equal"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
