"""FORTE (libmodbus) against the firmware's own decision logic, with the plant closing the loop.

The container runs firmware/esp32/lib/io_core on Linux in place of the Python I/O. This tests that FORTE, the agents
and the C++ logic agree: same register map, lease, fencing and watchdog. No ESP32 is involved, and nothing here says
anything about ESP32 timing or Wi-Fi. Only registers are used, because this target has no sim-control port.
"""
from __future__ import annotations

import subprocess
import time

import pytest

import stack
from stack import container, docker, wait_until

OVERLAY = ["-f", str(stack.EDGE / "compose.yaml"), "-f", str(stack.EDGE / "tests/compose.iocore.yaml")]


def ir(client, name: str) -> int:
    return client.read_input(stack.regmap.IR[name]["addr"], 1)[0]


def controlling(client) -> bool:
    holder = ir(client, "LEASE_HOLDER")
    return holder != 0 and stack.read_control(client)["TOKEN"] == ir(client, "LEASE_EPOCH") and ir(client, "LEASE_AGE_MS") < 300


@pytest.fixture(scope="module")
def firmware_stack():
    subprocess.run(["docker", "build", "-q", "-f", "test_host/Dockerfile", "-t", "st2fb-edge-iocore-host:1", "."],
                   cwd=stack.EDGE / "firmware/esp32", check=True, capture_output=True)
    stack.compose(*OVERLAY, "up", "-d", "--no-build", "--force-recreate", "remote-io", "ctrl-a", "ctrl-b")
    client = stack.modbus()
    wait_until(lambda: controlling(client), 30, 0.1, "control over the firmware core")
    yield client
    stack.compose("up", "-d", "--no-build", "--force-recreate", "remote-io", "ctrl-a", "ctrl-b", "ctrl-c")
    wait_until(stack.controlling, 30, what="control back on the simulation")


def test_scan_writes_reach_firmware_core(firmware_stack):
    client = firmware_stack
    first = ir(client, "ACCEPTED")
    time.sleep(2.0)
    assert 15 <= (ir(client, "ACCEPTED") - first) & 0xFFFF <= 25
    assert ir(client, "WD_TRIPPED") == 0


def test_closed_loop_on_firmware_core(firmware_stack):
    client = firmware_stack
    stack.plant_config(level=1.0)
    wait_until(lambda: stack.read_control(client)["STATE_NO"] == 1, 30, 0.05, "waiting state")
    stack.plant_config(level=3.3)
    wait_until(lambda: stack.read_control(client)["STATE_NO"] in (3, 4), 15, 0.05, "pump running")
    assert stack.plant_state()["cmd1"] or stack.plant_state()["cmd2"]
    assert ir(client, "OUTPUT_1") or ir(client, "OUTPUT_2")


def test_failover_and_fencing_on_firmware_core(firmware_stack):
    client = firmware_stack
    holder = ir(client, "LEASE_HOLDER")
    epoch = ir(client, "LEASE_EPOCH")
    name = stack.NODES[holder][0]
    docker("kill", "--signal", "KILL", container(name))
    wait_until(lambda: ir(client, "LEASE_HOLDER") == 3 - holder and controlling(client), 10, 0.02, "standby to control")
    assert ir(client, "LEASE_EPOCH") == epoch + 1
    assert ir(client, "WD_TRIPPED") == 0
    docker("start", container(name))
    wait_until(lambda: stack.node_ready(holder), 15, 0.1, "old node back as standby")
    stale = stack.mbtcp.ModbusException
    with pytest.raises(stale):
        client.write_registers(200, [epoch, 1, 1] + [0] * 17)


def test_watchdog_on_firmware_core_when_all_controllers_stop(firmware_stack):
    client = firmware_stack
    stack.plant_config(level=3.3)
    wait_until(lambda: ir(client, "OUTPUT_1") or ir(client, "OUTPUT_2"), 15, 0.05, "an output on")
    trips = ir(client, "WD_TRIPS")
    docker("pause", container("ctrl-a"), container("ctrl-b"))
    try:
        time.sleep(1.3)
        assert ir(client, "WD_TRIPPED") == 1
        assert (ir(client, "OUTPUT_1"), ir(client, "OUTPUT_2")) == (0, 0)
        assert ir(client, "WD_TRIPS") == trips + 1
        wait_until(lambda: not (stack.plant_state()["cmd1"] or stack.plant_state()["cmd2"]), 2, 0.05, "plant relays off")
    finally:
        docker("unpause", container("ctrl-a"), container("ctrl-b"))
    wait_until(lambda: controlling(client), 10, 0.05, "control after unpause")
