#!/usr/bin/env python3
"""Run the arm64 controller image under QEMU user emulation against the simulated stack, on this x86_64 PC.

This checks that the arm64 binary and image work: FB types present, libmodbus linked, byte and word order right, the
closed loop running. It is not a run on a Raspberry Pi, and its timing means nothing, so no timing is reported.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stack  # noqa: E402

NAME = "st2fb-arm64-check"
IMAGE = "st2fb-edge-controller:efcd63c-arm64"


def main() -> int:
    stack.compose("up", "-d", "--no-build", "plant", "remote-io")
    stack.compose("stop", "-t", "1", "ctrl-a", "ctrl-b", "ctrl-c")
    stack.docker("rm", "-f", NAME, check=False)
    time.sleep(1.5)
    stack.docker("run", "-d", "--rm", "--name", NAME, "--platform", "linux/arm64", "--network", stack.OT_NET, "--ip", "172.30.0.14",
                 "--tmpfs", "/tmp", "-e", "NODE_ID=1", "-e", "ROLE=contender", "-e", "IO_HOST=172.30.0.20", "-e", "AGENT_TOKEN=check", IMAGE)
    client = stack.modbus()
    result = {"image": IMAGE, "note": "QEMU user emulation on x86_64, not a Raspberry Pi. No timing is reported."}
    try:
        result["uname_m"] = stack.docker("exec", NAME, "uname", "-m").stdout.strip()
        result["build_info"] = stack.docker("exec", NAME, "cat", "/opt/forte/BUILD_INFO").stdout.split("\n")[:-1]
        stack.wait_until(lambda: stack.io_state()["holder"] == 1 and stack.read_control(client)["TOKEN"] == stack.io_state()["epoch"], 90, 0.2, "arm64 FORTE to take the lease")
        result["took_lease"] = True
        stack.plant_config(level=1.0)
        stack.wait_until(lambda: stack.read_control(client)["STATE_NO"] == 1, 60, 0.2, "waiting state")
        stack.plant_config(level=3.3)
        stack.wait_until(lambda: stack.read_control(client)["STATE_NO"] in (3, 4), 60, 0.2, "pump running")
        control = stack.read_control(client)
        plant = stack.plant_state()
        result["closed_loop"] = {"STATE_NO": control["STATE_NO"], "FILTERED_LEVEL": round(control["FILTERED_LEVEL"], 3),
                                 "plant_level": plant["level"], "STARTS": control["STARTS"], "cmd1": plant["cmd1"], "cmd2": plant["cmd2"]}
        assert abs(control["FILTERED_LEVEL"] - plant["level"]) < 0.5, "REAL word order or scaling is wrong"
    finally:
        print(stack.docker("logs", "--tail", "5", NAME, check=False).stdout)
        stack.docker("rm", "-f", NAME, check=False)
        stack.compose("up", "-d", "--no-build", "ctrl-a", "ctrl-b", "ctrl-c")
    path = stack.write_result("arm64_qemu.json", result)
    print(result)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
