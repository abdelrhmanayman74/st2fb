#!/usr/bin/env python3
"""IT/OT gateway: the only service on both networks, the single conduit between them.

OT side:  polls the remote I/O over Modbus TCP, and writes setpoints and ACK. Those are the only two write
          paths in this file, both validated again here. The control block is never written from here.
IT side:  publishes tags on MQTT, serves them read-only over OPC UA, ships history to the TSDB, and answers
          the API on a token-protected HTTP port.

Failure rule: the controller never depends on this process. Each IT sink has its own thread or task and its
failures stay there, so a dead broker, TSDB or OPC UA client does not delay the Modbus poll.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paho.mqtt.client as mqtt  # noqa: E402
from asyncua import Server, ua  # noqa: E402

from common import mbtcp, minihttp, regmap  # noqa: E402

POLL_S = 0.2
PUBLISH_S = 1.0
STALE_S = 2.0
TOPIC = os.environ.get("MQTT_TOPIC", "st2fb/station1")
SETPOINTS = regmap.group("setpoints")
SET_BASE, SET_COUNT = regmap.span(SETPOINTS)
CONTROL = regmap.group("control")
CONTROL_BASE, CONTROL_COUNT = regmap.span(CONTROL)
INPUTS = list(regmap.IR.values())
# Tags offered upward. Raw lease and scan details are grouped for the health panel.
PROCESS_TAGS = ["RAW_LEVEL", "FLOW", "FB_1", "FB_2", "TRIP_1", "TRIP_2", "AUTO_SWITCH", "OUTPUT_1", "OUTPUT_2",
                "STATE_NO", "LEAD_IS_2", "HIGH_ALARM", "STATION_FAULT", "SENSOR_FAULT", "COMMS_OK",
                "FILTERED_LEVEL", "TOTAL", "PULSES", "STARTS", "STOP_LEVEL", "START_LEVEL", "LAG_LEVEL", "HIGH_LEVEL"]
HEALTH_TAGS = ["LEASE_EPOCH", "LEASE_HOLDER", "LEASE_AGE_MS", "WD_TRIPPED", "WD_TRIPS", "GRANTS", "REJECTED", "ACCEPTED",
               "HEARTBEAT", "SCAN_COUNT", "LAST_DT_10US", "MAX_DT_10US", "LAST_EXEC_US", "WD_TIMEOUT_MS", "LEASE_TTL_MS"]
ALL_TAGS = PROCESS_TAGS + HEALTH_TAGS


def log(message: str) -> None:
    print(f"gateway {time.strftime('%H:%M:%S')} {message}", flush=True)


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.tags: dict = {}
        self.last_poll = 0.0
        self.io_errors = 0
        self.mqtt_connected = False
        self.mqtt_published = 0
        self.tsdb_ok = False
        self.tsdb_written = 0
        self.opcua_ok = False
        self.started = time.time()

    def snapshot(self) -> dict:
        with self.lock:
            age = time.monotonic() - self.last_poll if self.last_poll else None
            return {
                "simulated": True,
                "tags": dict(self.tags),
                "io_link_ok": age is not None and age < STALE_S,
                "io_age_s": None if age is None else round(age, 3),
                "io_errors": self.io_errors,
                "mqtt_connected": self.mqtt_connected,
                "mqtt_published": self.mqtt_published,
                "tsdb_ok": self.tsdb_ok,
                "opcua_ok": self.opcua_ok,
                "gateway_uptime_s": round(time.time() - self.started, 1),
            }


class Poller(threading.Thread):
    def __init__(self, state: State, host: str, port: int):
        super().__init__(daemon=True)
        self.state = state
        self.io = mbtcp.Client(host, port, timeout=0.3)
        self.write_lock = threading.Lock()

    def run(self) -> None:
        was_ok = None
        while True:
            started = time.monotonic()
            try:
                with self.write_lock:
                    inputs = self.io.read_input(0, 31)
                    setpoints = self.io.read_holding(SET_BASE, SET_COUNT)
                    control = self.io.read_holding(CONTROL_BASE, CONTROL_COUNT)
                tags = {**regmap.decode(INPUTS, inputs, 0),
                        **regmap.decode(SETPOINTS, setpoints, SET_BASE),
                        **regmap.decode(CONTROL, control, CONTROL_BASE)}
                with self.state.lock:
                    self.state.tags = tags
                    self.state.last_poll = time.monotonic()
                if was_ok is not True:
                    log("I/O link up")
                was_ok = True
            except mbtcp.ModbusError as exc:
                with self.state.lock:
                    self.state.io_errors += 1
                if was_ok is not False:
                    log(f"I/O link down: {exc}")
                was_ok = False
            time.sleep(max(0.0, POLL_S - (time.monotonic() - started)))

    def write_setpoints(self, values: dict) -> None:
        names = [r["name"] for r in SETPOINTS]
        words = [w for name in names for w in regmap.real_words(values[name])]
        with self.write_lock:
            self.io.write_registers(SET_BASE, words)

    def ack(self) -> None:
        with self.write_lock:
            self.io.write_coil(0, True)


def validate_setpoints(body: dict) -> dict:
    """Allow-list: exactly the four setpoints, finite, in range and strictly ordered."""
    names = [r["name"] for r in SETPOINTS]
    if set(body) != set(names):
        raise ValueError(f"expected exactly {names}")
    values = {}
    for reg in SETPOINTS:
        value = body[reg["name"]]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{reg['name']} must be a finite number")
        if not reg["min"] <= value <= reg["max"]:
            raise ValueError(f"{reg['name']} must be within {reg['min']}..{reg['max']}")
        values[reg["name"]] = float(value)
    if not values["STOP_LEVEL"] < values["START_LEVEL"] < values["LAG_LEVEL"] < values["HIGH_LEVEL"]:
        raise ValueError("levels must satisfy STOP < START < LAG < HIGH")
    return values


class MqttPublisher(threading.Thread):
    def __init__(self, state: State):
        super().__init__(daemon=True)
        self.state = state
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="st2fb-gateway")
        self.client.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
        self.client.will_set(f"{TOPIC}/gateway/status", "offline", qos=1, retain=True)
        self.client.reconnect_delay_set(min_delay=1, max_delay=5)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect

    def on_connect(self, client, _userdata, _flags, reason, _props=None) -> None:
        ok = not reason.is_failure
        with self.state.lock:
            self.state.mqtt_connected = ok
        log(f"MQTT connected: {reason}")
        if ok:
            client.publish(f"{TOPIC}/gateway/status", "online", qos=1, retain=True)

    def on_disconnect(self, _client, _userdata, _flags, reason, _props=None) -> None:
        with self.state.lock:
            self.state.mqtt_connected = False
        log(f"MQTT disconnected: {reason}")

    def run(self) -> None:
        self.client.connect_async(os.environ.get("MQTT_HOST", "mosquitto"), int(os.environ.get("MQTT_PORT", 1883)), keepalive=10)
        self.client.loop_start()
        while True:
            started = time.monotonic()
            snap = self.state.snapshot()
            if snap["mqtt_connected"] and snap["io_link_ok"]:
                for name in ALL_TAGS:
                    if name in snap["tags"]:
                        self.client.publish(f"{TOPIC}/tags/{name}", json.dumps(snap["tags"][name]), retain=True)
                self.client.publish(f"{TOPIC}/state", json.dumps({"t": time.time(), "simulated": True, **snap["tags"]}))
                with self.state.lock:
                    self.state.mqtt_published += 1
            time.sleep(max(0.0, PUBLISH_S - (time.monotonic() - started)))


class TsdbWriter(threading.Thread):
    def __init__(self, state: State):
        super().__init__(daemon=True)
        self.state = state
        self.url = os.environ.get("TSDB_URL", "http://tsdb:8428") + "/api/v1/import/prometheus"

    def run(self) -> None:
        while True:
            started = time.monotonic()
            snap = self.state.snapshot()
            if snap["io_link_ok"]:
                stamp = int(time.time() * 1000)
                lines = [f"st2fb_{name.lower()} {float(snap['tags'][name])} {stamp}" for name in ALL_TAGS if name in snap["tags"]]
                try:
                    urllib.request.urlopen(urllib.request.Request(self.url, "\n".join(lines).encode(), method="POST"), timeout=0.5).read()
                    ok = True
                except OSError:
                    ok = False
                with self.state.lock:
                    self.state.tsdb_ok = ok
            time.sleep(max(0.0, PUBLISH_S - (time.monotonic() - started)))


async def opcua_server(state: State) -> None:
    """Read-only OPC UA view through asyncua. No security policy; bound to localhost by compose. See docs/EDGE.md."""
    logging.getLogger("asyncua").setLevel(logging.ERROR)
    server = Server()
    await server.init()
    server.set_endpoint("opc.tcp://0.0.0.0:4840/st2fb/")
    server.set_server_name("st2fb edge gateway (simulated)")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    index = await server.register_namespace("urn:st2fb:edge:simulated")
    station = await server.nodes.objects.add_object(index, "Station1")
    nodes = {}
    for name in ALL_TAGS:
        nodes[name] = await station.add_variable(ua.NodeId(name, index), name, 0.0, ua.VariantType.Double)
    async with server:
        with state.lock:
            state.opcua_ok = True
        log("OPC UA serving on 4840")
        while True:
            tags = state.snapshot()["tags"]
            for name, node in nodes.items():
                if name in tags:
                    await node.write_value(float(tags[name]), ua.VariantType.Double)
            await asyncio.sleep(0.5)


def main() -> None:
    state = State()
    poller = Poller(state, os.environ.get("IO_HOST", "172.30.0.20"), int(os.environ.get("IO_PORT", 502)))
    poller.start()
    MqttPublisher(state).start()
    TsdbWriter(state).start()

    def post_setpoints(_query, body):
        values = validate_setpoints(body)
        try:
            poller.write_setpoints(values)
        except mbtcp.ModbusException as exc:
            return 422, {"error": f"refused by the I/O: code {exc.code}"}
        except mbtcp.ModbusError as exc:
            return 503, {"error": f"I/O unreachable: {exc}"}
        return 200, {"written": values}

    def post_ack(_query, _body):
        try:
            poller.ack()
        except mbtcp.ModbusError as exc:
            return 503, {"error": f"I/O unreachable: {exc}"}
        return 200, {"ack": True}

    minihttp.serve(8090, {
        "GET /state": lambda q, b: (200, state.snapshot()),
        "POST /setpoints": post_setpoints,
        "POST /ack": post_ack,
    }, token=os.environ["GATEWAY_TOKEN"])
    log("up")
    asyncio.run(opcua_server(state))


if __name__ == "__main__":
    main()
