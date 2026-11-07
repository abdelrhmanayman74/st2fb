"""REST API and dashboard. It has no route to the OT network: everything goes through the gateway.

Reads need the viewer or operator token. Writes need the operator token, and there are exactly two:
setpoints and alarm acknowledge. There is no endpoint that can touch a pump, the lease or the control block.
"""
from __future__ import annotations

import collections
import hmac
import json
import math
import os
import time
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator

REGMAP = json.loads(Path(os.environ.get("ST2FB_REGMAP", "/app/regmap.json")).read_text(encoding="utf-8"))
_LIMITS = {r["name"]: (r["min"], r["max"]) for r in REGMAP["holding_registers"] if r.get("group") == "setpoints"}
LEVEL_MIN, LEVEL_MAX = _LIMITS["STOP_LEVEL"]

GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway:8090")
TSDB = os.environ.get("TSDB_URL", "http://tsdb:8428")
VIEWER_TOKEN = os.environ["API_VIEWER_TOKEN"]
OPERATOR_TOKEN = os.environ["API_OPERATOR_TOKEN"]
GATEWAY_HEADERS = {"Authorization": f"Bearer {os.environ['GATEWAY_TOKEN']}"}
WRITE_LIMIT_PER_MINUTE = 60
HISTORY_TAGS = ("raw_level", "filtered_level", "flow", "output_1", "output_2", "state_no", "total", "last_dt_10us", "lease_epoch")
STATE_NAMES = {0: "Off", 1: "Waiting for level", 2: "Lead starting", 3: "Lead running", 4: "Lead and lag running", 5: "Station fault"}
NODE_NAMES = {0: "none", 1: "ctrl-a", 2: "ctrl-b", 3: "ctrl-c"}

app = FastAPI(
    title="st2fb edge API (simulated plant)",
    version="1.0",
    description="Read tags, alarms, controller health and history. Write setpoints and acknowledge alarms. "
    "Demo on simulated equipment; not a certified control or safety system.",
)
_bearer = HTTPBearer(auto_error=False)
_client = httpx.Client(timeout=1.0)
_audit: collections.deque = collections.deque(maxlen=200)
_write_times: collections.deque = collections.deque()


def _role(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is None:
        return None
    token = credentials.credentials.encode()
    if hmac.compare_digest(token, OPERATOR_TOKEN.encode()):
        return "operator"
    if hmac.compare_digest(token, VIEWER_TOKEN.encode()):
        return "viewer"
    return None


def require_viewer(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    role = _role(credentials)
    if role is None:
        raise HTTPException(401, "missing or invalid bearer token", {"WWW-Authenticate": "Bearer"})
    return role


def require_operator(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    role = require_viewer(credentials)
    if role != "operator":
        raise HTTPException(403, "operator token required")
    return role


def _rate_limit() -> None:
    now = time.monotonic()
    while _write_times and now - _write_times[0] > 60:
        _write_times.popleft()
    if len(_write_times) >= WRITE_LIMIT_PER_MINUTE:
        raise HTTPException(429, "too many writes")
    _write_times.append(now)


def _gateway_state() -> dict:
    try:
        response = _client.get(f"{GATEWAY}/state", headers=GATEWAY_HEADERS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"gateway unavailable: {type(exc).__name__}") from exc
    return response.json()


def _times_ten(value: int | None) -> int | None:
    return None if value is None else value * 10


def _alarms(snapshot: dict) -> list[dict]:
    tags, alarms = snapshot["tags"], []

    def add(active: bool, code: str, text: str, severity: str) -> None:
        if active:
            alarms.append({"code": code, "text": text, "severity": severity})

    add(tags.get("STATION_FAULT", 0), "STATION_FAULT", "Both pumps failed, station latched off", "critical")
    add(tags.get("WD_TRIPPED", 0), "IO_WATCHDOG", "I/O watchdog tripped: outputs forced safe", "critical")
    add(tags.get("SENSOR_FAULT", 0), "SENSOR_STUCK", "Level sensor reading unchanged: pumps inhibited", "serious")
    add(tags.get("HIGH_ALARM", 0), "HIGH_LEVEL", "High level", "serious")
    add(tags.get("TRIP_1", 0), "TRIP_1", "Pump 1 tripped", "warning")
    add(tags.get("TRIP_2", 0), "TRIP_2", "Pump 2 tripped", "warning")
    add(not tags.get("AUTO_SWITCH", 1), "LOCAL_MANUAL", "Panel switch not in AUTO", "warning")
    add(not snapshot["io_link_ok"], "IO_LINK", "Gateway has no fresh data from the I/O", "serious")
    return alarms


@app.get("/healthz", tags=["system"])
def healthz() -> dict:
    """Liveness of this API process only. No plant data."""
    return {"status": "ok"}


@app.get("/api/v1/tags", tags=["read"])
def tags(_role_name: str = Depends(require_viewer)) -> dict:
    snapshot = _gateway_state()
    return {"simulated": True, "io_link_ok": snapshot["io_link_ok"], "age_s": snapshot["io_age_s"], "tags": snapshot["tags"]}


@app.get("/api/v1/alarms", tags=["read"])
def alarms(_role_name: str = Depends(require_viewer)) -> dict:
    return {"alarms": _alarms(_gateway_state())}


@app.get("/api/v1/health", tags=["read"])
def health(_role_name: str = Depends(require_viewer)) -> dict:
    snapshot = _gateway_state()
    tag = snapshot["tags"]
    return {
        "simulated": True,
        "controller": {
            "active_node": NODE_NAMES.get(tag.get("LEASE_HOLDER", 0), str(tag.get("LEASE_HOLDER"))),
            "epoch": tag.get("LEASE_EPOCH"),
            "lease_age_ms": tag.get("LEASE_AGE_MS"),
            "lease_ttl_ms": tag.get("LEASE_TTL_MS"),
            "scan_count": tag.get("SCAN_COUNT"),
            "last_dt_us": _times_ten(tag.get("LAST_DT_10US")),
            "max_dt_us": _times_ten(tag.get("MAX_DT_10US")),
            "last_exec_us": tag.get("LAST_EXEC_US"),
            "comms_ok": bool(tag.get("COMMS_OK", 0)),
            "state_no": tag.get("STATE_NO"),
            "state_name": STATE_NAMES.get(tag.get("STATE_NO"), "unknown"),
        },
        "remote_io": {
            "watchdog_tripped": bool(tag.get("WD_TRIPPED", 0)),
            "watchdog_trips": tag.get("WD_TRIPS"),
            "watchdog_timeout_ms": tag.get("WD_TIMEOUT_MS"),
            "takeovers_granted": tag.get("GRANTS"),
            "writes_accepted": tag.get("ACCEPTED"),
            "writes_rejected": tag.get("REJECTED"),
            "heartbeat": tag.get("HEARTBEAT"),
        },
        "gateway": {k: snapshot[k] for k in ("io_link_ok", "io_age_s", "io_errors", "mqtt_connected", "mqtt_published",
                                             "tsdb_ok", "opcua_ok", "gateway_uptime_s")},
    }


@app.get("/api/v1/history", tags=["read"])
def history(
    tag: Literal[HISTORY_TAGS] = Query("raw_level"),  # type: ignore[valid-type]
    minutes: int = Query(10, ge=1, le=1440),
    _role_name: str = Depends(require_viewer),
) -> dict:
    """Stored samples from the time-series database. The query is built from allow-listed parts only."""
    end = time.time()
    step = max(1, minutes * 60 // 300)
    try:
        response = _client.get(f"{TSDB}/api/v1/query_range", params={
            "query": f"st2fb_{tag}", "start": end - minutes * 60, "end": end, "step": f"{step}s",
        })
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"history unavailable: {type(exc).__name__}") from exc
    result = response.json()["data"]["result"]
    points = [[t, float(v)] for t, v in result[0]["values"]] if result else []
    return {"tag": tag, "step_s": step, "points": points}


@app.get("/api/v1/dashboard", tags=["read"])
def dashboard(_role_name: str = Depends(require_viewer)) -> dict:
    """Everything the dashboard page shows, in one request."""
    return {"tags": _gateway_state()["tags"], "alarms": alarms(), "health": health()}


class Setpoints(BaseModel):
    """All four levels together, because their ordering is the constraint that matters."""

    model_config = ConfigDict(extra="forbid")
    STOP_LEVEL: float = Field(ge=LEVEL_MIN, le=LEVEL_MAX, description="Pumps stop at or below this level, m")
    START_LEVEL: float = Field(ge=LEVEL_MIN, le=LEVEL_MAX, description="Lead pump starts at or above this level, m")
    LAG_LEVEL: float = Field(ge=LEVEL_MIN, le=LEVEL_MAX, description="Lag pump joins at or above this level, m")
    HIGH_LEVEL: float = Field(ge=LEVEL_MIN, le=LEVEL_MAX, description="High level alarm threshold, m")

    @model_validator(mode="after")
    def check_order(self) -> "Setpoints":
        values = [self.STOP_LEVEL, self.START_LEVEL, self.LAG_LEVEL, self.HIGH_LEVEL]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("levels must be finite")
        if not self.STOP_LEVEL < self.START_LEVEL < self.LAG_LEVEL < self.HIGH_LEVEL:
            raise ValueError("levels must satisfy STOP < START < LAG < HIGH")
        return self


@app.get("/api/v1/setpoints", tags=["read"])
def get_setpoints(_role_name: str = Depends(require_viewer)) -> dict:
    tag = _gateway_state()["tags"]
    return {name: tag.get(name) for name in _LIMITS}


def _forward(path: str, payload: dict | None, request: Request, action: str) -> dict:
    _rate_limit()
    client = request.client.host if request.client else "?"
    try:
        response = _client.post(f"{GATEWAY}{path}", headers=GATEWAY_HEADERS, json=payload or {})
    except httpx.HTTPError as exc:
        _audit.append({"t": time.time(), "action": action, "client": client, "result": "gateway unavailable"})
        raise HTTPException(503, f"gateway unavailable: {type(exc).__name__}") from exc
    _audit.append({"t": time.time(), "action": action, "payload": payload, "client": client, "result": response.status_code})
    print(f"AUDIT {action} {payload} from {client}: {response.status_code}", flush=True)
    if response.status_code != 200:
        raise HTTPException(502 if response.status_code >= 500 else 422, response.json().get("error", "refused"))
    return response.json()


@app.put("/api/v1/setpoints", tags=["write"])
def put_setpoints(body: Setpoints, request: Request, _role_name: str = Depends(require_operator)) -> dict:
    """Validated here, again in the gateway, and a third time by the I/O before it stores them."""
    return _forward("/setpoints", body.model_dump(), request, "setpoints")


@app.post("/api/v1/alarms/ack", tags=["write"])
def acknowledge(request: Request, _role_name: str = Depends(require_operator)) -> dict:
    """Pulse the ACK coil. The FB clears a latched pump failure on the rising edge, if the cause has gone."""
    return _forward("/ack", None, request, "ack")


@app.get("/api/v1/audit", tags=["read"])
def audit(_role_name: str = Depends(require_operator)) -> dict:
    return {"entries": list(_audit)}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(Path(__file__).with_name("static") / "index.html")
