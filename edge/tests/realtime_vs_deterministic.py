#!/usr/bin/env python3
"""Same stimulus through the deterministic test path and through the real-time path, then compare outputs.

  deterministic  st2fb.forte_run: one request frame per scan, block for the reply. No wall clock. Each scan sees
                 exactly its inputs. (Computed by the repo's pipeline on real FORTE, in the base image.)
  real time      the edge application on E_CYCLE, 100 ms. A player replays the same inputs into the simulated I/O
                 every 100 ms of wall time. Modbus polling and the scan sample them asynchronously.

The stimulus is corpus/20_pump_station_supervisor/stimulus.json with PULSE_SIZE held at 1.0, because PULSE_SIZE is
an app parameter on the edge. PROOF_TIME, ALARM_DELAY and SCAN_HOURS are set to the stimulus values.
Reference: tests/replay_player.py sends the inputs. Output: results/realtime_vs_deterministic.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stack  # noqa: E402

REPO = stack.EDGE.parent
STIMULUS = REPO / "corpus/20_pump_station_supervisor/stimulus.json"
SIGNALS = {"STATE_NO": "state", "PUMP_1": "pump1", "PUMP_2": "pump2", "LEAD_IS_2": "lead2", "HIGH_ALARM": "high", "STATION_FAULT": "fault"}
PLAYER = "st2fb-replay-player"
OVERRIDES = {"SUP.PROOF_TIME": "T#1s", "SUP.ALARM_DELAY": "T#2s", "SUP.SCAN_HOURS": "0.0078125", "SUP.PULSE_SIZE": "1.0",
             "GUARD.STUCK_TIME": "T#1h"}


def deterministic_trace(work: Path, stimulus_path: Path) -> list[dict]:
    fbt = work / "sup.fbt"
    out = work / "forte.json"
    for args in (["st2fb.translate", str(REPO / "corpus/20_pump_station_supervisor/program.st"), "--out", str(fbt)],
                 ["st2fb.forte_run", "--fbt", str(fbt), "--stimulus", str(stimulus_path), "--out", str(out)]):
        result = subprocess.run([sys.executable, "-m", *args], cwd=REPO, capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(result.stderr)
    return json.loads(out.read_text())["scans"]


def as_int(value) -> int:
    return int(value) if isinstance(value, (bool, int)) else value


def transitions(values: list[int]) -> list[tuple[int, int]]:
    """(scan index, new value) for every change."""
    return [(i, v) for i, (p, v) in enumerate(zip(values, values[1:]), start=1) if p != v]


def run_real_time(work: Path, reference: list[dict], scans: list[dict], scan_ms: int, phase_ms: int) -> dict:
    """One replay with the player's start shifted by phase_ms against the controller's cycle."""
    env = {"APP_OVERRIDES": json.dumps(OVERRIDES)}
    stack.compose("stop", "-t", "1", "plant", "ctrl-a", "ctrl-b", "ctrl-c", "gateway", "api", "tsdb", "mosquitto", check=False)
    stack.compose("up", "-d", "--no-build", "--no-deps", "--force-recreate", "remote-io", "ctrl-a", env=env)
    stack.docker("rm", "-f", PLAYER, check=False)
    try:
        player = subprocess.Popen(
            ["docker", "run", "--rm", "--name", PLAYER, "--network", f"{stack.PROJECT}_field", "--ip", "172.30.1.10",
             "-v", f"{work}:/work:ro", "-v", f"{Path(__file__).resolve().parent / 'replay_player.py'}:/replay_player.py:ro",
             "st2fb-edge-sim:1", "python3", "-B", "-u", "/replay_player.py", "/work/stimulus.json", str(phase_ms)],
            stdout=subprocess.PIPE, text=True,
        )
        # The player arms first, holding the first scan's inputs until the controller is writing.
        stack.wait_until(stack.controlling, 40, what="controller to take the lease")
        seq0 = stack.io_state()["last"]
        for line in player.stdout:
            print(" ", line.strip(), flush=True)
            if line.startswith("done"):
                t_info = json.loads(line.split(" ", 1)[1])
                break
        player.wait(timeout=20)
        time.sleep(0.5)
        accepts = [e for e in stack.io_events(seq0) if e["kind"] == "accept" and e["t_ns"] >= t_info["t_start_ns"]]
        final = stack.read_control()
    finally:
        stack.docker("rm", "-f", PLAYER, check=False)

    # One real-time sample per stimulus scan: the last write at or before the end of that scan's slot.
    t0 = t_info["t_start_ns"]
    period = scan_ms * 1_000_000
    per_slot: list[dict | None] = [None] * len(scans)
    index = 0
    for slot in range(len(scans)):
        end = t0 + (slot + 1) * period
        while index < len(accepts) and accepts[index]["t_ns"] <= end:
            per_slot[slot] = accepts[index]
            index += 1
        if per_slot[slot] is None and slot > 0:
            per_slot[slot] = per_slot[slot - 1]

    def mismatches(lag: int) -> dict:
        counts = {k: 0 for k in SIGNALS}
        compared = 0
        for i, ref in enumerate(reference):
            j = i + lag
            if j >= len(per_slot) or per_slot[j] is None:
                continue
            compared += 1
            for ref_name, rt_name in SIGNALS.items():
                if as_int(ref[ref_name]) != per_slot[j][rt_name]:
                    counts[ref_name] += 1
        return {"lag_scans": lag, "compared": compared, "mismatched_by_signal": counts, "mismatched_scans_total": sum(counts.values())}

    sweep = [mismatches(lag) for lag in range(0, 4)]
    best = min(sweep, key=lambda s: s["mismatched_scans_total"])

    # Event level: do the same state changes happen in the same order, and how late are they?
    ref_states = [as_int(r["STATE_NO"]) for r in reference]
    rt_states = [p["state"] if p else None for p in per_slot]
    ref_changes = transitions(ref_states)
    rt_changes = [(i, v) for i, v in transitions(rt_states) if v is not None]
    lags = []
    cursor = 0
    unmatched = []
    for scan, value in ref_changes:
        found = None
        for k in range(cursor, len(rt_changes)):
            if rt_changes[k][1] == value and rt_changes[k][0] >= scan - 2:
                found = k
                break
        if found is None or rt_changes[found][0] - scan > 30:
            unmatched.append([scan, value])
            continue
        lags.append(rt_changes[found][0] - scan)
        cursor = found + 1
    last = reference[-1]
    return {
        "phase_ms": phase_ms,
        "real_time_writes": len(accepts),
        "player": t_info,
        "lag_sweep": sweep,
        "best_lag": best,
        "state_changes_deterministic": len(ref_changes),
        "state_changes_real_time": len(rt_changes),
        "same_state_sequence": [v for _, v in ref_changes] == [v for _, v in rt_changes],
        "state_change_lag_scans": stack.stats(lags),
        "state_changes_unmatched": unmatched,
        "final": {
            "deterministic": {"STARTS": as_int(last["STARTS"]), "PULSES": as_int(last["PULSES"]), "TOTAL": last["TOTAL"], "LEAD_IS_2": as_int(last["LEAD_IS_2"])},
            "real_time": {"STARTS": final["STARTS"], "PULSES": final["PULSES"], "TOTAL": final["TOTAL"], "LEAD_IS_2": final["LEAD_IS_2"]},
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="realtime_vs_deterministic.json")
    parser.add_argument("--max-scans", type=int, default=0, help="shorten for a smoke run")
    parser.add_argument("--phases", default="0,33,66", help="start offsets of the player against the cycle, in ms")
    args = parser.parse_args()

    stimulus = json.loads(STIMULUS.read_text())
    scans = stimulus["scans"][: args.max_scans] if args.max_scans else stimulus["scans"]
    for scan in scans:
        scan["PULSE_SIZE"] = 1.0
    work = stack.EDGE / ".venv" / "replay"
    work.mkdir(parents=True, exist_ok=True)
    stim_path = work / "stimulus.json"
    stim_path.write_text(json.dumps({"scan_ms": stimulus["scan_ms"], "scans": scans}))

    print("deterministic path", flush=True)
    reference = deterministic_trace(work, stim_path)

    print("real-time path: stack with the plant replaced by the player", flush=True)
    runs = []
    try:
        for phase in (int(p) for p in args.phases.split(",")):
            runs.append(run_real_time(work, reference, scans, stimulus["scan_ms"], phase))
            print(json.dumps({k: runs[-1][k] for k in ("phase_ms", "best_lag", "same_state_sequence", "state_change_lag_scans", "final")}), flush=True)
    finally:
        stack.compose("up", "-d", "--no-build", "--force-recreate", "plant", "remote-io", "ctrl-a", "ctrl-b", "ctrl-c", check=False)
        stack.compose("up", "-d", "--no-build", *stack.IT_SERVICES, check=False)
    path = stack.write_result(args.out, {"stimulus_scans": len(scans), "scan_ms": stimulus["scan_ms"], "runs": runs})
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
