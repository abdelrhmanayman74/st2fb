"""Small blocking Modbus TCP client (FC1, FC3, FC4, FC5, FC16), used by the agent and the gateway.

Kept dependency-free so the controller image needs no pip. The tests cross-check it, and the server,
against pymodbus and against libmodbus (FORTE).
"""
from __future__ import annotations

import socket
import struct


class ModbusError(OSError):
    pass


class ModbusException(ModbusError):
    """The server answered with a Modbus exception code."""

    def __init__(self, function: int, code: int):
        super().__init__(f"function {function}: exception code {code}")
        self.function = function
        self.code = code


class Client:
    def __init__(self, host: str, port: int, unit: int = 1, timeout: float = 0.25):
        self.host, self.port, self.unit, self.timeout = host, port, unit, timeout
        self.sock: socket.socket | None = None
        self.tid = 0

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def _recv(self, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise ModbusError("connection closed")
            data += chunk
        return data

    def request(self, pdu: bytes) -> bytes:
        """One transaction. Any transport error closes the socket; the next call reconnects."""
        try:
            if self.sock is None:
                self._connect()
            self.tid = (self.tid + 1) & 0xFFFF
            self.sock.sendall(struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, self.unit) + pdu)
            tid, _, length, _ = struct.unpack(">HHHB", self._recv(7))
            body = self._recv(length - 1)
        except OSError as exc:
            self.close()
            raise ModbusError(str(exc)) from exc
        if tid != self.tid:
            self.close()
            raise ModbusError("transaction id mismatch")
        if body[0] & 0x80:
            raise ModbusException(pdu[0], body[1])
        return body

    def _read_words(self, function: int, addr: int, count: int) -> list[int]:
        body = self.request(struct.pack(">BHH", function, addr, count))
        return list(struct.unpack(f">{count}H", body[2:2 + 2 * count]))

    def read_input(self, addr: int, count: int) -> list[int]:
        return self._read_words(4, addr, count)

    def read_holding(self, addr: int, count: int) -> list[int]:
        return self._read_words(3, addr, count)

    def read_coils(self, addr: int, count: int) -> list[bool]:
        body = self.request(struct.pack(">BHH", 1, addr, count))
        return [bool(body[2 + i // 8] >> (i % 8) & 1) for i in range(count)]

    def write_coil(self, addr: int, value: bool) -> None:
        self.request(struct.pack(">BHH", 5, addr, 0xFF00 if value else 0))

    def write_registers(self, addr: int, words: list[int]) -> None:
        payload = struct.pack(f">{len(words)}H", *[w & 0xFFFF for w in words])
        self.request(struct.pack(">BHHB", 16, addr, len(words), len(payload)) + payload)
