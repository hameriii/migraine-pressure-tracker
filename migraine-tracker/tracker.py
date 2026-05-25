#!/usr/bin/env python3
"""Migraine barometric pressure tracker daemon."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

RAPID_ALERT_COOLDOWN_HOURS = 6
SUSTAINED_ALERT_COOLDOWN_HOURS = 12


def env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, default))


def env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


def env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


# --- Configuration ---
LATITUDE = env_float("LATITUDE", 63.83)
LONGITUDE = env_float("LONGITUDE", 20.26)
TIMEZONE = env_str("TIMEZONE", "Europe/Stockholm")

NTFY_URL = env_str("NTFY_URL", "")
NTFY_TOPIC = env_str("NTFY_TOPIC", "migraines")
NTFY_TOKEN = env_str("NTFY_TOKEN", "")
NTFY_USERNAME = env_str("NTFY_USERNAME", "")
NTFY_PASSWORD = env_str("NTFY_PASSWORD", "")

RAPID_DROP_HPA = env_float("RAPID_DROP_HPA", 3)
RAPID_DROP_HOURS = env_int("RAPID_DROP_HOURS", 3)
SUSTAINED_DROP_HPA = env_float("SUSTAINED_DROP_HPA", 6)
SUSTAINED_DROP_HOURS = env_int("SUSTAINED_DROP_HOURS", 12)
RISE_RECOVERY_HPA = env_float("RISE_RECOVERY_HPA", 2)
RISE_RECOVERY_HOURS = env_int("RISE_RECOVERY_HOURS", 3)

POLL_INTERVAL_MINUTES = env_int("POLL_INTERVAL_MINUTES", 60)
LOG_RETENTION_DAYS = env_int("LOG_RETENTION_DAYS", 30)
DATA_DIR = Path(env_str("DATA_DIR", "/data"))

PRESSURE_LOG_PATH = DATA_DIR / "pressure_log.json"
ALERT_STATE_PATH = DATA_DIR / "alert_state.json"
HEARTBEAT_PATH = DATA_DIR / "heartbeat"

DEFAULT_ALERT_STATE: dict[str, Any] = {
    "last_rapid_alert_time": None,
    "last_sustained_alert_time": None,
    "last_recovery_alert_time": None,
    "drop_alert_active": False,
    "peak_hpa_since_drop": None,
}


def handle_sigterm(sig: int, frame: Any) -> None:
    log.info("Received SIGTERM. Shutting down cleanly.")
    sys.exit(0)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def parse_open_meteo_times(
    times: list[str],
    pressures: list[float | None],
    utc_offset_seconds: int | None,
) -> list[dict[str, Any]]:
    """Parse hourly times into offset-aware ISO strings with hPa values."""
    tz = ZoneInfo(TIMEZONE)
    offset = timedelta(seconds=utc_offset_seconds or 0)
    readings: list[dict[str, Any]] = []

    for t_str, hpa in zip(times, pressures):
        if hpa is None:
            continue
        dt = _parse_time_string(t_str, offset, tz)
        readings.append({"time": dt.isoformat(), "hpa": round(float(hpa), 1)})

    return readings


def _parse_time_string(
    t_str: str,
    utc_offset: timedelta,
    tz: ZoneInfo,
) -> datetime:
    if len(t_str) >= 19 and (t_str[19] in "+-" or t_str.endswith("Z")):
        dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz)

    # Local time without offset from Open-Meteo when timezone param is set
    dt_naive = datetime.strptime(t_str[:16], "%Y-%m-%dT%H:%M")
    if utc_offset != timedelta(0):
        dt = dt_naive.replace(tzinfo=timezone(utc_offset)).astimezone(tz)
    else:
        dt = dt_naive.replace(tzinfo=tz)
    return dt


def fetch_forecast() -> list[dict[str, Any]]:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "surface_pressure",
        "timezone": TIMEZONE,
        "forecast_days": 2,
        "past_days": 7,
    }
    resp = requests.get(FORECAST_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    hourly = data["hourly"]
    return parse_open_meteo_times(
        hourly["time"],
        hourly["surface_pressure"],
        data.get("utc_offset_seconds"),
    )


def fetch_archive(start_date: str, end_date: str) -> list[dict[str, Any]]:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "surface_pressure",
        "timezone": TIMEZONE,
        "start_date": start_date,
        "end_date": end_date,
    }
    resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    hourly = data["hourly"]
    return parse_open_meteo_times(
        hourly["time"],
        hourly["surface_pressure"],
        data.get("utc_offset_seconds"),
    )


def fetch_pressure() -> list[dict[str, Any]]:
    return fetch_forecast()


def load_log() -> dict[str, Any]:
    if not PRESSURE_LOG_PATH.exists():
        return {
            "updated": None,
            "location": {
                "lat": LATITUDE,
                "lon": LONGITUDE,
                "timezone": TIMEZONE,
            },
            "readings": [],
        }
    with open(PRESSURE_LOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_alert_state() -> dict[str, Any]:
    if not ALERT_STATE_PATH.exists():
        return dict(DEFAULT_ALERT_STATE)
    with open(ALERT_STATE_PATH, encoding="utf-8") as f:
        state = json.load(f)
    for key, val in DEFAULT_ALERT_STATE.items():
        state.setdefault(key, val)
    return state


def save_alert_state(state: dict[str, Any]) -> None:
    atomic_write_json(ALERT_STATE_PATH, state)


def parse_reading_time(time_str: str) -> datetime:
    dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(TIMEZONE))
    return dt


def merge_readings(
    log: dict[str, Any],
    new_readings: list[dict[str, Any]],
) -> dict[str, Any]:
    by_time: dict[str, dict[str, Any]] = {
        r["time"]: r for r in log.get("readings", [])
    }
    for r in new_readings:
        by_time[r["time"]] = r

    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    cutoff = now - timedelta(days=LOG_RETENTION_DAYS)

    trimmed: list[dict[str, Any]] = []
    for t_key in sorted(by_time.keys()):
        if parse_reading_time(t_key) >= cutoff:
            trimmed.append(by_time[t_key])

    log["readings"] = trimmed
    log["location"] = {
        "lat": LATITUDE,
        "lon": LONGITUDE,
        "timezone": TIMEZONE,
    }
    log["updated"] = now.isoformat()
    return log


def save_log(log: dict[str, Any]) -> None:
    atomic_write_json(PRESSURE_LOG_PATH, log)


def touch_heartbeat() -> None:
    HEARTBEAT_PATH.touch()


def reading_at_hours_ago(
    readings: list[dict[str, Any]],
    hours: float,
) -> dict[str, Any] | None:
    if not readings:
        return None
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    target = now - timedelta(hours=hours)

    best: dict[str, Any] | None = None
    best_dt: datetime | None = None
    for r in readings:
        dt = parse_reading_time(r["time"])
        if dt <= target and (best_dt is None or dt > best_dt):
            best = r
            best_dt = dt
    return best


def current_reading(readings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not readings:
        return None
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    past = [r for r in readings if parse_reading_time(r["time"]) <= now]
    if past:
        return past[-1]
    return readings[-1]


def parse_alert_time(time_str: str | None) -> datetime | None:
    if not time_str:
        return None
    return parse_reading_time(time_str)


def hours_since_alert(last_time: str | None) -> float | None:
    if not last_time:
        return None
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    then = parse_alert_time(last_time)
    if then is None:
        return None
    return (now - then).total_seconds() / 3600


def min_hpa_since_drop(
    readings: list[dict[str, Any]],
    since: datetime,
) -> float | None:
    values = [
        r["hpa"]
        for r in readings
        if parse_reading_time(r["time"]) >= since
    ]
    return min(values) if values else None


def send_ntfy(
    url: str,
    topic: str,
    title: str,
    body: str,
    priority: str,
    tags: str,
    token: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> None:
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
        "Content-Type": "text/plain",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    auth = None
    if username and password:
        auth = (username, password)

    resp = requests.post(
        f"{url.rstrip('/')}/{topic}",
        data=body.encode("utf-8"),
        headers=headers,
        auth=auth,
        timeout=10,
    )
    resp.raise_for_status()


def notify(
    title: str,
    body: str,
    priority: str,
    tags: str,
) -> None:
    if not NTFY_URL or not NTFY_TOPIC:
        log.warning("NTFY_URL or NTFY_TOPIC not set; skipping notification")
        return

    token = NTFY_TOKEN or None
    username = NTFY_USERNAME or None
    password = NTFY_PASSWORD or None

    for attempt in range(2):
        try:
            send_ntfy(
                NTFY_URL,
                NTFY_TOPIC,
                title,
                body,
                priority,
                tags,
                token=token,
                username=username,
                password=password,
            )
            log.info("Notification sent: %s", title)
            return
        except requests.RequestException as e:
            log.error("ntfy failed (attempt %d): %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(30)


def check_and_alert(log: dict[str, Any]) -> None:
    readings = log.get("readings", [])
    current = current_reading(readings)
    if current is None:
        return

    current_hpa = current["hpa"]
    state = load_alert_state()
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)

    # Track peak while drop alert is active
    if state["drop_alert_active"]:
        peak = state.get("peak_hpa_since_drop")
        if peak is None:
            state["peak_hpa_since_drop"] = current_hpa
        else:
            state["peak_hpa_since_drop"] = max(peak, current_hpa)

    # --- Rapid drop ---
    past_rapid = reading_at_hours_ago(readings, RAPID_DROP_HOURS)
    if past_rapid is not None:
        delta_rapid = current_hpa - past_rapid["hpa"]
        if delta_rapid <= -RAPID_DROP_HPA:
            hours_since = hours_since_alert(state.get("last_rapid_alert_time"))
            if hours_since is None or hours_since >= RAPID_ALERT_COOLDOWN_HOURS:
                notify(
                    "⚠️ Pressure dropping fast",
                    (
                        f"Fell {abs(delta_rapid):.1f} hPa in {RAPID_DROP_HOURS}h — "
                        f"now {current_hpa:.1f} hPa. Migraine risk elevated."
                    ),
                    "high",
                    "warning,chart_with_downwards_trend",
                )
                state["last_rapid_alert_time"] = now.isoformat()
                state["drop_alert_active"] = True
                if state.get("peak_hpa_since_drop") is None:
                    state["peak_hpa_since_drop"] = current_hpa

    # --- Sustained drop ---
    past_sustained = reading_at_hours_ago(readings, SUSTAINED_DROP_HOURS)
    if past_sustained is not None:
        delta_sustained = current_hpa - past_sustained["hpa"]
        if delta_sustained <= -SUSTAINED_DROP_HPA:
            hours_since = hours_since_alert(state.get("last_sustained_alert_time"))
            if (
                hours_since is None
                or hours_since >= SUSTAINED_ALERT_COOLDOWN_HOURS
            ):
                notify(
                    "📉 Sustained pressure fall",
                    (
                        f"Down {abs(delta_sustained):.1f} hPa over "
                        f"{SUSTAINED_DROP_HOURS}h — now {current_hpa:.1f} hPa."
                    ),
                    "default",
                    "cloud_with_rain",
                )
                state["last_sustained_alert_time"] = now.isoformat()
                state["drop_alert_active"] = True
                if state.get("peak_hpa_since_drop") is None:
                    state["peak_hpa_since_drop"] = current_hpa

    # --- Recovery ---
    if state["drop_alert_active"]:
        past_recovery = reading_at_hours_ago(readings, RISE_RECOVERY_HOURS)
        recovery_fired = False

        if past_recovery is not None:
            delta_recovery = current_hpa - past_recovery["hpa"]
            if delta_recovery >= RISE_RECOVERY_HPA:
                recovery_fired = True

        # Also check rise from minimum since drop alerts began
        if not recovery_fired:
            drop_times = [
                t
                for t in (
                    state.get("last_rapid_alert_time"),
                    state.get("last_sustained_alert_time"),
                )
                if t
            ]
            if drop_times:
                since_drop = min(parse_alert_time(t) for t in drop_times if t)
                if since_drop:
                    low = min_hpa_since_drop(readings, since_drop)
                    if low is not None and (current_hpa - low) >= RISE_RECOVERY_HPA:
                        recovery_fired = True

        if recovery_fired:
            delta_display = RISE_RECOVERY_HPA
            if past_recovery is not None:
                delta_display = current_hpa - past_recovery["hpa"]
            notify(
                "✅ Pressure recovering",
                (
                    f"Up {delta_display:.1f} hPa in {RISE_RECOVERY_HOURS}h — "
                    f"now {current_hpa:.1f} hPa."
                ),
                "low",
                "sunny,white_check_mark",
            )
            state["last_recovery_alert_time"] = now.isoformat()
            state["drop_alert_active"] = False
            state["peak_hpa_since_drop"] = None

    save_alert_state(state)


def backfill_initial() -> dict[str, Any]:
    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    start = today - timedelta(days=30)

    log.info(
        "First run: backfilling archive %s to %s",
        start.isoformat(),
        yesterday.isoformat(),
    )
    archive_readings = fetch_archive(
        start.isoformat(),
        yesterday.isoformat(),
    )
    forecast_readings = fetch_forecast()
    log_data = load_log()
    log_data = merge_readings(log_data, archive_readings)
    log_data = merge_readings(log_data, forecast_readings)
    return log_data


def poll_cycle() -> None:
    readings = fetch_pressure()
    log_data = load_log()
    log_data = merge_readings(log_data, readings)
    save_log(log_data)
    touch_heartbeat()
    check_and_alert(log_data)


def send_startup_notification(current_hpa: float) -> None:
    notify(
        "🌡 Migraine Tracker started",
        (
            f"Monitoring pressure at {LATITUDE}, {LONGITUDE}. "
            f"Current: {current_hpa:.1f} hPa."
        ),
        "default",
        "white_check_mark",
    )


def main() -> None:
    signal.signal(signal.SIGTERM, handle_sigterm)
    ensure_data_dir()

    from api_server import start_api_server

    start_api_server()

    first_run = not PRESSURE_LOG_PATH.exists()

    if first_run:
        try:
            log_data = backfill_initial()
            save_log(log_data)
            touch_heartbeat()
            check_and_alert(log_data)
            current = current_reading(log_data.get("readings", []))
            if current:
                send_startup_notification(current["hpa"])
        except Exception as e:
            log.error("Initial backfill failed: %s", e, exc_info=True)
    else:
        try:
            poll_cycle()
        except requests.exceptions.ConnectionError as e:
            log.warning("Startup poll failed (connection): %s", e)
        except requests.exceptions.Timeout as e:
            log.warning("Startup poll failed (timeout): %s", e)
        except json.JSONDecodeError as e:
            log.error("Startup poll failed (JSON decode): %s", e)
        except OSError as e:
            log.error("Startup poll failed (file I/O): %s", e)
        except Exception as e:
            log.error("Startup poll failed: %s", e, exc_info=True)

    while True:
        try:
            poll_cycle()
        except requests.exceptions.ConnectionError as e:
            log.warning("Poll failed (connection): %s", e)
        except requests.exceptions.Timeout as e:
            log.warning("Poll failed (timeout): %s", e)
        except json.JSONDecodeError as e:
            log.error("Poll failed (JSON decode): %s", e)
        except OSError as e:
            log.error("Poll failed (file I/O): %s", e)
        except Exception as e:
            log.error("Poll failed: %s", e, exc_info=True)

        time.sleep(POLL_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
