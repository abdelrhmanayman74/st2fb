"""Client for FORTE's management port (DEV_MGR), the same protocol the 4diac IDE uses to deploy.

Request frame:  STRING(destination) STRING(xml); response frame: STRING(xml). In FBDK ASN.1 a STRING is
tag 0x50, a big-endian 16-bit length, then the bytes. See core/src/cominfra/fbdkasn1layer.cpp in FORTE.
"""
from __future__ import annotations

import re
import socket
import struct
from xml.sax.saxutils import escape

_STRING_TAG = 0x50
_REASON = re.compile(r'Reason="([^"]*)"')
_READ_VALUE = re.compile(r'Destination="([^"]*)"')


class DevMgrError(RuntimeError):
    pass


class DevMgr:
    def __init__(self, host: str = "127.0.0.1", port: int = 61499, timeout: float = 1.0):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock: socket.socket | None = None
        self.next_id = 1

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def _recv(self, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise DevMgrError("FORTE closed the management connection")
            data += chunk
        return data

    def request(self, destination: str, body: str) -> str:
        if self.sock is None:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        frame = b""
        for text in (destination, body):
            raw = text.encode()
            frame += struct.pack(">BH", _STRING_TAG, len(raw)) + raw
        try:
            self.sock.sendall(frame)
            tag, length = struct.unpack(">BH", self._recv(3))
            if tag != _STRING_TAG:
                raise DevMgrError(f"unexpected response tag {tag}")
            return self._recv(length).decode()
        except OSError as exc:
            self.close()
            raise DevMgrError(str(exc)) from exc

    def _command(self, destination: str, action: str, inner: str = "") -> str:
        number = self.next_id
        self.next_id += 1
        body = f'<Request ID="{number}" Action="{action}">{inner}</Request>' if inner else f'<Request ID="{number}" Action="{action}"/>'
        response = self.request(destination, body)
        reason = _REASON.search(response)
        if reason:
            raise DevMgrError(f"{action} {inner or destination}: {reason.group(1)}")
        return response

    def create_fb(self, resource: str, name: str, fb_type: str) -> None:
        self._command(resource, "CREATE", f'<FB Name="{name}" Type="{fb_type}"/>')

    def connect(self, resource: str, source: str, destination: str) -> None:
        self._command(resource, "CREATE", f'<Connection Source="{source}" Destination="{destination}"/>')

    def write(self, resource: str, value: str, destination: str) -> None:
        quoted = escape(value, {'"': "&quot;"})
        self._command(resource, "WRITE", f'<Connection Source="{quoted}" Destination="{destination}"/>')

    def read(self, resource: str, source: str) -> str:
        response = self._command(resource, "READ", f'<Connection Source="{source}" Destination="*"/>')
        match = _READ_VALUE.search(response)
        if match is None:
            raise DevMgrError(f"READ {source}: no value in {response}")
        return match.group(1)

    def start(self, resource: str) -> None:
        self._command(resource, "START")
