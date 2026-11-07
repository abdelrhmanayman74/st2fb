#!/usr/bin/env python3
"""Measure the real cycle on real FORTE, on a kernel that is not real-time.

    python3 tests/jitter_test.py --seconds 120

Two measuring points:
  inside FORTE   SCAN_PROBE timestamps each E_CYCLE event with CLOCK_MONOTONIC (nanosecond resolution, written to a
                 file on tmpfs). This is the event's start of service, not the kernel timer's expiry.
  at the I/O     arrival time of each control write in the Python server. Adds TCP, scheduling, Python.

Conditions: baseline (whatever else the host is doing, load recorded), CPU load (12 busy processes in a container),
and optionally SCHED_FIFO for FORTE with the same CPU load.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stack  # noqa: E402

NOMINAL_US = 100_000.0
STRESS_NAME = "st2fb-jitter-stress"
STRESS_IMAGE = "python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54"


def percentile(ordered: list[float], fraction: float) -> float:
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


def describe(deltas_us: list[float]) -> dict:
    ordered = sorted(deltas_us)
    deviations = sorted(abs(d - NOMINAL_US) for d in deltas_us)
    return {
        "n": len(deltas_us),
        "mean_us": round(statistics.fmean(deltas_us), 1),
        "stdev_us": round(statistics.pstdev(deltas_us), 1),
        "min_us": round(ordered[0], 1),
        "max_us": round(ordered[-1], 1),
        "abs_jitter_median_us": round(percentile(deviations, 0.5), 1),
        "abs_jitter_p95_us": round(percentile(deviations, 0.95), 1),
        "abs_jitter_p99_us": round(percentile(deviations, 0.99), 1),
        "abs_jitter_max_us": round(deviations[-1], 1),
        "over_110ms": sum(d > 110_000 for d in deltas_us),
        "over_150ms": sum(d > 150_000 for d in deltas_us),
    }


def scheduling_policies(service: str) -> list[str]:
    """Scheduling policy of every FORTE thread, as the kernel reports it."""
    script = ('pid=$(for p in /proc/[0-9]*; do [ "$(cat $p/comm 2>/dev/null)" = forte ] && echo ${p##*/}; done | head -1); '
              'for t in /proc/$pid/task/*; do chrt -p ${t##*/} | head -1 | sed "s/.*: //"; done | sort | uniq -c')
    return stack.docker("exec", stack.container(service), "sh", "-c", script).stdout.split("\n")[:-1]


def measure(seconds: float, label: str) -> dict:
    holder = stack.io_state()["holder"]
    service = stack.NODES[holder][0]
    policies = scheduling_policies(service)
    t_start = time.monotonic_ns()
    seq = stack.io_state()["last"]
    load_before = stack.loadavg()
    time.sleep(seconds)
    load_after = stack.loadavg()
    t_end = time.monotonic_ns()
    rows = [r for r in stack.scan_log(service) if t_start <= r[0] <= t_end]
    times = [r[0] for r in rows]
    deltas = [(b - a) / 1000.0 for a, b in zip(times, times[1:])]
    exec_us = sorted(r[1] for r in rows if r[1] > 0)
    arrivals = [e["t_ns"] for e in stack.io_events(seq) if e["kind"] == "accept"]
    arrival_deltas = [(b - a) / 1000.0 for a, b in zip(arrivals, arrivals[1:])]
    # Drift: what the FB's virtual clock (scan count times SCAN_DT) says, against the real elapsed time.
    elapsed_s = (times[-1] - times[0]) * 1e-9
    virtual_s = len(deltas) * NOMINAL_US * 1e-6
    return {
        "label": label,
        "seconds": seconds,
        "node": service,
        "forte_thread_policies": policies,
        "loadavg_before": load_before,
        "loadavg_after": load_after,
        "inside_forte": describe(deltas),
        "at_remote_io": describe(arrival_deltas),
        "scan_work_us": {
            "median": percentile(exec_us, 0.5) if exec_us else None,
            "p99": percentile(exec_us, 0.99) if exec_us else None,
            "max": exec_us[-1] if exec_us else None,
        },
        "virtual_clock_s": round(virtual_s, 3),
        "real_clock_s": round(elapsed_s, 3),
        "virtual_minus_real_ms": round((virtual_s - elapsed_s) * 1000, 2),
        "wd_trips": sum(e["kind"] == "wd_trip" for e in stack.io_events(seq)),
        "grants": sum(e["kind"] == "grant" for e in stack.io_events(seq)),
    }


def start_stress() -> None:
    code = "import multiprocessing as m,itertools\n\ndef f():\n    for _ in itertools.count(): pass\n\nps=[m.Process(target=f) for _ in range(12)]\n[p.start() for p in ps]\n[p.join() for p in ps]\n"
    stack.docker("rm", "-f", STRESS_NAME, check=False)
    stack.docker("run", "-d", "--rm", "--name", STRESS_NAME, "--network", "none", STRESS_IMAGE, "python3", "-c", code)


def stop_stress() -> None:
    stack.docker("rm", "-f", STRESS_NAME, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--out", default="jitter.json")
    parser.add_argument("--skip-fifo", action="store_true")
    args = parser.parse_args()
    results = []
    stack.ensure_core_up()
    print("baseline", flush=True)
    results.append(measure(args.seconds, "baseline"))
    print(results[-1]["inside_forte"], flush=True)
    start_stress()
    try:
        time.sleep(3)
        print("cpu load", flush=True)
        results.append(measure(args.seconds, "cpu_load_12_procs"))
        print(results[-1]["inside_forte"], flush=True)
    finally:
        stop_stress()
    fifo_note = "not run"
    if not args.skip_fifo:
        env = {"FORTE_RT": "1"}
        compose_fifo = stack.compose("-f", str(stack.EDGE / "compose.yaml"), "-f", str(stack.EDGE / "tests/compose.fifo.yaml"),
                                     "up", "-d", "--no-build", "--force-recreate", "ctrl-a", "ctrl-b", env=env, check=False)
        if compose_fifo.returncode != 0:
            fifo_note = f"compose failed: {compose_fifo.stderr[-300:]}"
        else:
            stack.wait_until(stack.controlling, 30, what="control under FIFO")
            time.sleep(3)
            start_stress()
            try:
                time.sleep(3)
                print("cpu load + SCHED_FIFO", flush=True)
                results.append(measure(args.seconds, "cpu_load_12_procs_sched_fifo"))
                print(results[-1]["inside_forte"], flush=True)
                fifo_note = "run"
            finally:
                stop_stress()
                stack.compose("up", "-d", "--no-build", "--force-recreate", "ctrl-a", "ctrl-b")
                stack.wait_until(stack.controlling, 30, what="control after FIFO")
    path = stack.write_result(args.out, {"nominal_cycle_us": NOMINAL_US, "fifo": fifo_note, "conditions": results})
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
