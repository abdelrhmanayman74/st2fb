#!/usr/bin/env python3
"""Move the control logic to another node, on the simulated stack, without touching the I/O or its wiring.

    edge/.venv/bin/python edge/tools/move_logic.py --to ctrl-c

Steps: deploy the application on the target through its agent (shadow, gate closed), wait until it sees live inputs,
tell the current holder to hand over (final checkpoint, gate shut, release reserved for the target), wait until the
target's writes arrive at the I/O, then empty the source node. Prints what the I/O saw.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

import stack  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", required=True, choices=sorted(stack.NODE_IDS))
    args = parser.parse_args()
    target = stack.NODE_IDS[args.to]
    source = stack.io_state()["holder"]
    if source == target:
        print(f"{args.to} already holds the lease")
        return 0
    seq = stack.io_state()["last"]
    deployed = stack.agent(target, "/deploy", {"contend": True})
    print(f"deployed on {args.to} in {deployed['deploy_ms']:.1f} ms, application {deployed['app_digest']}")
    stack.wait_until(lambda: stack.node_ready(target), 15, 0.02, "target to see live inputs")
    stack.agent(source, "/handover", {"to": target})
    stack.wait_until(lambda: stack.io_state()["holder"] == target and stack.read_control().get("TOKEN") == stack.io_state()["epoch"],
                     10, 0.01, "target to control")
    time.sleep(0.3)
    events = stack.io_events(seq)
    grant = next(e for e in events if e["kind"] == "grant")
    last_old = [e for e in events if e["kind"] == "accept" and e["t_ns"] < grant["t_ns"]][-1]
    first_new = next(e for e in events if e["kind"] == "accept" and e["epoch"] == grant["epoch"])
    print(f"I/O saw {stack.NODES[source][0]} epoch {last_old['epoch']} then {args.to} epoch {grant['epoch']}, "
          f"{(first_new['t_ns'] - last_old['t_ns']) / 1e6:.1f} ms between control writes, "
          f"pump commands {last_old['pump1']},{last_old['pump2']} then {first_new['pump1']},{first_new['pump2']}, "
          f"watchdog trips {sum(e['kind'] == 'wd_trip' for e in events)}")
    stack.agent(source, "/undeploy", {})
    print(f"{stack.NODES[source][0]} is now an empty runtime")
    return 0


if __name__ == "__main__":
    sys.exit(main())
