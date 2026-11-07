#!/usr/bin/env python3
"""Print the markdown tables in docs/EDGE.md from results/*.json, so the document repeats only measured numbers."""
from __future__ import annotations

import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent.parent / "results"


def load(name: str) -> dict | None:
    path = RESULTS / name
    return json.loads(path.read_text()) if path.exists() else None


def row(cells) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def stat_row(label: str, s: dict, digits: int = 0) -> str:
    fmt = lambda v: f"{v:.{digits}f}"  # noqa: E731
    return row([label, s["n"], fmt(s["mean"]), fmt(s["median"]), fmt(s["p95"]), fmt(s["max"])])


def regmap_tables() -> None:
    data = json.loads((RESULTS.parent / "regmap.json").read_text())
    print("## regmap\n")
    print("Input registers (FC4)\n")
    print(row(["Addr", "Name", "Type", "Meaning"]))
    print(row(["---"] * 4))
    for r in data["input_registers"]:
        unit = f" ({r['unit']})" if r.get("unit") else ""
        print(row([r["addr"], f"`{r['name']}`", r["type"], r.get("desc", "") + unit]))
    print("\nCoils\n")
    print(row(["Addr", "Name", "Meaning"]))
    print(row(["---"] * 3))
    for r in data["coils"]:
        print(row([r["addr"], f"`{r['name']}`", r["desc"]]))
    print("\nHolding registers\n")
    print(row(["Addr", "Name", "Type", "Block", "Meaning"]))
    print(row(["---"] * 5))
    for r in data["holding_registers"]:
        extra = f"Default {r['default']}, range {r['min']} to {r['max']}" if "default" in r else r.get("desc", "")
        print(row([r["addr"], f"`{r['name']}`", r["type"], r["group"], extra]))
    print()


def main() -> None:
    regmap_tables()
    jitter = load("jitter.json")
    if jitter:
        print("## jitter\n")
        m = jitter["machine"]
        print(f"{m['date']}, {m['cpu']}, {m['cpus']} CPUs, kernel {m['kernel']}\n")
        print(row(["Condition", "Point", "Cycles", "Mean us", "Stdev us", "Min us", "Max us", "|jitter| median us", "p95 us", "p99 us", "max us", ">110 ms"]))
        print(row(["---"] * 12))
        for c in jitter["conditions"]:
            for point, key in (("inside FORTE", "inside_forte"), ("at I/O", "at_remote_io")):
                d = c[key]
                print(row([c["label"], point, d["n"], d["mean_us"], d["stdev_us"], d["min_us"], d["max_us"], d["abs_jitter_median_us"],
                           d["abs_jitter_p95_us"], d["abs_jitter_p99_us"], d["abs_jitter_max_us"], d["over_110ms"]]))
        print()
        for c in jitter["conditions"]:
            print(f"- {c['label']}: scan work median {c['scan_work_us']['median']} us, p99 {c['scan_work_us']['p99']} us, max {c['scan_work_us']['max']} us; "
                  f"virtual minus real clock {c['virtual_minus_real_ms']} ms over {c['real_clock_s']} s; load {c['loadavg_before'][0]} to {c['loadavg_after'][0]}; "
                  f"grants {c['grants']}, watchdog trips {c['wd_trips']}; FORTE threads {[p.strip() for p in c['forte_thread_policies']]}")
        print()

    failover = load("failover.json")
    if failover:
        print("## failover\n")
        m = failover["machine"]
        print(f"{m['date']}, load before {failover['loadavg_before']}, after {failover['loadavg_after']}\n")
        for key in ("takeover_hold_last", "takeover_safe_first"):
            run = failover[key]
            print(f"### {key}: watchdog {run['wd_timeout_ms']} ms, lease {run['lease_ttl_ms']} ms, {run['reps']} repetitions\n")
            print(row(["ms", "n", "mean", "median", "p95", "max"]))
            print(row(["---"] * 6))
            for label, name in (("Kill command to first new write", "recovery_from_kill_ms"), ("Last old write to first new write (control gap)", "control_gap_ms"),
                                ("Last old write to lease grant (detection)", "detection_ms"), ("Grant to first new write (activation)", "activation_ms"),
                                ("docker kill command itself", "docker_kill_ms")):
                print(stat_row(label, run[name]))
            print()
            print(f"- reps with pumps running at kill {run['reps_with_pumps_running']}; same pump command in first new write {run['bumpless_reps_pumps_running']}; state held {run['state_held_reps_pumps_running']}")
            print(f"- watchdog trips {run['watchdog_trips']}, outputs safe before first new write in {run['safe_before_new_write_reps']} reps")
            print(f"- max rise, all reps: {run['max_rise_all_m']}")
            print(f"- max rise, pumps running: {run['max_rise_pumps_running_m']}")
            print(f"- running pump speed drop (fraction of full speed): {run['pump_speed_drop']}; command dropped ms (pumps running): {run['command_dropped_ms_pumps_running']}")
            print(f"- max level over run {run['max_level_m_over_run']} m, overflow {run['overflowed']}")
            print(f"- dual-drive violations {run['dual_drive_violations']}, state continuity failures {run['state_continuity_failures']}")
            print()
        z = failover["zombie"]
        print(f"zombie: {z['reps']} reps, stale refused {z['stale_refused_total']}, stale accepted {z['stale_accepted_total']}, violations {z['violations']}, demote ms {z['demote_ms']}")
        p = failover["partition"]
        print(f"partition: {p['reps']} reps, takeover ms {p['takeover_ms']}, rejoin ms {p['rejoin_ms']}, stale accepted {p['stale_accepted_total']}, violations {p['violations']}")
        print(f"split brain: {failover['split_brain']}")
        print(f"stale write: {failover['stale_write']}")
        print(f"state: {failover['state_transfer']}")
        mig = failover["migration"]
        print(f"\n### migration: {mig['reps']} repetitions\n")
        print(row(["", "n", "mean", "median", "p95", "max"]))
        print(row(["---"] * 6))
        print(stat_row("Deploy application, ms", mig["deploy_ms"], 1))
        print(stat_row("Deploy to shadow healthy, s", mig["shadow_warm_s"], 2))
        print(stat_row("Handover request to first new write, ms", mig["handover_to_first_write_ms"], 1))
        print(stat_row("Gap between control writes, ms", mig["write_gap_ms"], 1))
        print(f"\n- pumps running reps {mig['reps_with_pumps_running']}, same command in first new write {mig['bumpless_reps']}/{mig['reps']}, output changes in gap {mig['output_changes_in_gap']}, "
              f"watchdog trips {mig['watchdog_trips']}, wrong node granted {mig['wrong_node_granted']}, state continuity failures {mig['state_continuity_failures']}, violations {mig['violations']}, digests {mig['digests']}\n")

    replay = load("realtime_vs_deterministic.json")
    if replay:
        print("## real time vs deterministic\n")
        print(f"{replay['machine']['date']}, {replay['stimulus_scans']} scans of {replay['scan_ms']} ms\n")
        print(row(["Player phase ms", "Best lag scans", "Output values compared", "Mismatches", "Same state sequence", "State changes det / rt", "Missed", "Change lag scans min/median/max", "Final det", "Final rt"]))
        print(row(["---"] * 10))
        for run in replay["runs"]:
            best = run["best_lag"]
            lag = run["state_change_lag_scans"]
            print(row([run["phase_ms"], best["lag_scans"], best["compared"] * len(best["mismatched_by_signal"]), best["mismatched_scans_total"], run["same_state_sequence"],
                       f"{run['state_changes_deterministic']} / {run['state_changes_real_time']}", len(run["state_changes_unmatched"]),
                       f"{lag.get('min')}/{lag.get('median')}/{lag.get('max')}", run["final"]["deterministic"], run["final"]["real_time"]]))
        print()

    faults = load("faults.json")
    if faults:
        print("## faults\n")
        for key, value in faults.items():
            if key != "machine":
                print(f"- {key}: {value}")


if __name__ == "__main__":
    main()
