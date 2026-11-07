"""Same rules for the simulated I/O and for the firmware's decision logic, checked with an independent client.

Both targets run as throwaway containers with short timeouts. pymodbus is the client here, so a bug shared by
this project's own client and server cannot hide. FORTE adds libmodbus as a third implementation in the stack tests.
The firmware target is lib/io_core compiled for Linux: this verifies the logic, not ESP32 timing or Wi-Fi.
"""
from __future__ import annotations

import struct
import subprocess
import time

import pytest
from pymodbus.client import ModbusTcpClient

import stack

EDGE = stack.EDGE
WD_MS, TTL_MS = 300, 200
TARGETS = {"python_sim": 15020, "firmware_core": 15021}
FIRMWARE_IMAGE = "st2fb-edge-iocore-host:1"


def _wait_port(port: int) -> None:
    client = ModbusTcpClient("127.0.0.1", port=port, timeout=0.5)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if client.connect():
            reply = client.read_input_registers(27, count=1, slave=1)
            client.close()
            if not reply.isError():
                return
        time.sleep(0.1)
    raise TimeoutError(f"no Modbus server on {port}")


@pytest.fixture(scope="module", params=sorted(TARGETS))
def target(request):
    name = request.param
    port = TARGETS[name]
    cname = f"st2fb-conformance-{name}"
    subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
    env = ["-e", f"WD_TIMEOUT_MS={WD_MS}", "-e", f"LEASE_TTL_MS={TTL_MS}", "-e", "MODBUS_PORT=1502"]
    if name == "firmware_core":
        subprocess.run(
            ["docker", "build", "-q", "-f", "test_host/Dockerfile", "-t", FIRMWARE_IMAGE, "."],
            cwd=EDGE / "firmware/esp32", check=True, capture_output=True,
        )
        cmd = ["docker", "run", "-d", "--rm", "--name", cname, "-p", f"127.0.0.1:{port}:1502", *env, FIRMWARE_IMAGE]
    else:
        cmd = ["docker", "run", "-d", "--rm", "--name", cname, "-p", f"127.0.0.1:{port}:1502", *env,
               "-e", "PLANT_HOST=127.0.0.1", "st2fb-edge-sim:1", "python3", "-B", "-u", "remote_io/server.py"]
    subprocess.run(cmd, check=True, capture_output=True)
    try:
        _wait_port(port)
        yield name, port
    finally:
        subprocess.run(["docker", "rm", "-f", cname], capture_output=True)


@pytest.fixture
def mb(target):
    client = ModbusTcpClient("127.0.0.1", port=target[1], timeout=2)
    assert client.connect()
    yield client
    client.close()


def words_of(value: float) -> list[int]:
    return list(struct.unpack(">HH", struct.pack(">f", value)))


def ir(mb, addr: int) -> int:
    return mb.read_input_registers(addr, count=1, slave=1).registers[0]


def grant(mb, node: int) -> int:
    """Wait out any previous lease, take a new one, return the token."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        epoch = ir(mb, 16)
        if not mb.write_registers(90, [node, epoch], slave=1).isError():
            return ir(mb, 16)
        time.sleep(0.05)
    raise TimeoutError("no grant")


def control(mb, token: int, pump1: int = 1, pump2: int = 0):
    return mb.write_registers(200, [token, pump1, pump2] + [0] * 17, slave=1)


SETPOINT_OK = words_of(1.0) + words_of(2.0) + words_of(3.0) + words_of(4.0)


def test_map_version_and_heartbeat(mb):
    assert ir(mb, 27) == 1
    first = ir(mb, 9)
    time.sleep(0.1)
    assert ir(mb, 9) != first


def test_default_setpoints_match_regmap(mb):
    words = mb.read_holding_registers(100, count=8, slave=1).registers
    assert words == words_of(1.25) + words_of(3.0) + words_of(4.0) + words_of(5.0)


def test_setpoints_valid_and_invalid(mb):
    assert not mb.write_registers(100, SETPOINT_OK, slave=1).isError()
    assert mb.read_holding_registers(100, count=8, slave=1).registers == SETPOINT_OK
    out_of_range = words_of(0.01) + words_of(2.0) + words_of(3.0) + words_of(4.0)
    misordered = words_of(2.0) + words_of(1.0) + words_of(3.0) + words_of(4.0)
    nan = [0x7FC0, 0] + words_of(2.0) + words_of(3.0) + words_of(4.0)
    for bad in (out_of_range, misordered, nan):
        reply = mb.write_registers(100, bad, slave=1)
        assert reply.isError() and reply.exception_code == 3
    # A partial write is not a write: the block goes whole or not at all.
    reply = mb.write_registers(100, words_of(1.5), slave=1)
    assert reply.isError()
    assert mb.read_holding_registers(100, count=8, slave=1).registers == SETPOINT_OK
    mb.write_registers(100, words_of(1.25) + words_of(3.0) + words_of(4.0) + words_of(5.0), slave=1)


def test_only_allow_listed_functions_and_addresses(mb):
    # FC6 could otherwise change one register of a block without its token.
    assert mb.write_register(201, 1, slave=1).isError()
    assert mb.write_register(100, 1, slave=1).isError()
    assert mb.write_coils(0, [True, True], slave=1).isError()
    assert mb.write_coil(1, True, slave=1).isError()
    assert mb.read_holding_registers(0, count=4, slave=1).isError()
    assert mb.read_input_registers(40, count=1, slave=1).isError()


def test_ack_pulse_clears_itself(mb):
    assert not mb.write_coil(0, True, slave=1).isError()
    assert ir(mb, 10) == 1
    assert mb.read_coils(0, count=1, slave=1).bits[0] is True
    time.sleep(0.7)
    assert ir(mb, 10) == 0


def test_lease_is_compare_and_swap(mb):
    token = grant(mb, 1)
    assert ir(mb, 17) == 1
    control(mb, token)
    # Held and fresh: nobody else gets it, right epoch or not.
    assert mb.write_registers(90, [2, token], slave=1).isError()
    assert mb.write_registers(90, [2, (token - 1) & 0xFFFF], slave=1).isError()
    assert mb.write_registers(90, [0, token], slave=1).isError()
    assert ir(mb, 17) == 1
    time.sleep(TTL_MS / 1000 + 0.1)
    # Expired: a stale expected epoch still loses, the current one wins and the token moves on.
    assert mb.write_registers(90, [2, (token - 1) & 0xFFFF], slave=1).isError()
    assert not mb.write_registers(90, [2, token], slave=1).isError()
    assert ir(mb, 16) == ((token + 1) & 0xFFFF or 1)
    assert ir(mb, 17) == 2


def test_fencing_refuses_old_and_wrong_tokens(mb):
    token = grant(mb, 1)
    assert not control(mb, token, 0, 0).isError()
    rejected = ir(mb, 22)
    for bad in ((token - 1) & 0xFFFF, (token + 1) & 0xFFFF, 0):
        reply = control(mb, bad, 1, 1)
        assert reply.isError() and reply.exception_code == 6
    assert (ir(mb, 20), ir(mb, 21)) == (0, 0)
    assert ir(mb, 22) == (rejected + 3) & 0xFFFF
    # The checkpoint block has the same fence.
    assert mb.write_registers(230, [(token - 1) & 0xFFFF, 1, 1, 0, 0], slave=1).isError()
    assert not mb.write_registers(230, [token, 1, 0, 0, 0], slave=1).isError()
    assert mb.read_holding_registers(230, count=3, slave=1).registers == [token, 1, 0]


def test_outputs_follow_accepted_write_at_once(mb):
    token = grant(mb, 1)
    assert not control(mb, token, 1, 0).isError()
    assert (ir(mb, 20), ir(mb, 21)) == (1, 0)
    assert not control(mb, token, 0, 1).isError()
    assert (ir(mb, 20), ir(mb, 21)) == (0, 1)
    control(mb, token, 0, 0)


def test_watchdog_forces_safe_and_recovers(mb):
    token = grant(mb, 1)
    control(mb, token, 1, 1)
    trips = ir(mb, 24)
    assert (ir(mb, 20), ir(mb, 21)) == (1, 1)
    time.sleep(WD_MS / 1000 + 0.15)
    assert (ir(mb, 20), ir(mb, 21)) == (0, 0)
    assert ir(mb, 19) == 1
    assert ir(mb, 24) == trips + 1
    # Control returns with the next valid write, if the token is still current.
    if ir(mb, 17) == 1:
        assert not control(mb, token, 1, 0).isError()
        assert (ir(mb, 19), ir(mb, 20)) == (0, 1)
        control(mb, token, 0, 0)


def test_watchdog_not_refreshed_by_refused_writes_or_checkpoint(mb):
    token = grant(mb, 1)
    control(mb, token, 1, 0)
    deadline = time.monotonic() + WD_MS / 1000 + 0.15
    while time.monotonic() < deadline:
        mb.write_registers(230, [token, 0, 0, 0, 0], slave=1)
        control(mb, (token + 7) & 0xFFFF, 1, 0)
        time.sleep(0.02)
    assert ir(mb, 20) == 0
    assert ir(mb, 19) == 1


def test_planned_release_reserves_for_the_target(mb):
    token = grant(mb, 1)
    control(mb, token, 1, 0)
    # Only the holder with the current epoch can release.
    assert mb.write_registers(92, [2, token, 3], slave=1).isError()
    assert mb.write_registers(92, [1, (token - 1) & 0xFFFF, 3], slave=1).isError()
    assert not mb.write_registers(92, [1, token, 3], slave=1).isError()
    assert ir(mb, 17) == 0 and ir(mb, 30) == 3
    # After release the old token is dead, though it still equals the epoch.
    assert control(mb, token, 1, 1).isError()
    # Someone else cannot take a reserved lease; the target can, and outputs held meanwhile.
    assert mb.write_registers(90, [2, token], slave=1).isError()
    assert not mb.write_registers(90, [3, token], slave=1).isError()
    assert ir(mb, 17) == 3 and ir(mb, 30) == 0
    assert ir(mb, 20) == 1
    control(mb, ir(mb, 16), 0, 0)


def test_reservation_expires(mb):
    token = grant(mb, 1)
    control(mb, token, 0, 0)
    assert not mb.write_registers(92, [1, token, 3], slave=1).isError()
    time.sleep(TTL_MS / 1000 + 0.1)
    assert ir(mb, 30) == 0
    assert not mb.write_registers(90, [2, token], slave=1).isError()


def test_regmap_header_is_generated_from_the_json():
    result = subprocess.run(["python3", str(EDGE / "firmware/esp32/gen_regmap_h.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
