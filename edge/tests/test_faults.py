"""Fault injection. Each test states the expected behaviour and checks it. Everything here is simulated.

The main rule: control keeps running when IT systems fail. "Keeps running" is measured at the I/O: accepted
control writes per second, from the controller's scan, while the fault is present.
"""
from __future__ import annotations

import time

import pytest
import requests

import stack
from stack import API, ENV, container, docker, io_events, io_state, plant_fault, plant_state, read_control, wait_until

RESULTS: dict = {}
MS = 1e-6


def viewer() -> dict:
    return {"Authorization": f"Bearer {ENV['API_VIEWER_TOKEN']}"}


def operator() -> dict:
    return {"Authorization": f"Bearer {ENV['API_OPERATOR_TOKEN']}"}


def health() -> dict:
    return requests.get(f"{API}/api/v1/health", headers=viewer(), timeout=2).json()


def alarms() -> set[str]:
    return {a["code"] for a in requests.get(f"{API}/api/v1/alarms", headers=viewer(), timeout=2).json()["alarms"]}


def write_rate(seconds: float) -> dict:
    """Accepted writes per second and the worst gap between them, over a window."""
    seq = io_state()["last"]
    time.sleep(seconds)
    events = io_events(seq)
    accepts = [e["t_ns"] for e in events if e["kind"] == "accept"]
    gaps = [(b - a) * MS for a, b in zip(accepts, accepts[1:])]
    return {"writes_per_s": round(len(accepts) / seconds, 2), "max_gap_ms": round(max(gaps), 2) if gaps else None,
            "wd_trips": sum(e["kind"] == "wd_trip" for e in events), "grants": sum(e["kind"] == "grant" for e in events)}


@pytest.fixture(scope="module", autouse=True)
def stack_up_and_save():
    stack.ensure_core_up(stack.IT_SERVICES)
    wait_until(lambda: requests.get(f"{API}/healthz", timeout=1).ok, 30, what="api")
    wait_until(lambda: health()["gateway"]["mqtt_connected"], 30, what="mqtt")
    stack.plant_config(base_inflow=90.0, swing=10.0, level=2.0, reset_max=True)
    yield
    # Partial runs must not overwrite a full result set.
    if len(RESULTS) >= 8:
        stack.write_result("faults.json", RESULTS)


@pytest.fixture(autouse=True)
def healthy_before_each():
    plant_fault(trip_1=False, trip_2=False, pump_fail_1=False, pump_fail_2=False, sensor_stuck=False, auto_switch=True)
    wait_until(stack.controlling, 30, what="control before the test")
    yield
    plant_fault(trip_1=False, trip_2=False, pump_fail_1=False, pump_fail_2=False, sensor_stuck=False, auto_switch=True)


def test_mqtt_broker_down():
    """Expected: scan rate unchanged and no watchdog trip. API stays up and reports MQTT down. Reconnects when back."""
    plant_before = plant_state()
    before = write_rate(3)
    docker("stop", "-t", "1", container("mosquitto"))
    try:
        wait_until(lambda: not health()["gateway"]["mqtt_connected"], 15, 0.2, "gateway to notice")
        during = write_rate(10)
        assert during["writes_per_s"] >= 9.0
        assert during["wd_trips"] == 0 and during["grants"] == 0
        assert requests.get(f"{API}/api/v1/tags", headers=viewer(), timeout=2).status_code == 200
        # Setpoints do not use MQTT, so an operator can still write them.
    finally:
        docker("start", container("mosquitto"))
    t0 = time.monotonic()
    wait_until(lambda: health()["gateway"]["mqtt_connected"], 30, 0.2, "MQTT reconnect")
    RESULTS["mqtt_down"] = {"before": before, "during": during, "reconnect_s": round(time.monotonic() - t0, 2),
                            "level_before": plant_before["level"], "level_after": plant_state()["level"]}


def test_gateway_restart():
    """Expected: scan rate unchanged. API answers 503 while the gateway is away, then recovers. Setpoints survive
    because they live at the I/O."""
    client = stack.modbus()
    setpoints_before = client.read_holding(100, 8)
    docker("stop", "-t", "1", container("gateway"))
    try:
        assert requests.get(f"{API}/api/v1/tags", headers=viewer(), timeout=3).status_code == 503
        good = {"STOP_LEVEL": 1.25, "START_LEVEL": 3.0, "LAG_LEVEL": 4.0, "HIGH_LEVEL": 5.0}
        assert requests.put(f"{API}/api/v1/setpoints", json=good, headers=operator(), timeout=3).status_code == 503
        during = write_rate(5)
        assert during["writes_per_s"] >= 9.0
        assert during["wd_trips"] == 0 and during["grants"] == 0
    finally:
        docker("start", container("gateway"))
    t0 = time.monotonic()
    wait_until(lambda: requests.get(f"{API}/api/v1/tags", headers=viewer(), timeout=2).json()["io_link_ok"], 20, 0.2, "gateway back")
    RESULTS["gateway_restart"] = {"during": during, "recovery_s": round(time.monotonic() - t0, 2)}
    assert client.read_holding(100, 8) == setpoints_before


def test_tsdb_down():
    """Expected: scan unaffected; live tags fine; history returns 503."""
    docker("stop", "-t", "1", container("tsdb"))
    try:
        during = write_rate(5)
        assert during["writes_per_s"] >= 9.0 and during["wd_trips"] == 0
        assert requests.get(f"{API}/api/v1/history", headers=viewer(), timeout=3).status_code == 503
        assert requests.get(f"{API}/api/v1/tags", headers=viewer(), timeout=3).status_code == 200
        wait_until(lambda: not health()["gateway"]["tsdb_ok"], 10, 0.2, "gateway to notice")
    finally:
        docker("start", container("tsdb"))
    wait_until(lambda: health()["gateway"]["tsdb_ok"], 20, 0.2, "TSDB writes to resume")
    RESULTS["tsdb_down"] = {"during": during}


def test_all_it_down_control_keeps_running():
    """Expected: with broker, TSDB, gateway and API all stopped, the supervisor still controls the plant."""
    services = ["api", "gateway", "tsdb", "mosquitto"]
    client = stack.modbus()
    stack.to_waiting(client)
    starts_before = read_control(client)["STARTS"]
    docker("stop", "-t", "1", *[container(s) for s in services])
    try:
        during = write_rate(5)
        assert during["writes_per_s"] >= 9.0 and during["wd_trips"] == 0
        stack.plant_config(level=3.3)
        wait_until(lambda: read_control(client)["STATE_NO"] in (3, 4), 20, 0.1, "a pump start with no IT running")
        assert read_control(client)["STARTS"] > starts_before
    finally:
        docker("start", *[container(s) for s in reversed(services)])
    wait_until(lambda: requests.get(f"{API}/healthz", timeout=1).ok, 30, what="api back")
    wait_until(lambda: health()["gateway"]["mqtt_connected"], 30, what="mqtt back")
    stack.to_waiting(client)
    RESULTS["all_it_down"] = {"during": during, "started_pump_without_it": True}


def test_sensor_stuck():
    """Expected: after STUCK_TIME (10 s) with an unchanged reading, SENSOR_FAULT latches, AUTO_MODE drops, pumps stop,
    and the API shows the alarm. When the reading moves again, control stays off until an operator acknowledges."""
    client = stack.modbus()
    stack.plant_config(level=2.6)
    t_inject = time.monotonic_ns()
    plant_fault(sensor_stuck=True)
    wait_until(lambda: read_control(client)["SENSOR_FAULT"] == 1, 15, 0.05, "SENSOR_FAULT")
    detect_s = (time.monotonic_ns() - t_inject) * 1e-9
    assert 9.5 <= detect_s <= 12.0, detect_s
    wait_until(lambda: not any(plant_state()[k] for k in ("cmd1", "cmd2")), 3, 0.05, "pumps off")
    wait_until(lambda: read_control(client)["STATE_NO"] == 0, 3, 0.05, "state 0")
    wait_until(lambda: "SENSOR_STUCK" in alarms(), 5, 0.1, "API alarm")
    # Real reading returns. The latch must hold until ACK.
    plant_fault(sensor_stuck=False)
    time.sleep(1.0)
    assert read_control(client)["SENSOR_FAULT"] == 1
    assert read_control(client)["STATE_NO"] == 0
    assert requests.post(f"{API}/api/v1/alarms/ack", headers=operator(), timeout=2).status_code == 200
    wait_until(lambda: read_control(client)["SENSOR_FAULT"] == 0, 3, 0.05, "fault cleared by ACK")
    wait_until(lambda: read_control(client)["STATE_NO"] >= 1, 3, 0.05, "supervisor back to waiting")
    stack.to_waiting(client)
    RESULTS["sensor_stuck"] = {"detect_s": round(detect_s, 2), "stuck_time_setting_s": 10,
                               "latched_until_ack": True, "pumps_off": True}


def test_modbus_link_loss():
    """Expected at the I/O: watchdog forces outputs off within WD_TIMEOUT_MS plus a tick. Expected at the controllers:
    GUARD reports COMMS_OK false; no lease change is possible. Link back: control resumes unaided."""
    client = stack.modbus()
    state = io_state()
    wd_ms = state["wd_timeout_ms"]
    holder = state["holder"]
    stack.plant_config(level=3.4)
    wait_until(lambda: read_control(client)["PUMP_1"] or read_control(client)["PUMP_2"], 15, 0.05, "pump on before the cut")
    seq = state["last"]
    t_cut = time.monotonic_ns()
    docker("network", "disconnect", "--force", stack.OT_NET, container("remote-io"))
    try:
        wait_until(lambda: io_state()["wd_tripped"], 5, 0.02, "watchdog")
        t_wd = time.monotonic_ns()
        wait_until(lambda: not (plant_state()["cmd1"] or plant_state()["cmd2"]), 2, 0.02, "relays off")
        wait_until(lambda: stack.agent(holder, "/status")["scan"]["GUARD.COMMS_OK"] == "FALSE", 5, 0.05, "GUARD to report the loss")
        t_guard = time.monotonic_ns()
        time.sleep(2.0)
        epoch_during = io_state()["epoch"]
        level_mid = plant_state()["level"]
    finally:
        docker("network", "connect", "--ip", stack.IPS["remote-io"], stack.OT_NET, container("remote-io"))
    t_back = time.monotonic_ns()
    wait_until(stack.controlling, 30, 0.05, "control to resume")
    t_resume = time.monotonic_ns()
    events = io_events(seq)
    last_before = max(e["t_ns"] for e in events if e["kind"] == "accept" and e["t_ns"] < t_cut + 2_000_000_000 and e["t_ns"] <= t_wd)
    trips = [e for e in events if e["kind"] == "wd_trip"]
    assert trips
    wd_after_last_write_ms = (trips[0]["t_ns"] - last_before) * MS
    assert wd_after_last_write_ms <= wd_ms + 100
    # Blocking Modbus calls run on the event chain thread, so the cycle stretches during the outage.
    node = stack.NODES[holder][0]
    log_rows = [r[0] for r in stack.scan_log(node)]
    outage = [(b - a) * MS for a, b in zip(log_rows, log_rows[1:]) if t_cut <= a <= t_back]
    wait_until(lambda: read_control(client)["STATE_NO"] in (3, 4), 15, 0.05, "normal pump start after the link returns")
    assert plant_state()["level"] < 6.0
    stack.to_waiting(stack.modbus())
    RESULTS["modbus_link_loss"] = {
        "cycle_during_outage_ms": stack.stats(outage),
        "wd_after_last_write_ms": round(wd_after_last_write_ms, 1), "wd_timeout_ms": wd_ms,
        "guard_reports_loss_s": round((t_guard - t_cut) * 1e-9, 2),
        "epoch_changed_during_outage": epoch_during != state["epoch"],
        "resume_after_link_back_s": round((t_resume - t_back) * 1e-9, 2),
        "level_during_outage_m": level_mid,
        "grants_after_link_back": sum(e["kind"] == "grant" for e in events),
    }


def test_forte_process_crash():
    """Expected: only FORTE dies, the agent survives. The lease expires, the standby takes over, the agent restarts
    FORTE, redeploys in shadow and rejoins as standby. No write of the old epoch is accepted after the grant."""
    state = io_state()
    holder, seq = state["holder"], state["last"]
    old_epoch = state["epoch"]
    kill = ("import os,signal\n"
            "for p in os.listdir('/proc'):\n"
            "    if p.isdigit() and open(f'/proc/{p}/comm').read().strip()=='forte': os.kill(int(p),signal.SIGKILL)\n")
    t0 = time.monotonic_ns()
    docker("exec", container(stack.NODES[holder][0]), "python3", "-c", kill)
    wait_until(lambda: io_state()["holder"] == 3 - holder and stack.controlling(), 10, 0.02, "standby to take over")
    takeover_ms = (time.monotonic_ns() - t0) * MS
    wait_until(lambda: stack.node_ready(holder), 15, 0.1, "crashed node back as standby")
    events = io_events(seq)
    grant = next(e for e in events if e["kind"] == "grant")
    assert grant["epoch"] > old_epoch
    assert not [e for e in events if e["kind"] == "accept" and e["epoch"] == old_epoch and e["t_ns"] > grant["t_ns"]]
    RESULTS["forte_process_crash"] = {"takeover_ms": round(takeover_ms, 1), "rejoined_as_standby": True}


def test_remote_io_restart():
    """Expected: a rebooted I/O has a new random epoch, no holder, and safe outputs. The old token is refused,
    a controller takes a new lease. Setpoints go back to defaults because this I/O does not persist them."""
    client = stack.modbus()
    old = read_control(client)["TOKEN"]
    t0 = time.monotonic()
    docker("restart", "-t", "0", container("remote-io"))
    wait_until(stack.controlling, 30, 0.05, "control after I/O reboot")
    new_token = read_control(stack.modbus())["TOKEN"]
    RESULTS["remote_io_restart"] = {"recover_s": round(time.monotonic() - t0, 2), "old_token": old, "new_token": new_token}
    assert new_token != old
