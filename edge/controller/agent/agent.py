#!/usr/bin/env python3
"""Node agent: runs FORTE in this container, contends for the lease, opens the gate when it wins.

It never computes control output. The agent decides only who is allowed to control; the scan runs in FORTE.
States:
  BARE    FORTE runs with no application (a node waiting to receive the logic).
  SHADOW  The application runs on live inputs with GATE closed: no writes reach the I/O.
  ACTIVE  This node holds the lease; GATE is open and PACK.EPOCH carries the fencing token.

Takeover: wait until the lease is free, request it (compare-and-swap at the I/O), read the checkpoint the old
holder left at the I/O, load it into the shadow FB through DEV_MGR, set the token, open the gate.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import mbtcp, minihttp, regmap  # noqa: E402

from . import app  # noqa: E402
from .devmgr import DevMgr, DevMgrError  # noqa: E402

FORTE = os.environ.get("FORTE_BIN", "/opt/forte/forte")
LOOP_S = float(os.environ.get("AGENT_LOOP_S", 0.02))  # Raise for a real ESP32 on Wi-Fi: see docs/EDGE.md.
CHECKPOINT_PERIOD_S = 0.2
CONTROL = regmap.group("control")
CONTROL_BASE, CONTROL_COUNT = regmap.span(CONTROL)
CKPT = regmap.group("checkpoint")
CKPT_BASE, CKPT_COUNT = regmap.span(CKPT)
LEASE_FIRST, LEASE_COUNT = 16, 15


def log(message: str) -> None:
    print(f"agent[{os.environ.get('NODE_ID', '?')}] {time.monotonic():.3f} {message}", flush=True)


class Agent:
    def __init__(self):
        self.node = int(os.environ["NODE_ID"])
        self.contend = os.environ.get("ROLE", "contender") == "contender"
        self.io_ip, self.io_port = app.io_endpoint()
        self.app = app.definition(self.io_ip, self.io_port)
        self.state = "BARE"
        self.epoch = 0
        self.lock = threading.RLock()
        self.mgr = DevMgr()
        self.mgr_port = 61498
        self.io = mbtcp.Client(self.io_ip, self.io_port, timeout=0.15)
        self.forte: subprocess.Popen | None = None
        self.last_deploy_ms: float | None = None
        self.last_takeover: dict | None = None
        self.takeovers = 0
        self.demotions = 0
        self.last_lease: dict = {}
        self.io_ok = False
        self.comms_ok = False
        self.comms_checked = 0.0
        self.last_checkpoint = 0.0
        self.force_gate = False
        self.start_forte()

    # FORTE process

    def start_forte(self) -> None:
        self.mgr.close()
        # A new port each start: FORTE sets no SO_REUSEADDR, so a killed FORTE blocks its port for a minute.
        self.mgr_port = self.mgr_port + 1 if self.mgr_port < 61598 else 61499
        self.mgr.port = self.mgr_port
        cmd = [FORTE, "-c", f"127.0.0.1:{self.mgr_port}"]
        if os.environ.get("FORTE_RT") == "1":
            cmd = ["chrt", "-f", "50", *cmd]
        self.forte = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
        deadline = time.monotonic() + 5.0
        while True:
            try:
                self.mgr.request("", '<Request ID="0" Action="QUERY"><FB Name="*" Type="*"/></Request>')
                return
            except (OSError, DevMgrError):
                self.mgr.close()
                if time.monotonic() > deadline:
                    raise SystemExit("FORTE did not open its management port")
                time.sleep(0.005)

    def deploy_shadow(self) -> None:
        with self.lock:
            if self.state != "BARE":
                return
            started = time.monotonic()
            app.deploy(self.mgr, self.app)
            self.last_deploy_ms = (time.monotonic() - started) * 1000
            self.state = "SHADOW"
            self.comms_ok = False
            log(f"deployed {app.digest(self.app)} in {self.last_deploy_ms:.1f} ms")

    def undeploy(self) -> None:
        """Back to an empty runtime. A process restart is the clean way: FORTE's Modbus layer does not close."""
        with self.lock:
            self.stop_forte()
            self.state = "BARE"
            self.epoch = 0
            self.start_forte()

    def stop_forte(self) -> None:
        if self.forte is not None:
            self.forte.kill()
            self.forte.wait()

    # Lease

    def read_lease(self) -> dict | None:
        try:
            words = self.io.read_input(LEASE_FIRST, LEASE_COUNT)
        except mbtcp.ModbusError:
            self.io_ok = False
            return None
        self.io_ok = True
        self.last_lease = regmap.decode(list(regmap.IR.values()), words, LEASE_FIRST)
        return self.last_lease

    def shadow_healthy(self) -> bool:
        """Do not take control of a plant this node cannot see: GUARD must report a live heartbeat."""
        now = time.monotonic()
        if now - self.comms_checked > 0.1:
            self.comms_checked = now
            try:
                self.comms_ok = self.mgr.read(app.RESOURCE, "GUARD.COMMS_OK") == "TRUE"
            except DevMgrError:
                self.comms_ok = False
        return self.comms_ok

    def lease_free(self, lease: dict) -> bool:
        if lease["LEASE_HOLDER"] == 0:
            return lease["RESERVED_FOR"] in (0, self.node)
        return lease["LEASE_AGE_MS"] > lease["LEASE_TTL_MS"]

    def take_over(self, lease: dict) -> None:
        t_detect = time.monotonic()
        try:
            self.io.write_registers(90, [self.node, lease["LEASE_EPOCH"]])
        except mbtcp.ModbusException:
            return  # Lost the race, or the holder came back. The compare-and-swap decides.
        except mbtcp.ModbusError:
            return
        epoch = (lease["LEASE_EPOCH"] + 1) if lease["LEASE_EPOCH"] < 0xFFFF else 1
        t_grant = time.monotonic()
        # Read after the grant: from here on the old holder cannot change what is read.
        loaded = self.load_checkpoint()
        t_loaded = time.monotonic()
        self.mgr.write(app.RESOURCE, str(epoch), "PACK.EPOCH")
        self.mgr.write(app.RESOURCE, "TRUE", "GATE.PERMIT")
        t_open = time.monotonic()
        self.epoch = epoch
        self.state = "ACTIVE"
        self.takeovers += 1
        self.last_checkpoint = t_open
        self.last_takeover = {
            "epoch": epoch, "previous_holder": lease["LEASE_HOLDER"], "state_loaded": loaded,
            "grant_ms": round((t_grant - t_detect) * 1000, 2),
            "load_ms": round((t_loaded - t_grant) * 1000, 2),
            "open_ms": round((t_open - t_loaded) * 1000, 2),
        }
        log(f"ACTIVE epoch {epoch} {self.last_takeover}")

    def load_checkpoint(self) -> dict | None:
        """Copy what the old holder left at the I/O into the shadow FB. See docs/EDGE.md, state transfer."""
        words = self.io.read_holding(CONTROL_BASE, CONTROL_COUNT)
        control = regmap.decode(CONTROL, words, CONTROL_BASE)
        if control["TOKEN"] == 0:
            return None  # Nobody has ever controlled this I/O.
        ckpt = regmap.decode(CKPT, self.io.read_holding(CKPT_BASE, CKPT_COUNT), CKPT_BASE)
        bool_text = lambda v: "TRUE" if v else "FALSE"  # noqa: E731
        state = [
            ("SUP.LEAD_IS_2", bool_text(control["LEAD_IS_2"])),
            ("SUP.TOTAL", repr(control["TOTAL"])),
            ("SUP.PULSES", str(control["PULSES"])),
            ("SUP.STARTS", str(control["STARTS"])),
            # The shadow may have a proof timer running or expired on a state it only imagined.
            ("SUP.PROOF_TIMER_Q", "FALSE"),
            ("SUP.PROOF_TIMER_STATE", "0"),
            ("SUP.PROOF_TIMER_PREV_IN", "FALSE"),
            ("SUP.PROOF_TIMER_ET", "T#0s"),
        ]
        if ckpt["CKPT_TOKEN"] != 0:
            state += [
                ("SUP.FAILED_1_Q1", bool_text(ckpt["CKPT_FAILED_1"])),
                ("SUP.FAILED_2_Q1", bool_text(ckpt["CKPT_FAILED_2"])),
                ("SUP.PENDING", repr(ckpt["CKPT_PENDING"])),
            ]
        # STATE_NO goes last. A scan that lands between these writes then still sees a consistent old state.
        state.append(("SUP.STATE_NO", str(control["STATE_NO"])))
        for destination, value in state:
            self.mgr.write(app.RESOURCE, value, destination)
        return {"STATE_NO": control["STATE_NO"], "LEAD_IS_2": control["LEAD_IS_2"], "TOTAL": control["TOTAL"],
                "PULSES": control["PULSES"], "STARTS": control["STARTS"], "FAILED_1": ckpt["CKPT_FAILED_1"],
                "FAILED_2": ckpt["CKPT_FAILED_2"], "from_epoch": control["TOKEN"]}

    def close_gate(self) -> None:
        self.mgr.write(app.RESOURCE, "FALSE", "GATE.PERMIT")
        self.mgr.write(app.RESOURCE, "0", "PACK.EPOCH")

    def demote(self, reason: str) -> None:
        self.close_gate()
        log(f"SHADOW: {reason}")
        self.state = "SHADOW"
        self.epoch = 0
        self.demotions += 1

    def write_checkpoint(self) -> None:
        """Latches the FB has no output pin for. They need READ through DEV_MGR, so this is periodic, not per scan."""
        failed_1 = self.mgr.read(app.RESOURCE, "SUP.FAILED_1_Q1") == "TRUE"
        failed_2 = self.mgr.read(app.RESOURCE, "SUP.FAILED_2_Q1") == "TRUE"
        pending = float(self.mgr.read(app.RESOURCE, "SUP.PENDING"))
        try:
            self.io.write_registers(CKPT_BASE, [self.epoch, int(failed_1), int(failed_2), *regmap.real_words(pending)])
        except mbtcp.ModbusError:
            pass

    def handover(self, to_node: int) -> dict:
        """Planned move: gate shut, final checkpoint, release with a reservation for the target."""
        with self.lock:
            if self.state != "ACTIVE":
                return {"error": "not active", "state": self.state}
            t0 = time.monotonic()
            self.write_checkpoint()
            self.mgr.write(app.RESOURCE, "FALSE", "GATE.PERMIT")
            # A scan already past GATE may still write. The release below makes such a write harmless.
            self.io.write_registers(92, [self.node, self.epoch, to_node])
            self.mgr.write(app.RESOURCE, "0", "PACK.EPOCH")
            self.state, self.epoch = "SHADOW", 0
            self.contend = False  # The source must not race for the lease it gave away.
            return {"handover_ms": round((time.monotonic() - t0) * 1000, 2)}

    # Main loop

    def step(self) -> None:
        with self.lock:
            if self.forte.poll() is not None:
                log(f"FORTE exited with {self.forte.returncode}; restarting")
                self.state, self.epoch = "BARE", 0
                self.start_forte()
                if self.contend:
                    self.deploy_shadow()
                return
            lease = self.read_lease()
            if lease is None or self.state == "BARE":
                return
            if self.state == "ACTIVE":
                if lease["LEASE_EPOCH"] != self.epoch or lease["LEASE_HOLDER"] != self.node:
                    self.demote(f"lease now epoch {lease['LEASE_EPOCH']} holder {lease['LEASE_HOLDER']}")
                elif time.monotonic() - self.last_checkpoint >= CHECKPOINT_PERIOD_S:
                    self.last_checkpoint = time.monotonic()
                    self.write_checkpoint()
            elif self.state == "SHADOW" and self.contend and self.lease_free(lease) and self.shadow_healthy():
                self.take_over(lease)

    def status(self) -> dict:
        with self.lock:
            scan = {}
            if self.state != "BARE":
                for name in ("SUP.STATE_NO", "SUP.LEAD_IS_2", "SUP.FAILED_1_Q1", "SUP.FAILED_2_Q1", "SUP.TOTAL",
                             "SUP.PULSES", "SUP.STARTS", "SUP.FILTERED_LEVEL", "GUARD.COMMS_OK", "GUARD.SENSOR_FAULT",
                             "CYCLE.DT", "SUP.SCAN_DT", "GATE.PERMIT", "PACK.EPOCH", "PROBE.SCAN_COUNT"):
                    try:
                        scan[name] = self.mgr.read(app.RESOURCE, name)
                    except DevMgrError as exc:
                        scan[name] = f"error: {exc}"
            return {"node": self.node, "state": self.state, "epoch": self.epoch, "contend": self.contend,
                    "io_ok": self.io_ok, "lease": self.last_lease, "app_digest": app.digest(self.app),
                    "last_deploy_ms": self.last_deploy_ms, "last_takeover": self.last_takeover,
                    "takeovers": self.takeovers, "demotions": self.demotions, "scan": scan,
                    "force_gate": self.force_gate}

    # Control endpoints, token protected, reachable on the OT network only

    def http_deploy(self, _query, body) -> tuple[int, dict]:
        with self.lock:
            self.contend = bool(body.get("contend", True))
            self.deploy_shadow()
            return 200, {"state": self.state, "deploy_ms": self.last_deploy_ms, "app_digest": app.digest(self.app)}

    def http_undeploy(self, _query, _body) -> tuple[int, dict]:
        if self.state == "ACTIVE":
            return 409, {"error": "active node: hand over first"}
        started = time.monotonic()
        self.undeploy()
        return 200, {"state": self.state, "undeploy_ms": round((time.monotonic() - started) * 1000, 2)}

    def http_handover(self, _query, body) -> tuple[int, dict]:
        result = self.handover(int(body["to"]))
        return (409 if "error" in result else 200), result

    def http_contend(self, _query, body) -> tuple[int, dict]:
        self.contend = bool(body["contend"])
        return 200, {"contend": self.contend}

    def http_force_gate(self, _query, body) -> tuple[int, dict]:
        """Test hook for split-brain experiments: open the gate with any token, bypassing the lease."""
        if os.environ.get("ALLOW_TEST_HOOKS") != "1":
            return 403, {"error": "test hooks disabled"}
        with self.lock:
            self.mgr.write(app.RESOURCE, str(int(body["token"])), "PACK.EPOCH")
            self.mgr.write(app.RESOURCE, "TRUE" if body["open"] else "FALSE", "GATE.PERMIT")
            self.force_gate = bool(body["open"])
            return 200, {"force_gate": self.force_gate}

    def serve(self) -> None:
        minihttp.serve(int(os.environ.get("AGENT_PORT", 8081)), {
            "GET /status": lambda q, b: (200, self.status()),
            "POST /deploy": self.http_deploy,
            "POST /undeploy": self.http_undeploy,
            "POST /handover": self.http_handover,
            "POST /contend": self.http_contend,
            "POST /test/force_gate": self.http_force_gate,
        }, token=os.environ["AGENT_TOKEN"])


def main() -> int:
    agent = Agent()
    agent.serve()
    if agent.contend:
        agent.deploy_shadow()
    log(f"node {agent.node} {agent.state}, I/O {agent.io_ip}:{agent.io_port}, contend={agent.contend}")
    while True:
        started = time.monotonic()
        try:
            agent.step()
        except (DevMgrError, OSError, ValueError) as exc:
            log(f"step: {exc}")
        time.sleep(max(0.0, LOOP_S - (time.monotonic() - started)))


if __name__ == "__main__":
    sys.exit(main())
