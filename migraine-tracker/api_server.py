"""HTTP API (stdlib only)."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import data_store as store
import settings as cfg
from migraine_store import add_entry, delete_entry, list_entries

log = logging.getLogger(__name__)


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    if cfg.REQUIRE_API_TOKEN and not cfg.API_TOKEN:
        log.error("REQUIRE_API_TOKEN set but API_TOKEN empty")
        return False
    if not cfg.API_TOKEN:
        return True
    auth = handler.headers.get("Authorization", "")
    if auth == f"Bearer {cfg.API_TOKEN}":
        return True
    if handler.headers.get("X-API-Token") == cfg.API_TOKEN:
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

    def _send_bytes(
        self, status: int, data: bytes, content_type: str, download_name: str | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        _cors_headers(self)
        if download_name:
            self.send_header(
                "Content-Disposition", f'attachment; filename="{download_name}"'
            )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path in ("/api/health", "/api/config"):
            pass
        elif not _check_auth(self):
            self._send_json(401, {"error": "unauthorized"})
            return

        if path == "/api/health":
            self._send_json(200, {"ok": True})
        elif path == "/api/config":
            self._send_json(200, cfg.public_config())
        elif path == "/api/status":
            status = store.load_status()
            status["heartbeat_age_seconds"] = store.heartbeat_age_seconds()
            self._send_json(200, status)
        elif path == "/api/pressure":
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo

            log_data = store.load_pressure_log()
            days = int(parse_qs(urlparse(self.path).query).get("days", ["30"])[0])
            tz = ZoneInfo(cfg.TIMEZONE)
            now = datetime.now(tz)
            start = now - timedelta(days=days)
            readings = [
                r
                for r in log_data.get("readings", [])
                if store.parse_reading_time(r["time"]) >= start
            ]
            self._send_json(
                200,
                {
                    "updated": log_data.get("updated"),
                    "location": log_data.get("location"),
                    "readings": readings,
                },
            )
        elif path == "/api/migraines":
            entries = []
            for e in list_entries():
                item = dict(e)
                item["correlation"] = store.correlate_migraine_time(e["time"])
                entries.append(item)
            self._send_json(200, {"entries": entries})
        elif path == "/api/export":
            csv_data = store.build_export_csv().encode("utf-8")
            self._send_bytes(200, csv_data, "text/csv", "migraine-pressure-export.csv")
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not _check_auth(self):
            self._send_json(401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path.rstrip("/")
        if path != "/api/migraines":
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
        entry = add_entry(str(time_val), str(note), cfg.TIMEZONE)
        correlation = store.correlate_migraine_time(str(time_val))
        self._send_json(201, {"entry": entry, "correlation": correlation})

    def do_DELETE(self) -> None:
        if not _check_auth(self):
            self._send_json(401, {"error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/api/migraines":
            self._send_json(404, {"error": "not found"})
            return
        qs = parse_qs(parsed.query)
        time_vals = qs.get("time", [])
        if not time_vals:
            self._send_json(400, {"error": "time query param required"})
            return
        if delete_entry(time_vals[0], cfg.TIMEZONE):
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})


def start_api_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", cfg.API_PORT), MigraineAPIHandler)
    thread = threading.Thread(
        target=server.serve_forever, daemon=True, name="migraine-api"
    )
    thread.start()
    log.info("API listening on port %s", cfg.API_PORT)
    if cfg.REQUIRE_API_TOKEN and not cfg.API_TOKEN:
        log.warning("REQUIRE_API_TOKEN=true but API_TOKEN is empty")
    return server
