#!/usr/bin/env python3
"""Plant, simulated: digital twin of a wet well with two discharge pumps.

Mass balance:  A dL/dt = Qin - w1 Qmax - w2 Qmax    (A in m2, Q in m3/s, w = relative pump speed 0..1)
Pump dynamics: dw/dt = (cmd - w) / tau,  tau_up on acceleration, tau_down on coast-down.
Inflow: base flow plus a slow sinusoid, like a diurnal pattern sped up so a pumping cycle takes minutes.
Sensors reach the remote I/O over a UDP link that stands for wires. Relay commands come back the same way;
without them for FIELD_LOSS_S the relays are taken as de-energised, as with a powered-off I/O module.

The sim-control port on 8100 sets disturbances and injects faults. Nothing like it exists on real hardware.
"""
from __future__ import annotations

import collections
import math
import os
import random
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import minihttp  # noqa: E402

AREA_M2 = 1.0
HEIGHT_M = 6.0
QMAX_M3H = 180.0
TAU_UP_S = 1.5
TAU_DOWN_S = 2.5
FB_THRESHOLD = 0.3
FIELD_LOSS_S = 0.2
STEP_S = 0.01
SENSOR_PERIOD_S = 0.02
TRACE_PERIOD_S = 0.02
ADC_LSB_M = HEIGHT_M / 4096
NOISE_M = 0.002


class Plant:
    def __init__(self, initial_level: float):
        self.lock = threading.Lock()
        self.level = initial_level
        self.w = [0.0, 0.0]
        self.cmd = [False, False]
        self.last_rx = 0.0
        self.base_inflow = float(os.environ.get("INFLOW_M3H", 90.0))
        self.swing = float(os.environ.get("INFLOW_SWING_M3H", 10.0))
        self.swing_period = 120.0
        self.faults = {"sensor_stuck": False, "pump_fail_1": False, "pump_fail_2": False,
                       "trip_1": False, "trip_2": False, "auto_switch": True}
        self.stuck_value = None
        self.overflowed = False
        self.dry_run_s = 0.0
        self.t0 = time.monotonic()
        self.trace: collections.deque = collections.deque(maxlen=120_000)
        self.max_level = initial_level

    def inflow(self, t: float) -> float:
        return max(0.0, self.base_inflow + self.swing * math.sin(2 * math.pi * (t - self.t0) / self.swing_period))

    def step(self, dt: float, t: float) -> None:
        with self.lock:
            cmds = self.cmd if t - self.last_rx <= FIELD_LOSS_S else [False, False]
            for i in range(2):
                failed = self.faults[f"pump_fail_{i + 1}"] or self.faults[f"trip_{i + 1}"]
                target = 1.0 if cmds[i] and not failed else 0.0
                tau = TAU_UP_S if target > self.w[i] else TAU_DOWN_S
                self.w[i] += (target - self.w[i]) * min(1.0, dt / tau)
            qout = (self.w[0] + self.w[1]) * QMAX_M3H
            if self.level <= 0.0 and qout > 0.0:
                self.dry_run_s += dt
                qout = 0.0
            self.level += (self.inflow(t) - qout) / 3600.0 * dt / AREA_M2
            if self.level > HEIGHT_M:
                self.level, self.overflowed = HEIGHT_M, True
            self.level = max(0.0, self.level)
            self.max_level = max(self.max_level, self.level)

    def sensors(self) -> str:
        with self.lock:
            if self.faults["sensor_stuck"]:
                if self.stuck_value is None:
                    self.stuck_value = self.reading()
                level = self.stuck_value
            else:
                self.stuck_value = None
                level = self.reading()
            flow = (self.w[0] + self.w[1]) * QMAX_M3H
            fb = [int(self.w[i] > FB_THRESHOLD and not self.faults[f"pump_fail_{i + 1}"]) for i in range(2)]
            return (f"S {level:.5f} {flow:.3f} {fb[0]} {fb[1]} {int(self.faults['trip_1'])} "
                    f"{int(self.faults['trip_2'])} {int(self.faults['auto_switch'])}")

    def reading(self) -> float:
        noisy = self.level + random.gauss(0.0, NOISE_M)
        return round(noisy / ADC_LSB_M) * ADC_LSB_M

    def sample(self, t_ns: int, t: float) -> dict:
        return {"t_ns": t_ns, "level": round(self.level, 5), "cmd1": self.cmd[0], "cmd2": self.cmd[1],
                "w1": round(self.w[0], 4), "w2": round(self.w[1], 4), "qin": round(self.inflow(t), 2)}


def physics_loop(plant: Plant, sock: socket.socket, remote_io: tuple[str, int]) -> None:
    last = next_step = time.monotonic()
    next_sensor = next_trace = last
    while True:
        now = time.monotonic()
        plant.step(now - last, now)
        last = now
        if now >= next_sensor:
            next_sensor += SENSOR_PERIOD_S
            try:
                sock.sendto(plant.sensors().encode(), remote_io)
            except OSError:
                pass
        if now >= next_trace:
            next_trace += TRACE_PERIOD_S
            with plant.lock:
                plant.trace.append(plant.sample(time.monotonic_ns(), now))
        next_step += STEP_S
        time.sleep(max(0.0, next_step - time.monotonic()))


def rx_loop(plant: Plant, sock: socket.socket) -> None:
    while True:
        parts = sock.recv(64).decode().split()
        if len(parts) == 3 and parts[0] == "O":
            with plant.lock:
                plant.cmd = [parts[1] == "1", parts[2] == "1"]
                plant.last_rx = time.monotonic()


def main() -> None:
    plant = Plant(float(os.environ.get("INITIAL_LEVEL_M", 2.0)))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 5021))
    host = os.environ.get("REMOTE_IO_HOST", "remote-io")

    def resolve() -> tuple[str, int]:
        while True:
            try:
                return socket.gethostbyname(host), 5020
            except OSError:
                time.sleep(0.2)

    def get_trace(query, _body):
        since = int(query.get("since_ns", 0))
        with plant.lock:
            rows = [r for r in plant.trace if r["t_ns"] > since]
        return 200, {"rows": rows}

    def get_state(_query, _body):
        with plant.lock:
            now = time.monotonic()
            return 200, {**plant.sample(time.monotonic_ns(), now), "faults": dict(plant.faults),
                         "overflowed": plant.overflowed, "max_level": plant.max_level,
                         "dry_run_s": plant.dry_run_s, "simulated": True}

    def post_fault(_query, body):
        with plant.lock:
            for key, value in body.items():
                if key not in plant.faults:
                    raise ValueError(f"unknown fault {key}")
                plant.faults[key] = bool(value)
            return 200, dict(plant.faults)

    def post_config(_query, body):
        with plant.lock:
            plant.base_inflow = float(body.get("base_inflow", plant.base_inflow))
            plant.swing = float(body.get("swing", plant.swing))
            if "level" in body:
                plant.level = float(body["level"])
            if body.get("reset_max"):
                plant.max_level = plant.level
                plant.overflowed = False
            return 200, {"base_inflow": plant.base_inflow, "swing": plant.swing, "level": plant.level}

    minihttp.serve(int(os.environ.get("SIM_PORT", 8100)), {
        "GET /state": get_state, "GET /trace": get_trace, "POST /fault": post_fault, "POST /config": post_config,
    })
    threading.Thread(target=rx_loop, args=(plant, sock), daemon=True).start()
    print(f"plant: SIMULATED wet well, area {AREA_M2} m2, height {HEIGHT_M} m, two pumps {QMAX_M3H} m3/h", flush=True)
    physics_loop(plant, sock, resolve())


if __name__ == "__main__":
    main()
