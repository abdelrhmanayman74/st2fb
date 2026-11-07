"""The IEC 61499 application, as data. Every node deploys exactly this list through DEV_MGR.

Only IO_HOST and IO_PORT say where the I/O is, and they are the same on every node. That is the
software-defined part: the logic is a deployable artefact and the wiring stays on the network.

Scan event chain, one thread, run to completion:

  CYCLE.EO -> PROBE.REQ -> PROBE.CNF -> GUARD.REQ -> GUARD.CNF -> SUP.REQ -> SUP.CNF -> PACK.REQ -> PACK.CNF
           -> GATE.EI -> GATE.EO -> SPLIT.EI -> SPLIT.EO1 -> IO.REQ (blocking FC16)
                                             -> SPLIT.EO2 -> PROBE.END

IO is one Modbus CLIENT FB: a poll thread inside FORTE refreshes its RD pins every POLL_MS with two FC reads,
and SD_1..17 are written with one FC16 on each permitted scan. RD pins feed the FBs through data connections,
sampled when REQ arrives. So the control path is: input register -> FORTE poll -> GUARD and SUP -> FC16 -> relay.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket

RESOURCE = "EMB_RES"
SCAN_MS = 100
POLL_MS = int(os.environ.get("POLL_MS", 50))  # Raise for a real ESP32 on Wi-Fi: see docs/EDGE.md.
PROOF_TIME = "T#3s"
ALARM_DELAY = "T#5s"
COMMS_TIMEOUT = "T#500ms"
STUCK_TIME = "T#10s"
STUCK_EPS = "0.0001"
PULSE_SIZE = "1.0"

_INPUTS = ["RAW_LEVEL", "FLOW", "FB_1", "FB_2", "TRIP_1", "TRIP_2", "AUTO", "HEARTBEAT", "ACK"]
_SETPOINTS = ["STOP_LEVEL", "START_LEVEL", "LAG_LEVEL", "HIGH_LEVEL"]
RD_COUNT = len(_INPUTS) + len(_SETPOINTS)
SD_COUNT = 17


def modbus_id(io_ip: str, io_port: int) -> str:
    # The layer takes a dotted IP only (CModbusComLayer::isIp), and the read list must be in RD order.
    return f"modbus[tcp:{io_ip}:{io_port}:1:{POLL_MS}:i0..10,h100..107:h200..219]"


def definition(io_ip: str, io_port: int) -> dict:
    """FBs, parameter writes and connections. Plain data, so it can be hashed and compared across nodes."""
    fbs = [
        ("CYCLE", "iec61499::events::E_CYCLE"),
        ("PROBE", "st2fb::SCAN_PROBE"),
        ("GUARD", "st2fb::IO_GUARD"),
        ("SUP", "st2fb::PUMP_STATION_SUPERVISOR"),
        ("PACK", "st2fb::OUTPUT_PACK"),
        ("GATE", "iec61499::events::E_PERMIT"),
        ("SPLIT", "iec61499::events::E_SPLIT"),
        ("IO", f"iec61499::net::CLIENT_{SD_COUNT}_{RD_COUNT}"),
    ]
    scan = f"T#{SCAN_MS}ms"
    writes = [
        ("TRUE", "IO.QI"),
        (modbus_id(io_ip, io_port), "IO.ID"),
        (scan, "CYCLE.DT"),
        (scan, "SUP.SCAN_DT"),
        (scan, "GUARD.SCAN_DT"),
        (repr(SCAN_MS / 3_600_000.0), "SUP.SCAN_HOURS"),
        (PULSE_SIZE, "SUP.PULSE_SIZE"),
        (PROOF_TIME, "SUP.PROOF_TIME"),
        (ALARM_DELAY, "SUP.ALARM_DELAY"),
        (COMMS_TIMEOUT, "GUARD.COMMS_TIMEOUT"),
        (STUCK_TIME, "GUARD.STUCK_TIME"),
        (STUCK_EPS, "GUARD.STUCK_EPS"),
        ("0", "PACK.EPOCH"),
        ("FALSE", "GATE.PERMIT"),
    ]
    events = [
        ("START.COLD", "IO.INIT"), ("START.WARM", "IO.INIT"),
        ("IO.INITO", "CYCLE.START"),
        ("CYCLE.EO", "PROBE.REQ"), ("PROBE.CNF", "GUARD.REQ"), ("GUARD.CNF", "SUP.REQ"),
        ("SUP.CNF", "PACK.REQ"), ("PACK.CNF", "GATE.EI"), ("GATE.EO", "SPLIT.EI"),
        ("SPLIT.EO1", "IO.REQ"), ("SPLIT.EO2", "PROBE.END"),
    ]
    rd = {name: f"IO.RD_{i}" for i, name in enumerate(_INPUTS + _SETPOINTS, start=1)}
    data = [
        (rd["AUTO"], "GUARD.R_AUTO"), (rd["ACK"], "GUARD.R_ACK"), (rd["FB_1"], "GUARD.R_FB_1"),
        (rd["FB_2"], "GUARD.R_FB_2"), (rd["TRIP_1"], "GUARD.R_TRIP_1"), (rd["TRIP_2"], "GUARD.R_TRIP_2"),
        (rd["HEARTBEAT"], "GUARD.HEARTBEAT"), (rd["RAW_LEVEL"], "GUARD.RAW_LEVEL"),
        (rd["RAW_LEVEL"], "SUP.RAW_LEVEL"), (rd["FLOW"], "SUP.FLOW"),
        (rd["STOP_LEVEL"], "SUP.STOP_LEVEL"), (rd["START_LEVEL"], "SUP.START_LEVEL"),
        (rd["LAG_LEVEL"], "SUP.LAG_LEVEL"), (rd["HIGH_LEVEL"], "SUP.HIGH_LEVEL"),
        ("GUARD.AUTO_MODE", "SUP.AUTO_MODE"), ("GUARD.ACK", "SUP.ACK"), ("GUARD.FB_1", "SUP.FB_1"),
        ("GUARD.FB_2", "SUP.FB_2"), ("GUARD.TRIP_1", "SUP.TRIP_1"), ("GUARD.TRIP_2", "SUP.TRIP_2"),
        ("SUP.PUMP_1", "PACK.PUMP_1"), ("SUP.PUMP_2", "PACK.PUMP_2"), ("SUP.STATE_NO", "PACK.STATE_NO"),
        ("SUP.LEAD_IS_2", "PACK.LEAD_IS_2"), ("SUP.HIGH_ALARM", "PACK.HIGH_ALARM"),
        ("SUP.STATION_FAULT", "PACK.STATION_FAULT"), ("GUARD.COMMS_OK", "PACK.COMMS_OK"),
        ("GUARD.SENSOR_FAULT", "PACK.SENSOR_FAULT"),
    ]
    packed = ["W_TOKEN", "W_PUMP_1", "W_PUMP_2", "W_STATE_NO", "W_LEAD_IS_2", "W_HIGH_ALARM", "W_STATION_FAULT",
              "W_COMMS_OK", "W_SENSOR_FAULT"]
    sources = [f"PACK.{p}" for p in packed] + [
        "SUP.FILTERED_LEVEL", "SUP.TOTAL", "SUP.PULSES", "SUP.STARTS",
        "PROBE.SCAN_COUNT", "PROBE.LAST_DT_10US", "PROBE.MAX_DT_10US", "PROBE.LAST_EXEC_US",
    ]
    assert len(sources) == SD_COUNT
    data += [(source, f"IO.SD_{i}") for i, source in enumerate(sources, start=1)]
    # Parameter overrides, used only by the real-time versus deterministic test.
    overrides = json.loads(os.environ.get("APP_OVERRIDES") or "{}")
    writes = [(overrides.get(destination, value), destination) for value, destination in writes]
    return {"fbs": fbs, "writes": writes, "events": events, "data": data}


def digest(app: dict) -> str:
    return hashlib.sha256(json.dumps(app, sort_keys=True).encode()).hexdigest()[:16]


def deploy(mgr, app: dict) -> None:
    """Create the resource and the network, then start. Ordered as a 4diac IDE deployment."""
    mgr.create_fb("", RESOURCE, "iec61499::system::EMB_RES")
    for name, fb_type in app["fbs"]:
        mgr.create_fb(RESOURCE, name, fb_type)
    for value, destination in app["writes"]:
        mgr.write(RESOURCE, value, destination)
    for source, destination in app["events"] + app["data"]:
        mgr.connect(RESOURCE, source, destination)
    mgr.start(RESOURCE)


def io_endpoint() -> tuple[str, int]:
    return socket.gethostbyname(os.environ.get("IO_HOST", "remote-io")), int(os.environ.get("IO_PORT", 502))
