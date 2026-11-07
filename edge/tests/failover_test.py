#!/usr/bin/env python3
"""Failover, fencing and migration measurements on the running stack. Everything is simulated on one PC.

    python3 tests/failover_test.py --reps 30                 # both watchdog modes, then all other experiments
    python3 tests/failover_test.py --reps 3 --out smoke.json # quick version

Experiments:
  takeover     docker kill the active controller; the standby takes over. Repeated in two I/O configurations:
               hold-last (watchdog longer than recovery) and safe-first (watchdog shorter than the lease).
  zombie       docker pause the active, let the standby take over, unpause: the old node's writes must be refused.
  partition    disconnect the active from the OT network, then reconnect.
  split_brain  force the standby's gate open with a stale token while the active runs.
  stale_write  direct Modbus writes with wrong tokens from this script.
  state        a latched pump failure survives takeover; what a takeover does to a running proof timer.
  migration    planned move of the logic to an empty node, I/O wiring untouched.

Timings come from the remote I/O event log and the plant trace. Same clock, CLOCK_MONOTONIC, for all.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stack  # noqa: E402
from stack import agent, compose, container, docker, io_config, io_events, io_state, plant_fault, plant_state, plant_trace, read_control, wait_until  # noqa: E402

MS = 1e-6
SETTLE_S = 3.0
PUMPS_RUNNING = {3, 4}


def contenders() -> list[int]:
    return [1, 2]


def wait_healthy_pair(active_expected: int | None = None, timeout: float = 15.0) -> tuple[int, int]:
    """Wait for one ACTIVE node and a ready standby. Returns (active, standby)."""

    def check():
        holder = io_state()["holder"]
        if holder not in contenders() or not stack.controlling():
            return None
        other = 3 - holder
        return (holder, other) if stack.node_ready(other) else None

    return wait_until(check, timeout, period=0.1, what="active and ready standby")


def check_no_dual_drive(events: list[dict]) -> dict:
    """The core invariant, from the I/O's own log: accepted control writes have a non-decreasing epoch,
    and once an epoch is granted no write of an older epoch is ever accepted."""
    violations = []
    current = None
    granted = None
    for event in events:
        if event["kind"] == "grant":
            granted = event["epoch"]
        elif event["kind"] == "accept":
            if current is not None and event["epoch"] < current:
                violations.append(event)
            if granted is not None and event["epoch"] != granted:
                violations.append(event)
            current = event["epoch"]
    return {"accepted_writes": sum(e["kind"] == "accept" for e in events),
            "rejected_writes": sum(e["kind"] == "reject" for e in events),
            "violations": len(violations)}


def analyse_takeover(events: list[dict], t_kill: int, old_epoch: int, trace: list[dict], pre: dict) -> dict:
    grant = next(e for e in events if e["kind"] == "grant" and e["t_ns"] > t_kill - 2_000_000_000 and e["epoch"] > old_epoch)
    first_new = next(e for e in events if e["kind"] == "accept" and e["epoch"] == grant["epoch"])
    old_accepts = [e for e in events if e["kind"] == "accept" and e["epoch"] == old_epoch]
    last_old = old_accepts[-1] if old_accepts else None
    wd = [e for e in events if e["kind"] == "wd_trip" and e["t_ns"] >= t_kill]
    window = [r for r in trace if r["t_ns"] >= t_kill]
    level_at_kill = window[0]["level"] if window else None
    # Time with a pump command removed that was present before the kill.
    before = (bool(pre["PUMP_1"]), bool(pre["PUMP_2"]))
    dropped_ms = 0.0
    for prev, row in zip(window, window[1:]):
        if (before[0] and not row["cmd1"]) or (before[1] and not row["cmd2"]):
            if row["t_ns"] <= first_new["t_ns"] + 200_000_000:
                dropped_ms += (row["t_ns"] - prev["t_ns"]) * MS
    return {
        "t_kill_ns": t_kill,
        "pumps_on_at_kill": sum(before),
        "state_at_kill": pre["STATE_NO"],
        "recovery_from_kill_ms": round((first_new["t_ns"] - t_kill) * MS, 2),
        "control_gap_ms": round((first_new["t_ns"] - last_old["t_ns"]) * MS, 2) if last_old else None,
        "detection_ms": round((grant["t_ns"] - last_old["t_ns"]) * MS, 2) if last_old else None,
        "activation_ms": round((first_new["t_ns"] - grant["t_ns"]) * MS, 2),
        "watchdog_tripped": bool(wd),
        "safe_before_new_write": bool(wd) and wd[0]["t_ns"] < first_new["t_ns"],
        "command_dropped_ms": round(dropped_ms, 1),
        "level_at_kill": level_at_kill,
        "max_rise_m": round(max(r["level"] for r in window) - level_at_kill, 4) if window else None,
        "max_level_m": max(r["level"] for r in window) if window else None,
        # How far a running pump coasted down during the takeover. The window ends well after recovery.
        "pump_speed_at_kill": round(max(window[0]["w1"] if before[0] else 0, window[0]["w2"] if before[1] else 0), 3) if window and any(before) else None,
        "pump_speed_drop": round(max(
            (window[0]["w1"] - min(r["w1"] for r in window)) if before[0] else 0,
            (window[0]["w2"] - min(r["w2"] for r in window)) if before[1] else 0), 4) if window and any(before) else None,
        "new_epoch": grant["epoch"],
        "bumpless_command": (first_new["pump1"], first_new["pump2"]) == (pre["PUMP_1"], pre["PUMP_2"]),
        "state_after_first_write": first_new["state"],
    }


def prepare_plant(rep: int, client) -> None:
    """Even reps kill during pumping, odd reps while waiting, so both cases are covered equally."""
    if rep % 2 == 0:
        if read_control(client)["STATE_NO"] not in PUMPS_RUNNING:
            stack.to_waiting(client)
            stack.plant_config(level=3.3)
            wait_until(lambda: read_control(client)["STATE_NO"] in PUMPS_RUNNING, 20, 0.05, "pump running")
            time.sleep(6.0)  # Four spin-up time constants, so a speed drop is visible as a drop.
    else:
        stack.to_waiting(client, level=1.0)
        stack.plant_config(level=1.5)
        time.sleep(0.3)


def takeover_once(rep: int) -> dict:
    client = stack.modbus()
    prepare_plant(rep, client)
    active, standby = wait_healthy_pair()
    name = stack.NODES[active][0]
    seq = io_state()["last"]
    pre = read_control(client)
    old_epoch = pre["TOKEN"]
    trace_from = time.monotonic_ns()
    t_kill = time.monotonic_ns()
    docker("kill", "--signal", "KILL", container(name))
    t_killed = time.monotonic_ns()

    def new_writer():
        state = io_state()
        return state if state["holder"] == standby and read_control(client).get("TOKEN") == state["epoch"] else None

    wait_until(new_writer, 10, period=0.02, what=f"node {standby} to control")
    time.sleep(SETTLE_S)  # Long enough to see the plant's response.
    events = io_events(seq)
    trace = plant_trace(trace_from)
    post = read_control(client)
    result = analyse_takeover(events, t_kill, old_epoch, trace, pre)
    status = agent(standby, "/status")
    result.update(
        rep=rep, from_node=active, to_node=standby,
        docker_kill_ms=round((t_killed - t_kill) * MS, 1),
        agent_breakdown=status["last_takeover"],
        dual_drive=check_no_dual_drive(events),
        state_before={k: pre[k] for k in ("STATE_NO", "LEAD_IS_2", "TOTAL", "PULSES", "STARTS", "FILTERED_LEVEL")},
        state_after={k: post[k] for k in ("STATE_NO", "LEAD_IS_2", "TOTAL", "PULSES", "STARTS", "FILTERED_LEVEL")},
        total_continuous=post["TOTAL"] >= pre["TOTAL"] - 1e-3,
        pulses_continuous=post["PULSES"] >= pre["PULSES"],
        starts_continuous=post["STARTS"] >= pre["STARTS"],
        high_alarm_seen=bool(post["HIGH_ALARM"]),
    )
    docker("start", container(name))
    return result


def run_takeovers(reps: int, wd_timeout_ms: int, lease_ttl_ms: int, label: str) -> dict:
    io_config(wd_timeout_ms=wd_timeout_ms, lease_ttl_ms=lease_ttl_ms)
    stack.plant_config(reset_max=True)
    max_before = plant_state()["max_level"]
    runs = []
    for rep in range(reps):
        result = takeover_once(rep)
        runs.append(result)
        print(f"  {label} {rep + 1}/{reps}: recovery {result['recovery_from_kill_ms']:.0f} ms, gap {result['control_gap_ms']} ms, "
              f"pumps {result['pumps_on_at_kill']}, wd {result['watchdog_tripped']}, rise {result['max_rise_m']} m", flush=True)
    running = [r for r in runs if r["pumps_on_at_kill"] > 0]
    plant = plant_state()
    return {
        "label": label,
        "wd_timeout_ms": wd_timeout_ms,
        "lease_ttl_ms": lease_ttl_ms,
        "reps": reps,
        "recovery_from_kill_ms": stack.stats([r["recovery_from_kill_ms"] for r in runs]),
        "control_gap_ms": stack.stats([r["control_gap_ms"] for r in runs if r["control_gap_ms"] is not None]),
        "detection_ms": stack.stats([r["detection_ms"] for r in runs if r["detection_ms"] is not None]),
        "activation_ms": stack.stats([r["activation_ms"] for r in runs]),
        "docker_kill_ms": stack.stats([r["docker_kill_ms"] for r in runs]),
        "reps_with_pumps_running": len(running),
        "max_rise_all_m": stack.stats([r["max_rise_m"] for r in runs if r["max_rise_m"] is not None]),
        "max_rise_pumps_running_m": stack.stats([r["max_rise_m"] for r in running if r["max_rise_m"] is not None]),
        "pump_speed_drop": stack.stats([r["pump_speed_drop"] for r in running]),
        "command_dropped_ms_pumps_running": stack.stats([r["command_dropped_ms"] for r in running]),
        "bumpless_reps_pumps_running": sum(r["bumpless_command"] for r in running),
        "state_held_reps_pumps_running": sum(r["state_after_first_write"] == r["state_at_kill"] for r in running),
        "watchdog_trips": sum(r["watchdog_tripped"] for r in runs),
        "safe_before_new_write_reps": sum(r["safe_before_new_write"] for r in runs),
        "dual_drive_violations": sum(r["dual_drive"]["violations"] for r in runs),
        "state_continuity_failures": sum(not (r["total_continuous"] and r["pulses_continuous"] and r["starts_continuous"]) for r in runs),
        "max_level_m_over_run": plant["max_level"],
        "max_level_m_before_run": max_before,
        "overflowed": plant["overflowed"],
        "runs": runs,
    }


def zombie(reps: int) -> dict:
    """Freeze the active with SIGSTOP via docker pause. It thinks no time has passed when it wakes."""
    runs = []
    for rep in range(reps):
        active, standby = wait_healthy_pair()
        name = stack.NODES[active][0]
        seq = io_state()["last"]
        old_epoch = read_control()["TOKEN"]
        docker("pause", container(name))
        wait_until(lambda: io_state()["holder"] == standby, 10, 0.02, "standby to take over")
        time.sleep(1.0)
        t_unpause = time.monotonic_ns()
        docker("unpause", container(name))
        wait_until(lambda: agent(active, "/status")["state"] == "SHADOW", 10, 0.02, "zombie to demote")
        t_demoted = time.monotonic_ns()
        time.sleep(1.0)
        events = io_events(seq)
        stale = [e for e in events if e["kind"] == "reject" and e["t_ns"] >= t_unpause and e["token"] == old_epoch]
        accepted_stale = [e for e in events if e["kind"] == "accept" and e["epoch"] == old_epoch and e["t_ns"] >= t_unpause]
        runs.append({
            "rep": rep, "old_epoch": old_epoch,
            "stale_writes_refused": len(stale),
            "stale_writes_accepted": len(accepted_stale),
            "demote_ms": round((t_demoted - t_unpause) * MS, 1),
            "dual_drive": check_no_dual_drive(events),
        })
        print(f"  zombie {rep + 1}/{reps}: refused {len(stale)}, accepted {len(accepted_stale)}", flush=True)
    return {"reps": reps, "stale_accepted_total": sum(r["stale_writes_accepted"] for r in runs),
            "stale_refused_total": sum(r["stale_writes_refused"] for r in runs),
            "violations": sum(r["dual_drive"]["violations"] for r in runs),
            "demote_ms": stack.stats([r["demote_ms"] for r in runs]), "runs": runs}


def partition(reps: int) -> dict:
    """Cut only the active node off the OT network. It keeps running, blind, and must not regain control."""
    runs = []
    for rep in range(reps):
        active, standby = wait_healthy_pair()
        name = stack.NODES[active][0]
        seq = io_state()["last"]
        old_epoch = read_control()["TOKEN"]
        t_cut = time.monotonic_ns()
        docker("network", "disconnect", "--force", stack.OT_NET, container(name))
        try:
            wait_until(lambda: io_state()["holder"] == standby and read_control().get("TOKEN") == io_state()["epoch"], 10, 0.02, "standby to take over")
            t_taken = time.monotonic_ns()
            time.sleep(1.0)
        finally:
            docker("network", "connect", "--ip", stack.IPS[name], stack.OT_NET, container(name))
        t_back = time.monotonic_ns()
        wait_until(lambda: stack.node_ready(active), 20, 0.1, "old node back to ready standby")
        t_ready = time.monotonic_ns()
        time.sleep(1.0)
        events = io_events(seq)
        accepted_stale = [e for e in events if e["kind"] == "accept" and e["epoch"] == old_epoch and e["t_ns"] >= t_taken]
        runs.append({
            "rep": rep,
            "takeover_ms": round((t_taken - t_cut) * MS, 1),
            "rejoin_ms": round((t_ready - t_back) * MS, 1),
            "stale_refused": sum(e["kind"] == "reject" and e["token"] == old_epoch for e in events),
            "stale_accepted": len(accepted_stale),
            "dual_drive": check_no_dual_drive(events),
        })
        print(f"  partition {rep + 1}/{reps}: {runs[-1]['takeover_ms']} ms, rejoin {runs[-1]['rejoin_ms']} ms", flush=True)
    return {"reps": reps, "takeover_ms": stack.stats([r["takeover_ms"] for r in runs]),
            "rejoin_ms": stack.stats([r["rejoin_ms"] for r in runs]),
            "stale_accepted_total": sum(r["stale_accepted"] for r in runs),
            "violations": sum(r["dual_drive"]["violations"] for r in runs), "runs": runs}


def split_brain(seconds: float = 3.0) -> dict:
    """The agent's gate is one barrier, fencing is the next. Bypass the first and watch the second hold."""
    active, standby = wait_healthy_pair()
    token = read_control()["TOKEN"]
    stale = (token - 1) & 0xFFFF
    seq = io_state()["last"]
    t0 = time.monotonic_ns()
    agent(standby, "/test/force_gate", {"token": stale, "open": True})
    time.sleep(seconds)
    agent(standby, "/test/force_gate", {"token": 0, "open": False})
    events = [e for e in io_events(seq) if e["t_ns"] >= t0]
    refused = [e for e in events if e["kind"] == "reject" and e["token"] == stale]
    accepted = [e for e in events if e["kind"] == "accept"]
    return {
        "seconds_both_writing": seconds,
        "forced_token": stale,
        "standby_writes_refused": len(refused),
        "standby_writes_accepted": sum(e["epoch"] == stale for e in accepted),
        "active_writes_accepted": sum(e["epoch"] == token for e in accepted),
        "violations": check_no_dual_drive(events)["violations"],
    }


def stale_write() -> dict:
    """Direct writes with wrong tokens, from a client that is not a controller."""
    from common import mbtcp

    client = stack.modbus()
    token = read_control(client)["TOKEN"]
    base, count = stack.regmap.span(stack.regmap.group("control"))
    results = {}
    for name, bad in (("old", (token - 1) & 0xFFFF), ("future", (token + 1) & 0xFFFF), ("zero", 0)):
        before = io_state()["outputs"]
        words = [bad, int(not before[0]), int(not before[1])] + [0] * (count - 3)
        try:
            client.write_registers(base, words)
            results[name] = "ACCEPTED"
        except mbtcp.ModbusException as exc:
            results[name] = f"refused with exception {exc.code}"
    return results


def state_transfer() -> dict:
    """Latched state that the FB has no output pin for, and timers, which are not transferred."""
    out = {}
    # A pump failure latch must survive. Trip pump 1, clear the trip, take over, look at the new controller.
    active, standby = wait_healthy_pair()
    plant_fault(trip_1=True)
    wait_until(lambda: agent(active, "/status")["scan"]["SUP.FAILED_1_Q1"] == "TRUE", 5, 0.05, "failure latch")
    plant_fault(trip_1=False)
    time.sleep(0.6)  # At least two checkpoint periods.
    docker("kill", "--signal", "KILL", container(stack.NODES[active][0]))
    wait_until(lambda: io_state()["holder"] == standby and stack.controlling(), 10, 0.02, "takeover")
    time.sleep(0.3)
    status = agent(standby, "/status")
    out["failed_latch_after_takeover"] = status["scan"]["SUP.FAILED_1_Q1"]
    out["state_loaded"] = status["last_takeover"]["state_loaded"]
    client = stack.modbus()
    client.write_coil(0, True)
    wait_until(lambda: agent(standby, "/status")["scan"]["SUP.FAILED_1_Q1"] == "FALSE", 5, 0.05, "ack to clear the latch")
    out["ack_clears_latch"] = True
    docker("start", container(stack.NODES[active][0]))

    # A running proof timer restarts. Make the lead fail to prove, kill the controller partway through.
    proof_runs = []
    for kill_after in (None, 1.5):
        active, standby = wait_healthy_pair()
        stack.to_waiting(client)
        lead2 = bool(read_control(client)["LEAD_IS_2"])
        pump = 2 if lead2 else 1
        plant_fault(**{f"pump_fail_{pump}": True})
        stack.plant_config(level=3.5)
        wait_until(lambda: read_control(client)["STATE_NO"] == 2, 15, 0.01, "lead starting")
        t_state2 = time.monotonic()
        controller = active
        if kill_after is not None:
            time.sleep(kill_after)
            docker("kill", "--signal", "KILL", container(stack.NODES[active][0]))
            controller = standby
        # The latch is internal. It shows as the supervisor leaving state 2 or rotating the lead.
        wait_until(lambda: agent(controller, "/status")["scan"][f"SUP.FAILED_{pump}_Q1"] == "TRUE", 20, 0.02, "proof failure")
        proof_runs.append({"killed_after_s": kill_after, "time_to_proof_failure_s": round(time.monotonic() - t_state2, 2)})
        plant_fault(**{f"pump_fail_{pump}": False})
        client.write_coil(0, True)
        stack.plant_config(level=1.0)
        if kill_after is not None:
            docker("start", container(stack.NODES[active][0]))
        time.sleep(1.0)
    out["proof_timer"] = proof_runs
    return out


def migrate_once(rep: int, source: int, target: int) -> dict:
    """Hand the logic from source to an empty node. Nothing about the I/O or the wiring changes."""
    prepare_plant(rep, stack.modbus())
    seq = io_state()["last"]
    pre = read_control()
    old_epoch = pre["TOKEN"]
    deployed = agent(target, "/deploy", {"contend": True})
    t_deployed = time.monotonic()
    wait_until(lambda: stack.node_ready(target), 15, 0.02, "target shadow healthy")
    warm_s = time.monotonic() - t_deployed
    t_handover = time.monotonic_ns()
    handover = agent(source, "/handover", {"to": target})
    wait_until(lambda: io_state()["holder"] == target and read_control().get("TOKEN") == io_state()["epoch"], 10, 0.01, "target to control")
    time.sleep(1.0)
    events = io_events(seq)
    post = read_control()
    undeploy = agent(source, "/undeploy", {})
    grant = next(e for e in events if e["kind"] == "grant" and e["epoch"] > old_epoch)
    first_new = next(e for e in events if e["kind"] == "accept" and e["epoch"] == grant["epoch"])
    last_old = [e for e in events if e["kind"] == "accept" and e["epoch"] == old_epoch][-1]
    falls = [e for e in events if e["kind"] == "output" and last_old["t_ns"] <= e["t_ns"] <= first_new["t_ns"]]
    return {
        "rep": rep, "from_node": source, "to_node": target,
        "pumps_on": pre["PUMP_1"] + pre["PUMP_2"],
        "bumpless_command": (first_new["pump1"], first_new["pump2"]) == (pre["PUMP_1"], pre["PUMP_2"]),
        "deploy_ms": round(deployed["deploy_ms"], 2),
        "shadow_warm_s": round(warm_s, 3),
        "handover_ms": handover.get("handover_ms"),
        "write_gap_ms": round((first_new["t_ns"] - last_old["t_ns"]) * MS, 2),
        "handover_to_first_write_ms": round((first_new["t_ns"] - t_handover) * MS, 2),
        "output_change_in_gap": len(falls),
        "watchdog_trips": sum(e["kind"] == "wd_trip" for e in events),
        "grant_to": grant["node"],
        "digest_source": agent(source, "/status")["app_digest"],
        "digest_target": agent(target, "/status")["app_digest"],
        "total_before": pre["TOTAL"], "total_after": post["TOTAL"],
        "total_continuous": post["TOTAL"] >= pre["TOTAL"] - 1e-3,
        "pulses_continuous": post["PULSES"] >= pre["PULSES"],
        "starts_continuous": post["STARTS"] >= pre["STARTS"],
        "lead_before": pre["LEAD_IS_2"], "lead_after": post["LEAD_IS_2"],
        "undeploy_ms": undeploy.get("undeploy_ms"),
        "dual_drive": check_no_dual_drive(events),
    }


def migration(reps: int) -> dict:
    """Between ctrl-a's or ctrl-b's position and the empty ctrl-c, with the other contender still contending."""
    io_config(wd_timeout_ms=1000, lease_ttl_ms=300)
    source, _ = wait_healthy_pair()
    target = 3
    runs = []
    for rep in range(reps):
        result = migrate_once(rep, source, target)
        runs.append(result)
        print(f"  migration {rep + 1}/{reps}: {source}->{target} gap {result['write_gap_ms']} ms, deploy {result['deploy_ms']} ms, "
              f"warm {result['shadow_warm_s']} s, pumps {result['pumps_on']}, wd {result['watchdog_trips']}", flush=True)
        source, target = target, source
    return {
        "reps": reps,
        "deploy_ms": stack.stats([r["deploy_ms"] for r in runs]),
        "shadow_warm_s": stack.stats([r["shadow_warm_s"] for r in runs]),
        "write_gap_ms": stack.stats([r["write_gap_ms"] for r in runs]),
        "handover_to_first_write_ms": stack.stats([r["handover_to_first_write_ms"] for r in runs]),
        "output_changes_in_gap": sum(r["output_change_in_gap"] for r in runs),
        "reps_with_pumps_running": sum(r["pumps_on"] > 0 for r in runs),
        "bumpless_reps": sum(r["bumpless_command"] for r in runs),
        "watchdog_trips": sum(r["watchdog_trips"] for r in runs),
        "wrong_node_granted": sum(r["grant_to"] != r["to_node"] for r in runs),
        "digests": sorted({r["digest_source"] for r in runs} | {r["digest_target"] for r in runs}),
        "state_continuity_failures": sum(not (r["total_continuous"] and r["pulses_continuous"] and r["starts_continuous"]) for r in runs),
        "violations": sum(r["dual_drive"]["violations"] for r in runs),
        "runs": runs,
    }


def restore_after_migration() -> None:
    """Back to ctrl-a and ctrl-b contending, ctrl-c bare."""
    compose("up", "-d", "--no-build", "--force-recreate", "ctrl-a", "ctrl-b", "ctrl-c")
    wait_until(stack.controlling, 30, what="control after recreate")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reps", type=int, default=30)
    parser.add_argument("--out", default="failover.json")
    parser.add_argument("--only", help="comma-separated: hold,safe,zombie,partition,split,stale,state,migration")
    args = parser.parse_args()
    chosen = set(args.only.split(",")) if args.only else {"hold", "safe", "zombie", "partition", "split", "stale", "state", "migration"}
    target = stack.RESULTS / args.out
    # A partial run updates its own sections of an existing result file.
    out: dict = json.loads(target.read_text()) if args.only and target.exists() else {}
    out["reps_requested"] = args.reps
    stack.ensure_core_up()
    # Keep the plant cycling at a known rate through the experiments.
    stack.plant_config(base_inflow=90.0, swing=10.0)
    load_before = stack.loadavg()
    try:
        if "hold" in chosen:
            print("takeover, hold-last: watchdog 1000 ms, lease 300 ms", flush=True)
            out["takeover_hold_last"] = run_takeovers(args.reps, 1000, 300, "hold")
        if "safe" in chosen:
            print("takeover, safe-first: watchdog 200 ms, lease 300 ms", flush=True)
            out["takeover_safe_first"] = run_takeovers(args.reps, 200, 300, "safe")
            io_config(wd_timeout_ms=1000, lease_ttl_ms=300)
        if "zombie" in chosen:
            print("zombie", flush=True)
            out["zombie"] = zombie(max(3, args.reps // 6))
        if "partition" in chosen:
            print("partition", flush=True)
            out["partition"] = partition(max(3, args.reps // 10))
        if "split" in chosen:
            print("split brain", flush=True)
            out["split_brain"] = split_brain()
        if "stale" in chosen:
            print("stale writes", flush=True)
            out["stale_write"] = stale_write()
        if "state" in chosen:
            print("state transfer", flush=True)
            out["state_transfer"] = state_transfer()
        if "migration" in chosen:
            print("migration", flush=True)
            out["migration"] = migration(args.reps)
            restore_after_migration()
    finally:
        io_config(wd_timeout_ms=1000, lease_ttl_ms=300)
        plant_fault(trip_1=False, trip_2=False, pump_fail_1=False, pump_fail_2=False, sensor_stuck=False)
    out["loadavg_before"], out["loadavg_after"] = load_before, stack.loadavg()
    path = stack.write_result(args.out, out)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
