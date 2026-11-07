"""Host-side helpers for the tests: compose control, sim-control ports, agents, statistics.

All timestamps from containers are CLOCK_MONOTONIC. Containers on one host share that clock, and
time.monotonic_ns() here reads it too, so times from different containers can be compared directly.
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import statistics
import struct
import subprocess
import sys
import time
from pathlib import Path

import requests

EDGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EDGE))

from common import mbtcp, regmap  # noqa: E402

RESULTS = EDGE / "results"
PROJECT = "st2fb-edge"
OT_NET = f"{PROJECT}_ot"
PLANT = "http://127.0.0.1:18100"
IO = "http://127.0.0.1:18101"
API = "http://127.0.0.1:8080"
NODES = {1: ("ctrl-a", 18111), 2: ("ctrl-b", 18112), 3: ("ctrl-c", 18113)}
NODE_IDS = {name: node for node, (name, _) in NODES.items()}
IPS = {"ctrl-a": "172.30.0.11", "ctrl-b": "172.30.0.12", "ctrl-c": "172.30.0.13", "remote-io": "172.30.0.20", "gateway": "172.30.0.30"}
CORE_SERVICES = ["plant", "remote-io", "ctrl-a", "ctrl-b", "ctrl-c"]
IT_SERVICES = ["mosquitto", "tsdb", "gateway", "api"]
SESSION = requests.Session()


def env_file() -> dict[str, str]:
    values = {}
    for line in (EDGE / ".env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


ENV = env_file() if (EDGE / ".env").exists() else {}


def compose(*args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "--project-directory", str(EDGE), *args],
        check=check, capture_output=True, text=True, env={**os.environ, "ALLOW_TEST_HOOKS": "1", **(env or {})},
    )


def container(service: str) -> str:
    return f"{PROJECT}-{service}-1"


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True)


def agent(node_or_name, path: str, body: dict | None = None, timeout: float = 3.0):
    node = NODE_IDS.get(node_or_name, node_or_name)
    url = f"http://127.0.0.1:{NODES[node][1]}{path}"
    headers = {"Authorization": f"Bearer {ENV['AGENT_TOKEN']}"}
    if body is None:
        return SESSION.get(url, headers=headers, timeout=timeout).json()
    return SESSION.post(url, headers=headers, json=body, timeout=timeout).json()


def io_state() -> dict:
    return SESSION.get(f"{IO}/state", timeout=2).json()


def io_events(since: int = 0) -> list[dict]:
    return SESSION.get(f"{IO}/events", params={"since": since}, timeout=5).json()["events"]


def io_config(**values) -> dict:
    return SESSION.post(f"{IO}/config", json=values, timeout=2).json()


def plant_state() -> dict:
    return SESSION.get(f"{PLANT}/state", timeout=2).json()


def plant_trace(since_ns: int = 0) -> list[dict]:
    return SESSION.get(f"{PLANT}/trace", params={"since_ns": since_ns}, timeout=5).json()["rows"]


def plant_fault(**faults) -> dict:
    return SESSION.post(f"{PLANT}/fault", json=faults, timeout=2).json()


def plant_config(**values) -> dict:
    return SESSION.post(f"{PLANT}/config", json=values, timeout=2).json()


def modbus(timeout: float = 1.0) -> mbtcp.Client:
    return mbtcp.Client("127.0.0.1", 1502, timeout=timeout)


def read_control(client: mbtcp.Client | None = None) -> dict:
    client = client or modbus()
    base, count = regmap.span(regmap.group("control"))
    return regmap.decode(regmap.group("control"), client.read_holding(base, count), base)


def wait_until(condition, timeout: float, period: float = 0.05, what: str = "condition"):
    deadline = time.monotonic() + timeout
    while True:
        try:
            value = condition()
        except (requests.RequestException, OSError, KeyError, ValueError):
            value = None
        if value:
            return value
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out after {timeout} s waiting for {what}")
        time.sleep(period)


def scan_log(service: str) -> list[tuple[int, int]]:
    """(event time ns, execution us of the previous scan) from SCAN_PROBE's raw log inside the container."""
    raw = docker_bytes("exec", container(service), "cat", "/tmp/scan.bin")
    return [struct.unpack_from("<QI", raw, i) for i in range(0, len(raw) - len(raw) % 16, 16)]


def docker_bytes(*args: str) -> bytes:
    return subprocess.run(["docker", *args], check=True, capture_output=True).stdout


def to_waiting(client: mbtcp.Client | None = None, level: float = 1.0) -> None:
    """Bring the supervisor to state 1 with pumps off. A running pump only stops at or below STOP_LEVEL."""
    client = client or modbus()
    plant_config(level=level)
    wait_until(lambda: read_control(client)["STATE_NO"] == 1, 30, 0.05, "waiting state")


def active_node() -> int:
    return io_state()["holder"]


def node_ready(node) -> bool:
    status = agent(node, "/status")
    return status["state"] == "SHADOW" and status["scan"].get("GUARD.COMMS_OK") == "TRUE"


def controlling() -> bool:
    """A holder exists and its writes are arriving."""
    state = io_state()
    return state["holder"] != 0 and not state["wd_tripped"] and read_control().get("TOKEN") == state["epoch"]


def ensure_core_up(extra: list[str] | None = None) -> None:
    services = CORE_SERVICES + (extra or [])
    compose("up", "-d", "--no-build", *services)
    wait_until(controlling, 30, what="a controller to take the lease")


def stats(values: list[float]) -> dict:
    """mean, median, p95, max in one consistent form. p95 is nearest rank."""
    ordered = sorted(values)
    if not ordered:
        return {"n": 0}
    rank = max(0, min(len(ordered) - 1, int(round(0.95 * len(ordered))) - 1))
    return {
        "n": len(ordered),
        "mean": round(statistics.fmean(ordered), 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[rank], 3),
        "max": round(ordered[-1], 3),
        "min": round(ordered[0], 3),
    }


def machine_info() -> dict:
    cpu = "unknown"
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            cpu = line.split(":", 1)[1].strip()
            break
    return {
        "date": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "cpu": cpu,
        "cpus": os.cpu_count(),
        "kernel": platform.release(),
        "kernel_version": platform.version(),
        "docker": docker("version", "--format", "{{.Server.Version}}").stdout.strip(),
        "environment": "simulated: one x86_64 PC, Docker bridge networks, no Raspberry Pi or ESP32",
    }


def loadavg() -> list[float]:
    return [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]


def write_result(name: str, data: dict) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps({**data, "machine": machine_info()}, indent=2) + "\n", encoding="utf-8")
    return path
