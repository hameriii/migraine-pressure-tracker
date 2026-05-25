"""Minimal HTTP API for migraine log entries (stdlib only)."""

from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from migraine_store import add_entry, delete_entry, list_entries

log = logging.getLogger(__name__)

API_PORT = int(os.environ.get("API_PORT", "8780"))
API_TOKEN = os.environ.get("API_TOKEN", "").strip()
TIMEZONE = os.environ.get("TIMEZONE", "UTC")


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    if not API_TOKEN:
        return True
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {API_TOKEN}":
        return True
    if handler.headers.get("X-API-Token") == API_TOKEN:
        return True
    return False


def _cors_headers(handler: BaseHTTPRequestHandler) -> None:
    origin = handler.headers.get("Origin", "*")
    handler.send_header("Access-Control-Allow-Origin", origin or "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    handler.send_header(
        "Access-Control-Allow-Headers",
        "Content-Type, Authorization, X-API-Token",
    )
    handler.send_header("Access-Control-Max-Age", "86400")


class MigraineAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        _cors_headers(self)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        _cors_headers(self)
        self.end_headers()

    def do_GET(self) -> None:
        if not _check_auth(self):
            self._send_json(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        if path == "/api/migraines" or path == "/api/migraines/":
            self._send_json(200, {"entries": list_entries()})
            return
        if path == "/api/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not _check_auth(self):
            self._send_json(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        if path not in ("/api/migraines", "/api/migraines/"):
            self._send_json(404, {"error": "not found"})
            return
        body = self._read_json_body()
        if body is None:
            self._send_json(400, {"error": "invalid JSON"})
            return
        time_val = body.get("time")
        if not time_val:
            self._send_json(400, {"error": "time required"})
            return
        note = body.get("note", "")
        entry = add_entry(str(time_val), str(note), TIMEZONE)
        self._send_json(201, {"entry": entry})

    def do_DELETE(self) -> None:
        if not _check_auth(self):
            self._send_json(401, {"error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/migraines", "/api/migraines/"):
            self._send_json(404, {"error": "not found"})
            return
        qs = parse_qs(parsed.query)
        time_vals = qs.get("time", [])
        if not time_vals:
            self._send_json(400, {"error": "time query param required"})
            return
        removed = delete_entry(time_vals[0], TIMEZONE)
        if removed:
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})


def start_api_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), MigraineAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="migraine-api")
    thread.start()
    log.info("Migraine log API listening on port %s", API_PORT)
    return server
