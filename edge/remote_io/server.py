#!/usr/bin/env python3
"""Remote I/O, simulated: a Modbus TCP server standing in for the ESP32 in firmware/esp32.

Same register map, same fencing and watchdog rules as firmware/esp32/lib/io_core/io_core.cpp, and the same
conformance test (tests/test_modbus_conformance.py) runs against both. The field side is a UDP link to the
plant simulator instead of GPIO. The sim-control port and the event log exist only here, for measurement.
"""
from __future__ import annotations

import asyncio
import collections
import math
import os
import random
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import minihttp, regmap  # noqa: E402

EX_ILLEGAL_FUNCTION, EX_ILLEGAL_ADDRESS, EX_ILLEGAL_VALUE, EX_BUSY = 1, 2, 3, 6
ACK_PULSE_MS = regmap.TIMING["ack_pulse_ms"]
TICK_S = regmap.TIMING["tick_ms"] / 1000.0
CONTROL_BASE, CONTROL_COUNT = regmap.span(regmap.group("control"))
CKPT_BASE, CKPT_COUNT = regmap.span(regmap.group("checkpoint"))
SET_BASE, SET_COUNT = regmap.span(regmap.group("setpoints"))
SETPOINTS = regmap.group("setpoints")


def now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


class IoCore:
    """Everything that decides what the outputs do. One asyncio thread, so every request is atomic."""

    def __init__(self, wd_timeout_ms: int, lease_ttl_ms: int):
        self.wd_timeout_ms, self.lease_ttl_ms = wd_timeout_ms, lease_ttl_ms
        # A random start means a token from before a reboot cannot match by accident.
        self.epoch = random.randint(1, 0xFFF0)
        self.holder = 0
        self.reserved_for = 0
        self.reserved_until = 0
        self.last_control_ms = 0
        self.have_control = False  # True once any control write has been accepted.
        self.outputs = [False, False]
        self.wd_tripped = False
        self.rejected = self.accepted = self.wd_trips = self.grants = 0
        self.boot_ms = now_ms()
        self.heartbeat = 0
        self.ack = False
        self.ack_since = 0
        self.field = {"level": 0.0, "flow": 0.0, "fb1": 0, "fb2": 0, "trip1": 0, "trip2": 0, "auto": 1}
        self.setpoints = [w for r in SETPOINTS for w in regmap.real_words(r["default"])]
        self.control = [0] * CONTROL_COUNT
        self.checkpoint = [0] * CKPT_COUNT
        self.events: collections.deque = collections.deque(maxlen=200_000)
        self.seq = 0
        self.on_output_change = lambda: None

    def log(self, kind: str, **data) -> None:
        self.seq += 1
        self.events.append({"seq": self.seq, "t_ns": time.monotonic_ns(), "kind": kind, **data})

    # Periodic work

    def tick(self) -> None:
        now = now_ms()
        self.heartbeat = (self.heartbeat + 1) & 0xFFFF
        if self.ack and now - self.ack_since >= ACK_PULSE_MS:
            self.ack = False
        if self.reserved_for and now >= self.reserved_until:
            self.reserved_for = 0
        if self.have_control and not self.wd_tripped and now - self.last_control_ms > self.wd_timeout_ms:
            self.wd_tripped = True
            self.wd_trips += 1
            self.log("wd_trip", epoch=self.epoch, outputs=list(self.outputs))
            self._set_outputs(False, False)

    def _set_outputs(self, one: bool, two: bool) -> None:
        if [one, two] != self.outputs:
            self.outputs = [one, two]
            self.log("output", out1=one, out2=two)
            self.on_output_change()

    # Register images

    def input_registers(self) -> list[int]:
        now = now_ms()
        f = self.field
        words = [0] * 32
        words[0:2] = regmap.real_words(f["level"])
        words[2:4] = regmap.real_words(f["flow"])
        words[4:9] = [f["fb1"], f["fb2"], f["trip1"], f["trip2"], f["auto"]]
        words[9] = self.heartbeat
        words[10] = int(self.ack)
        words[16] = self.epoch
        words[17] = self.holder
        words[18] = min(now - self.last_control_ms, 65535)
        words[19] = int(self.wd_tripped)
        words[20], words[21] = int(self.outputs[0]), int(self.outputs[1])
        words[22] = self.rejected & 0xFFFF
        words[23] = self.accepted & 0xFFFF
        words[24] = self.wd_trips & 0xFFFF
        words[25] = self.grants & 0xFFFF
        words[26] = ((now - self.boot_ms) // 1000) & 0xFFFF
        words[27] = regmap.MAP["version"]
        words[28] = self.wd_timeout_ms
        words[29] = self.lease_ttl_ms
        words[30] = self.reserved_for
        return words

    def holding(self, addr: int, count: int) -> list[int] | None:
        for base, block in ((SET_BASE, self.setpoints), (CONTROL_BASE, self.control), (CKPT_BASE, self.checkpoint)):
            if base <= addr and addr + count <= base + len(block):
                return block[addr - base:addr - base + count]
        return None

    # Requests

    def handle_pdu(self, pdu: bytes) -> bytes:
        """One Modbus request PDU to one response PDU."""
        function = pdu[0] if pdu else 0
        try:
            return self._dispatch(function, pdu)
        except _Refused as refused:
            return bytes([function | 0x80, refused.code])
        except (struct.error, IndexError):
            return bytes([function | 0x80, EX_ILLEGAL_VALUE])

    def _dispatch(self, function: int, pdu: bytes) -> bytes:
        if function in (3, 4):
            addr, count = struct.unpack(">HH", pdu[1:5])
            if not 1 <= count <= 125:
                raise _Refused(EX_ILLEGAL_VALUE)
            if function == 4:
                image = self.input_registers()
                if addr + count > len(image):
                    raise _Refused(EX_ILLEGAL_ADDRESS)
                words = image[addr:addr + count]
            else:
                words = self.holding(addr, count)
                if words is None:
                    raise _Refused(EX_ILLEGAL_ADDRESS)
            return bytes([function, 2 * count]) + struct.pack(f">{count}H", *words)
        if function == 1:
            addr, count = struct.unpack(">HH", pdu[1:5])
            if addr != 0 or count != 1:
                raise _Refused(EX_ILLEGAL_ADDRESS)
            return bytes([1, 1, int(self.ack)])
        if function == 5:
            addr, value = struct.unpack(">HH", pdu[1:5])
            if addr != 0:
                raise _Refused(EX_ILLEGAL_ADDRESS)
            if value not in (0, 0xFF00):
                raise _Refused(EX_ILLEGAL_VALUE)
            self.ack = bool(value)
            if value:
                self.ack_since = now_ms()
                self.log("ack")
            return pdu[:5]
        if function == 16:
            addr, count, size = struct.unpack(">HHB", pdu[1:6])
            if size != 2 * count or len(pdu) != 6 + size:
                raise _Refused(EX_ILLEGAL_VALUE)
            self._write_block(addr, list(struct.unpack(f">{count}H", pdu[6:6 + size])))
            return pdu[:5]
        raise _Refused(EX_ILLEGAL_FUNCTION)

    def _write_block(self, addr: int, words: list[int]) -> None:
        count = len(words)
        if addr == 90 and count == 2:
            self._lease_request(words[0], words[1])
        elif addr == 92 and count == 3:
            self._lease_release(words[0], words[1], words[2])
        elif addr == SET_BASE and count == SET_COUNT:
            self._write_setpoints(words)
        elif addr == CONTROL_BASE and count == CONTROL_COUNT:
            self._control_write(words)
        elif addr == CKPT_BASE and count == CKPT_COUNT:
            if not self._token_ok(words[0], "ckpt"):
                raise _Refused(EX_BUSY)
            self.checkpoint = words
        else:
            raise _Refused(EX_ILLEGAL_ADDRESS)

    def _token_ok(self, token: int, block: str) -> bool:
        if self.holder != 0 and token == self.epoch:
            return True
        self.rejected += 1
        self.log("reject", block=block, token=token, epoch=self.epoch)
        return False

    def _control_write(self, words: list[int]) -> None:
        if not self._token_ok(words[0], "control"):
            raise _Refused(EX_BUSY)
        self.control = words
        self.accepted += 1
        self.last_control_ms = now_ms()
        self.have_control = True
        self.log("accept", epoch=words[0], pump1=words[1], pump2=words[2], state=words[3], lead2=words[4],
                 high=words[5], fault=words[6], comms=words[7], sensor=words[8], scan=words[16])
        if self.wd_tripped:
            self.wd_tripped = False
            self.log("wd_clear", epoch=words[0])
        self._set_outputs(words[1] != 0, words[2] != 0)

    def _lease_request(self, node: int, expected_epoch: int) -> None:
        now = now_ms()
        if node == 0 or expected_epoch != self.epoch:
            raise _Refused(EX_BUSY)
        if self.holder != 0:
            free = now - self.last_control_ms > self.lease_ttl_ms
        else:
            free = self.reserved_for in (0, node)
        if not free:
            raise _Refused(EX_BUSY)
        self.epoch = self.epoch + 1 if self.epoch < 0xFFFF else 1
        self.holder = node
        self.reserved_for = 0
        self.last_control_ms = now
        self.grants += 1
        self.log("grant", epoch=self.epoch, node=node)

    def _lease_release(self, node: int, epoch: int, next_node: int) -> None:
        if node == 0 or node != self.holder or epoch != self.epoch:
            raise _Refused(EX_BUSY)
        self.holder = 0
        self.reserved_for = next_node
        self.reserved_until = now_ms() + self.lease_ttl_ms
        self.log("release", epoch=epoch, node=node, next=next_node)

    def _write_setpoints(self, words: list[int]) -> None:
        values = regmap.decode(SETPOINTS, words, SET_BASE)
        for reg in SETPOINTS:
            value = values[reg["name"]]
            if not math.isfinite(value) or not reg["min"] <= value <= reg["max"]:
                raise _Refused(EX_ILLEGAL_VALUE)
        ordered = [values[n] for n in ("STOP_LEVEL", "START_LEVEL", "LAG_LEVEL", "HIGH_LEVEL")]
        if ordered != sorted(ordered) or len(set(ordered)) != 4:
            raise _Refused(EX_ILLEGAL_VALUE)
        self.setpoints = words
        self.log("setpoints", **values)


class _Refused(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


async def serve_client(core: IoCore, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    sock = writer.get_extra_info("socket")
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        while True:
            header = await reader.readexactly(7)
            tid, proto, length, unit = struct.unpack(">HHHB", header)
            if proto != 0 or not 2 <= length <= 254:
                break
            pdu = await reader.readexactly(length - 1)
            response = core.handle_pdu(pdu)
            writer.write(struct.pack(">HHHB", tid, 0, len(response) + 1, unit) + response)
            await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        writer.close()


class FieldLink(asyncio.DatagramProtocol):
    """The simulated wires: "S level flow fb1 fb2 trip1 trip2 auto" in, "O out1 out2" out."""

    def __init__(self, core: IoCore, plant_addr: tuple[str, int]):
        self.core, self.plant_addr = core, plant_addr
        self.transport = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        parts = data.decode().split()
        if len(parts) == 8 and parts[0] == "S":
            self.core.field.update(
                level=float(parts[1]), flow=float(parts[2]), fb1=int(parts[3]), fb2=int(parts[4]),
                trip1=int(parts[5]), trip2=int(parts[6]), auto=int(parts[7]),
            )

    def send_outputs(self) -> None:
        if self.transport is not None:
            one, two = self.core.outputs
            self.transport.sendto(f"O {int(one)} {int(two)}".encode(), self.plant_addr)


async def main() -> None:
    core = IoCore(
        int(os.environ.get("WD_TIMEOUT_MS", regmap.TIMING["wd_timeout_ms"])),
        int(os.environ.get("LEASE_TTL_MS", regmap.TIMING["lease_ttl_ms"])),
    )
    loop = asyncio.get_running_loop()
    plant = (socket.gethostbyname(os.environ.get("PLANT_HOST", "plant")), int(os.environ.get("PLANT_PORT", 5021)))
    _, field = await loop.create_datagram_endpoint(lambda: FieldLink(core, plant), local_addr=("0.0.0.0", 5020))
    core.on_output_change = field.send_outputs

    def get_events(query, _body):
        since = int(query.get("since", 0))
        return 200, {"last": core.seq, "events": [e for e in list(core.events) if e["seq"] > since]}

    def set_config(_query, body):
        core.wd_timeout_ms = int(body.get("wd_timeout_ms", core.wd_timeout_ms))
        core.lease_ttl_ms = int(body.get("lease_ttl_ms", core.lease_ttl_ms))
        return 200, {"wd_timeout_ms": core.wd_timeout_ms, "lease_ttl_ms": core.lease_ttl_ms}

    minihttp.serve(int(os.environ.get("SIM_PORT", 8101)), {
        "GET /events": get_events,
        "GET /state": lambda q, b: (200, {"epoch": core.epoch, "holder": core.holder, "outputs": core.outputs,
                                          "wd_tripped": core.wd_tripped, "last": core.seq,
                                          "wd_timeout_ms": core.wd_timeout_ms, "lease_ttl_ms": core.lease_ttl_ms}),
        "POST /config": set_config,
    })

    server = await asyncio.start_server(lambda r, w: serve_client(core, r, w), "0.0.0.0", int(os.environ.get("MODBUS_PORT", 502)))
    print(f"remote_io: SIMULATED ESP32, epoch {core.epoch}, wd {core.wd_timeout_ms} ms, lease {core.lease_ttl_ms} ms", flush=True)

    next_tick = time.monotonic()
    async with server:
        while True:
            core.tick()
            field.send_outputs()
            next_tick += TICK_S
            await asyncio.sleep(max(0.0, next_tick - time.monotonic()))


if __name__ == "__main__":
    asyncio.run(main())
