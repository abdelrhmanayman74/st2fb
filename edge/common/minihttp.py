"""Tiny JSON-over-HTTP server for sim-control and agent endpoints, standard library only."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def serve(port: int, routes, host: str = "0.0.0.0", token: str | None = None) -> ThreadingHTTPServer:
    """routes maps "GET /path" to fn(query: dict, body: dict) -> (status, jsonable). Runs in a thread."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self):
            url = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            route = routes.get(f"{self.command} {url.path}")
            if token is not None and self.headers.get("Authorization") != f"Bearer {token}":
                status, out = 401, {"error": "unauthorized"}
            elif route is None:
                status, out = 404, {"error": "not found"}
            else:
                try:
                    query = {k: v[-1] for k, v in parse_qs(url.query).items()}
                    status, out = route(query, json.loads(raw) if raw else {})
                except (ValueError, KeyError, TypeError) as exc:
                    status, out = 400, {"error": str(exc)}
            data = json.dumps(out).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = _handle

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
