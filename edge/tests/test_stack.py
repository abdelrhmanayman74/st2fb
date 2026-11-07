"""Integration tests against the running stack: control path, IT services, authentication, security basics."""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time

import paho.mqtt.client as mqtt
import pytest
import requests
from asyncua import Client as UaClient
from pymodbus.client import ModbusTcpClient

import stack
from stack import API, ENV, io_events, io_state, plant_state, read_control, wait_until


@pytest.fixture(scope="module", autouse=True)
def running_stack():
    stack.ensure_core_up(stack.IT_SERVICES)
    wait_until(lambda: requests.get(f"{API}/healthz", timeout=1).ok, 30, what="api")
    wait_until(lambda: gateway_health()["mqtt_connected"], 30, what="gateway mqtt")
    yield


def viewer() -> dict:
    return {"Authorization": f"Bearer {ENV['API_VIEWER_TOKEN']}"}


def operator() -> dict:
    return {"Authorization": f"Bearer {ENV['API_OPERATOR_TOKEN']}"}


def gateway_health() -> dict:
    return requests.get(f"{API}/api/v1/health", headers=viewer(), timeout=2).json()["gateway"]


# Control path

def test_scan_writes_arrive_every_cycle():
    seq = io_state()["last"]
    time.sleep(2.0)
    accepts = [e for e in io_events(seq) if e["kind"] == "accept"]
    assert 17 <= len(accepts) <= 23, len(accepts)


def test_scan_dt_equals_cycle():
    """SCAN_DT is data; the only guarantee it matches the cycle is that both come from one constant."""
    status = stack.agent(io_state()["holder"], "/status")
    assert status["scan"]["CYCLE.DT"] == status["scan"]["SUP.SCAN_DT"] == "T#100ms"


def test_all_nodes_deploy_the_same_application():
    digests = {stack.agent(n, "/status")["app_digest"] for n in stack.NODES}
    assert len(digests) == 1


def test_closed_loop_holds_level_between_stop_and_high():
    """Run the plant through a pumping cycle and check the supervisor's own thresholds in the plant trace."""
    client = stack.modbus()
    stack.to_waiting(client)
    stack.plant_config(level=3.2, reset_max=True)
    wait_until(lambda: read_control(client)["STATE_NO"] in (3, 4), 30, 0.1, "pump running")
    state = read_control(client)
    assert plant_state()["cmd1"] or plant_state()["cmd2"]
    assert state["STARTS"] >= 1
    assert plant_state()["max_level"] < 5.5


def test_feedback_failure_rotates_to_other_pump():
    """Supervisor logic live on real time: the lead cannot prove running, so the other pump takes over."""
    client = stack.modbus()
    stack.to_waiting(client)
    lead2 = read_control(client)["LEAD_IS_2"]
    pump = 2 if lead2 else 1
    stack.plant_fault(**{f"pump_fail_{pump}": True})
    try:
        stack.plant_config(level=3.4)
        wait_until(lambda: read_control(client)["LEAD_IS_2"] != lead2, 10, 0.05, "lead rotation")
        other = f"PUMP_{1 if pump == 2 else 2}"
        wait_until(lambda: read_control(client)[other] == 1, 5, 0.05, "other pump running")
        assert read_control(client)[f"PUMP_{pump}"] == 0
    finally:
        stack.plant_fault(**{f"pump_fail_{pump}": False})
        client.write_coil(0, True)
    stack.to_waiting(client)


def test_libmodbus_and_pymodbus_read_same_values():
    """FORTE writes through libmodbus. pymodbus reads what it wrote, decoded with the map's word order."""
    client = ModbusTcpClient("127.0.0.1", port=1502, timeout=2)
    assert client.connect()
    words = client.read_holding_registers(200, count=20, slave=1).registers
    client.close()
    assert words[0] == io_state()["epoch"]
    assert 0.0 <= stack.regmap.decode(stack.regmap.group("control"), words, 200)["FILTERED_LEVEL"] <= 6.0


# REST API

def test_read_needs_a_token():
    for path in ("/api/v1/tags", "/api/v1/alarms", "/api/v1/health", "/api/v1/history", "/api/v1/setpoints"):
        assert requests.get(API + path, timeout=2).status_code == 401
        assert requests.get(API + path, headers={"Authorization": "Bearer wrong"}, timeout=2).status_code == 401
        assert requests.get(API + path, headers=viewer(), timeout=2).status_code == 200


def test_write_needs_operator_token():
    good = {"STOP_LEVEL": 1.25, "START_LEVEL": 3.0, "LAG_LEVEL": 4.0, "HIGH_LEVEL": 5.0}
    assert requests.put(f"{API}/api/v1/setpoints", json=good, timeout=2).status_code == 401
    assert requests.put(f"{API}/api/v1/setpoints", json=good, headers=viewer(), timeout=2).status_code == 403
    assert requests.post(f"{API}/api/v1/alarms/ack", headers=viewer(), timeout=2).status_code == 403
    assert requests.put(f"{API}/api/v1/setpoints", json=good, headers=operator(), timeout=2).status_code == 200


@pytest.mark.parametrize("bad", [
    {"STOP_LEVEL": 3.5, "START_LEVEL": 3.0, "LAG_LEVEL": 4.0, "HIGH_LEVEL": 5.0},
    {"STOP_LEVEL": 0.0, "START_LEVEL": 3.0, "LAG_LEVEL": 4.0, "HIGH_LEVEL": 5.0},
    {"STOP_LEVEL": 1.25, "START_LEVEL": 3.0, "LAG_LEVEL": 4.0, "HIGH_LEVEL": 99.0},
    {"STOP_LEVEL": 1.25, "START_LEVEL": 3.0, "LAG_LEVEL": 4.0},
    {"STOP_LEVEL": 1.25, "START_LEVEL": 3.0, "LAG_LEVEL": 4.0, "HIGH_LEVEL": 5.0, "PUMP_1": 1},
    {"STOP_LEVEL": "x", "START_LEVEL": 3.0, "LAG_LEVEL": 4.0, "HIGH_LEVEL": 5.0},
])
def test_invalid_setpoints_are_refused(bad):
    assert requests.put(f"{API}/api/v1/setpoints", json=bad, headers=operator(), timeout=2).status_code == 422


def test_setpoint_reaches_the_controller_through_fbs_inputs():
    """Write through REST, then see a real behaviour change in the FB: pumps start at the new START_LEVEL."""
    client = stack.modbus()
    new = {"STOP_LEVEL": 1.0, "START_LEVEL": 2.2, "LAG_LEVEL": 4.0, "HIGH_LEVEL": 5.0}
    default = {"STOP_LEVEL": 1.25, "START_LEVEL": 3.0, "LAG_LEVEL": 4.0, "HIGH_LEVEL": 5.0}
    stack.to_waiting(client)
    assert requests.put(f"{API}/api/v1/setpoints", json=new, headers=operator(), timeout=2).status_code == 200
    try:
        stack.plant_config(level=2.4)
        wait_until(lambda: read_control(client)["STATE_NO"] in (2, 3), 5, 0.05, "start at the new setpoint")
    finally:
        requests.put(f"{API}/api/v1/setpoints", json=default, headers=operator(), timeout=2)
    stack.to_waiting(client)


def test_write_surface_is_exactly_two_endpoints():
    spec = requests.get(f"{API}/openapi.json", timeout=2).json()
    writes = sorted((method.upper(), path) for path, item in spec["paths"].items()
                    for method in item if method in ("post", "put", "patch", "delete"))
    assert writes == [("POST", "/api/v1/alarms/ack"), ("PUT", "/api/v1/setpoints")]
    assert requests.get(f"{API}/docs", timeout=2).status_code == 200


def test_ack_endpoint_pulses_the_coil():
    assert requests.post(f"{API}/api/v1/alarms/ack", headers=operator(), timeout=2).status_code == 200
    assert stack.modbus().read_input(10, 1)[0] == 1


def test_history_comes_from_tsdb():
    wait_until(lambda: len(requests.get(f"{API}/api/v1/history", params={"tag": "raw_level", "minutes": 5}, headers=viewer(), timeout=2).json()["points"]) > 3, 30, 1, "history points")
    assert requests.get(f"{API}/api/v1/history", params={"tag": "evil{}"}, headers=viewer(), timeout=2).status_code == 422


def test_dashboard_page_served_and_marked_simulated():
    page = requests.get(API + "/", timeout=2)
    assert page.status_code == 200 and "Simulated" in page.text


# MQTT and OPC UA

def _mqtt_client(user: str, password: str | None) -> tuple[mqtt.Client, dict]:
    result: dict = {"rc": None, "messages": {}}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if password is not None:
        client.username_pw_set(user, password)

    def on_connect(_c, _u, _f, reason, _p=None):
        result["rc"] = reason.value

    def on_message(_c, _u, message):
        result["messages"][message.topic] = message.payload

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("127.0.0.1", 1883, 5)
    client.loop_start()
    deadline = time.monotonic() + 5
    while result["rc"] is None and time.monotonic() < deadline:
        time.sleep(0.02)
    return client, result


def test_mqtt_anonymous_and_wrong_password_refused():
    for user, password in (("x", None), ("st2fb-viewer", "wrong")):
        client, result = _mqtt_client(user, password)
        client.loop_stop()
        client.disconnect()
        assert result["rc"] not in (None, 0), (user, result["rc"])


def test_mqtt_tags_published_and_viewer_cannot_publish():
    client, result = _mqtt_client("st2fb-viewer", ENV["MQTT_VIEWER_PASSWORD"])
    assert result["rc"] == 0
    client.subscribe("st2fb/station1/#")
    wait_until(lambda: "st2fb/station1/tags/RAW_LEVEL" in result["messages"], 5, what="tag message")
    wait_until(lambda: "st2fb/station1/state" in result["messages"], 5, what="state message")
    assert json.loads(result["messages"]["st2fb/station1/state"])["simulated"] is True
    # The ACL drops this silently; the retained value must not change to it.
    client.publish("st2fb/station1/tags/RAW_LEVEL", "999", retain=True)
    time.sleep(1.5)
    assert result["messages"]["st2fb/station1/tags/RAW_LEVEL"] != b"999"
    client.loop_stop()
    client.disconnect()


def test_opcua_browse_read_and_write_refused():
    async def scenario():
        async with UaClient("opc.tcp://127.0.0.1:4840/st2fb/", timeout=5) as client:
            index = await client.get_namespace_index("urn:st2fb:edge:simulated")
            node = client.get_node(f"ns={index};s=RAW_LEVEL")
            value = await node.read_value()
            assert isinstance(value, float)
            with pytest.raises(Exception):
                await node.write_value(1.0)
            return value

    assert 0.0 <= asyncio.run(scenario()) <= 6.0


# Security basics

def test_published_ports_bind_localhost_only():
    out = subprocess.run(["docker", "compose", "--project-directory", str(stack.EDGE), "ps", "--format", "{{json .Publishers}}"],
                         capture_output=True, text=True, check=True, env={**__import__("os").environ, "ALLOW_TEST_HOOKS": "1"}).stdout
    addresses = {p["URL"] for line in out.splitlines() for p in json.loads(line) if p.get("PublishedPort")}
    assert addresses == {"127.0.0.1"}, addresses


def test_forte_management_port_not_reachable_from_ot_network():
    """DEV_MGR has no authentication, so it listens on the container's loopback only."""
    probe = ["docker", "exec", stack.container("ctrl-a"), "python3", "-c",
             "import socket,sys\ns=socket.socket();s.settimeout(1)\n"
             "sys.exit(0 if s.connect_ex(('172.30.0.12',61499))!=0 else 1)"]
    assert subprocess.run(probe, capture_output=True).returncode == 0


def test_api_container_has_no_route_to_ot_network():
    probe = ["docker", "exec", stack.container("api"), "python3", "-c",
             "import socket,sys\ns=socket.socket();s.settimeout(1)\n"
             "sys.exit(0 if s.connect_ex(('172.30.0.20',502))!=0 else 1)"]
    assert subprocess.run(probe, capture_output=True).returncode == 0


def test_no_secrets_tracked_and_generated_files_ignored():
    repo = stack.EDGE.parent
    for path in ("edge/.env", "edge/secrets/passwd"):
        assert subprocess.run(["git", "check-ignore", "-q", path], cwd=repo).returncode == 0, path
    candidates = subprocess.run(["git", "ls-files", "--others", "--cached", "--exclude-standard", "edge", "docs/EDGE.md"],
                                cwd=repo, capture_output=True, text=True, check=True).stdout.split()
    secrets_values = [v for k, v in ENV.items() if k.endswith(("TOKEN", "PASSWORD"))]
    for name in candidates:
        path = repo / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for value in secrets_values:
            assert value not in text, f"secret found in {name}"
    example = (stack.EDGE / ".env.example").read_text()
    assert not re.search(r"^[A-Z_]+(TOKEN|PASSWORD)=(?!generated-by-bootstrap)", example, re.M)


def test_agent_needs_token_and_test_hook_is_off_by_default():
    """A throwaway node with the default setting. The split-brain hook must answer 403, and everything needs the token."""
    name = "st2fb-hook-check"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, "--network", stack.OT_NET, "-p", "127.0.0.1:18119:8081",
                    "-e", "NODE_ID=9", "-e", "ROLE=bare", "-e", "AGENT_TOKEN=check", "-e", "IO_HOST=172.30.0.20",
                    "st2fb-edge-controller:efcd63c"], check=True, capture_output=True)
    try:
        url = "http://127.0.0.1:18119"
        wait_until(lambda: requests.get(f"{url}/status", timeout=1).status_code == 401, 15, what="agent up")
        hook = requests.post(f"{url}/test/force_gate", json={"token": 1, "open": True}, headers={"Authorization": "Bearer check"}, timeout=2)
        assert hook.status_code == 403
        assert requests.post(f"{url}/deploy", json={}, timeout=2).status_code == 401
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def test_ot_containers_have_no_internet_route():
    probe = ["docker", "exec", stack.container("ctrl-a"), "python3", "-c",
             "import socket,sys\ns=socket.socket();s.settimeout(2)\n"
             "sys.exit(0 if s.connect_ex(('1.1.1.1',443))!=0 else 1)"]
    assert subprocess.run(probe, capture_output=True).returncode == 0
