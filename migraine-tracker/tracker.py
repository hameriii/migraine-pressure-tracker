#!/usr/bin/env python3
"""Migraine barometric pressure tracker daemon."""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests

import data_store as store
import settings as cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_ntfy_failures = 0


def handle_sigterm(sig: int, frame: Any) -> None:
    log.info("Received SIGTERM. Shutting down cleanly.")
    sys.exit(0)


def parse_open_meteo_times(
    times: list[str],
    pressures: list[float | None],
    utc_offset_seconds: int | None,
) -> list[dict[str, Any]]:
    tz = ZoneInfo(cfg.TIMEZONE)
    offset = timedelta(seconds=utc_offset_seconds or 0)
    readings: list[dict[str, Any]] = []

    for t_str, hpa in zip(times, pressures):
        if hpa is None:
            continue
        dt = _parse_time_string(t_str, offset, tz)
        readings.append({"time": dt.isoformat(), "hpa": round(float(hpa), 1)})

    return readings


def _parse_time_string(t_str: str, utc_offset: timedelta, tz: ZoneInfo) -> datetime:
    if len(t_str) >= 19 and (t_str[19] in "+-" or t_str.endswith("Z")):
        dt = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            from datetime import timezone

            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(tz)
    dt_naive = datetime.strptime(t_str[:16], "%Y-%m-%dT%H:%M")
    if utc_offset != timedelta(0):
        from datetime import timezone

        dt = dt_naive.replace(tzinfo=timezone(utc_offset)).astimezone(tz)
    else:
        dt = dt_naive.replace(tzinfo=tz)
    return dt


def fetch_forecast() -> list[dict[str, Any]]:
    params = {
        "latitude": cfg.LATITUDE,
        "longitude": cfg.LONGITUDE,
        "hourly": "surface_pressure",
        "timezone": cfg.TIMEZONE,
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
        "latitude": cfg.LATITUDE,
        "longitude": cfg.LONGITUDE,
        "hourly": "surface_pressure",
        "timezone": cfg.TIMEZONE,
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


def merge_readings(
    log: dict[str, Any],
    new_readings: list[dict[str, Any]],
) -> dict[str, Any]:
    by_time = {r["time"]: r for r in log.get("readings", [])}
    for r in new_readings:
        by_time[r["time"]] = r

    tz = ZoneInfo(cfg.TIMEZONE)
    now = datetime.now(tz)
    cutoff = now - timedelta(days=cfg.LOG_RETENTION_DAYS)
    trimmed = [
        by_time[k]
        for k in sorted(by_time.keys())
        if store.parse_reading_time(k) >= cutoff
    ]
    log["readings"] = trimmed
    log["location"] = {
        "lat": cfg.LATITUDE,
        "lon": cfg.LONGITUDE,
        "timezone": cfg.TIMEZONE,
    }
    log["updated"] = now.isoformat()
    return log


def _alert_body_lines(delta: float, hours: float, current: float, kind: str) -> str:
    lines = [
        f"{kind}: {abs(delta):.1f} hPa over {hours:.0f}h (smoothed over {cfg.SMOOTHING_HOURS}h).",
        f"Now: {current:.1f} hPa at {cfg.LATITUDE}, {cfg.LONGITUDE}.",
    ]
    if cfg.APP_URL:
        lines.append(f"Open chart: {cfg.APP_URL}")
    return "\n".join(lines)


def send_ntfy(title: str, body: str, priority: str, tags: str) -> None:
    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
        "Content-Type": "text/plain",
    }
    if cfg.NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {cfg.NTFY_TOKEN}"
    if cfg.APP_URL:
        headers["Click"] = cfg.APP_URL
    auth = None
    if cfg.NTFY_USERNAME and cfg.NTFY_PASSWORD:
        auth = (cfg.NTFY_USERNAME, cfg.NTFY_PASSWORD)
    resp = requests.post(
        f"{cfg.NTFY_URL.rstrip('/')}/{cfg.NTFY_TOPIC}",
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
    *,
    bypass_quiet: bool = False,
) -> bool:
    global _ntfy_failures
    if not cfg.NTFY_URL or not cfg.NTFY_TOPIC:
        log.warning("NTFY_URL or NTFY_TOPIC not set; skipping notification")
        return False
    if cfg.is_quiet_hours() and not bypass_quiet:
        log.info("Quiet hours — skipping: %s", title)
        return False
    for attempt in range(2):
        try:
            send_ntfy(title, body, priority, tags)
            log.info("Notification sent: %s", title)
            return True
        except requests.RequestException as e:
            _ntfy_failures += 1
            log.error("ntfy failed (attempt %d): %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(30)
    return False


def hours_since_alert(last_time: str | None) -> float | None:
    if not last_time:
        return None
    tz = ZoneInfo(cfg.TIMEZONE)
    now = datetime.now(tz)
    then = store.parse_reading_time(last_time)
    return (now - then).total_seconds() / 3600


def min_hpa_since_drop(readings: list[dict[str, Any]], since: datetime) -> float | None:
    values = [
        r["hpa"]
        for r in readings
        if store.parse_reading_time(r["time"]) >= since
    ]
    return min(values) if values else None


def check_and_alert(log: dict[str, Any]) -> None:
    readings = log.get("readings", [])
    current = store.current_hpa(readings, smooth=True)
    if current is None:
        return

    rapid_hpa, sustained_hpa = cfg.seasonal_thresholds()
    state = store.load_alert_state()
    tz = ZoneInfo(cfg.TIMEZONE)
    now = datetime.now(tz)

    if state["drop_alert_active"]:
        peak = state.get("peak_hpa_since_drop")
        state["peak_hpa_since_drop"] = (
            current if peak is None else max(peak, current)
        )

    delta_rapid = store.pressure_change_hours(
        readings, cfg.RAPID_DROP_HOURS, smooth=True
    )
    if delta_rapid is not None and delta_rapid <= -rapid_hpa:
        hs = hours_since_alert(state.get("last_rapid_alert_time"))
        if hs is None or hs >= cfg.RAPID_ALERT_COOLDOWN_HOURS:
            notify(
                "⚠️ Pressure dropping fast",
                _alert_body_lines(delta_rapid, cfg.RAPID_DROP_HOURS, current, "Rapid drop"),
                "high",
                "warning,chart_with_downwards_trend",
            )
            state["last_rapid_alert_time"] = now.isoformat()
            state["drop_alert_active"] = True
            state.setdefault("peak_hpa_since_drop", current)

    elif (
        cfg.PRE_ALERT_ENABLED
        and delta_rapid is not None
        and delta_rapid <= -(rapid_hpa * cfg.WATCH_DROP_FRACTION)
    ):
        hs = hours_since_alert(state.get("last_pre_alert_time"))
        if hs is None or hs >= cfg.PRE_ALERT_COOLDOWN_HOURS:
            notify(
                "👀 Pressure watch",
                _alert_body_lines(
                    delta_rapid,
                    cfg.RAPID_DROP_HOURS,
                    current,
                    f"Approaching rapid threshold ({rapid_hpa:.0f} hPa)",
                ),
                "low",
                "eyes",
            )
            state["last_pre_alert_time"] = now.isoformat()

    delta_sustained = store.pressure_change_hours(
        readings, cfg.SUSTAINED_DROP_HOURS, smooth=True
    )
    if delta_sustained is not None and delta_sustained <= -sustained_hpa:
        hs = hours_since_alert(state.get("last_sustained_alert_time"))
        if hs is None or hs >= cfg.SUSTAINED_ALERT_COOLDOWN_HOURS:
            notify(
                "📉 Sustained pressure fall",
                _alert_body_lines(
                    delta_sustained, cfg.SUSTAINED_DROP_HOURS, current, "Sustained drop"
                ),
                "default",
                "cloud_with_rain",
            )
            state["last_sustained_alert_time"] = now.isoformat()
            state["drop_alert_active"] = True
            state.setdefault("peak_hpa_since_drop", current)

    if state["drop_alert_active"]:
        delta_recovery = store.pressure_change_hours(
            readings, cfg.RISE_RECOVERY_HOURS, smooth=True
        )
        recovery_fired = delta_recovery is not None and delta_recovery >= cfg.RISE_RECOVERY_HPA
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
                since_drop = min(store.parse_reading_time(t) for t in drop_times)
                low = min_hpa_since_drop(readings, since_drop)
                if low is not None and (current - low) >= cfg.RISE_RECOVERY_HPA:
                    recovery_fired = True
                    delta_recovery = current - low
        if recovery_fired:
            d = delta_recovery or cfg.RISE_RECOVERY_HPA
            notify(
                "✅ Pressure recovering",
                _alert_body_lines(d, cfg.RISE_RECOVERY_HOURS, current, "Recovery"),
                "low",
                "sunny,white_check_mark",
            )
            state["last_recovery_alert_time"] = now.isoformat()
            state["drop_alert_active"] = False
            state["peak_hpa_since_drop"] = None

    store.save_alert_state(state)


def update_status(log: dict[str, Any], poll_ok: bool) -> None:
    readings = log.get("readings", [])
    state = store.load_alert_state()
    store.save_status(
        {
            "updated": datetime.now(ZoneInfo(cfg.TIMEZONE)).isoformat(),
            "poll_ok": poll_ok,
            "current_hpa": store.current_hpa(readings, smooth=True),
            "readings_count": len(readings),
            "pressure_log_updated": log.get("updated"),
            "heartbeat_age_seconds": store.heartbeat_age_seconds(),
            "drop_alert_active": state.get("drop_alert_active", False),
            "last_rapid_alert_time": state.get("last_rapid_alert_time"),
            "last_sustained_alert_time": state.get("last_sustained_alert_time"),
            "quiet_hours_active": cfg.is_quiet_hours(),
            "ntfy_failures": _ntfy_failures,
            "season": (
                "winter"
                if datetime.now(ZoneInfo(cfg.TIMEZONE)).month in (12, 1, 2)
                else "summer"
                if datetime.now(ZoneInfo(cfg.TIMEZONE)).month in (6, 7, 8)
                else "default"
            ),
        }
    )


def deadman_loop() -> None:
    while True:
        time.sleep(cfg.DEADMAN_CHECK_MINUTES * 60)
        if not cfg.DEADMAN_ALERT_ENABLED:
            continue
        age = store.heartbeat_age_seconds()
        if age is None or age < cfg.DEADMAN_STALE_HOURS * 3600:
            continue
        state = store.load_alert_state()
        hs = hours_since_alert(state.get("last_deadman_alert_time"))
        if hs is not None and hs < cfg.DEADMAN_COOLDOWN_HOURS:
            continue
        body = (
            f"No successful poll for {age / 3600:.1f}h. "
            f"Check container logs and Open-Meteo connectivity."
        )
        if cfg.APP_URL:
            body += f"\nServer: {cfg.APP_URL}"
        if notify(
            "🛑 Migraine tracker offline",
            body,
            "high",
            "rotating_light",
            bypass_quiet=True,
        ):
            state["last_deadman_alert_time"] = datetime.now(
                ZoneInfo(cfg.TIMEZONE)
            ).isoformat()
            store.save_alert_state(state)


def backfill_initial() -> dict[str, Any]:
    tz = ZoneInfo(cfg.TIMEZONE)
    today = datetime.now(tz).date()
    yesterday = today - timedelta(days=1)
    start = today - timedelta(days=30)
    log.info("First run: backfilling archive %s to %s", start, yesterday)
    archive_readings = fetch_archive(start.isoformat(), yesterday.isoformat())
    forecast_readings = fetch_forecast()
    log_data = store.load_pressure_log()
    log_data = merge_readings(log_data, archive_readings)
    log_data = merge_readings(log_data, forecast_readings)
    return log_data


def poll_cycle() -> None:
    global _ntfy_failures
    poll_ok = False
    try:
        readings = fetch_forecast()
        log_data = store.load_pressure_log()
        log_data = merge_readings(log_data, readings)
        store.save_pressure_log(log_data)
        store.touch_heartbeat()
        check_and_alert(log_data)
        poll_ok = True
        update_status(log_data, True)
    except Exception:
        update_status(store.load_pressure_log(), False)
        raise


def send_startup_notification(current_hpa: float) -> None:
    body = (
        f"Monitoring pressure at {cfg.LATITUDE}, {cfg.LONGITUDE}. "
        f"Current: {current_hpa:.1f} hPa."
    )
    if cfg.APP_URL:
        body += f"\nOpen chart: {cfg.APP_URL}"
    notify("🌡 Migraine Tracker started", body, "default", "white_check_mark")


def main() -> None:
    signal.signal(signal.SIGTERM, handle_sigterm)
    store.ensure_data_dir()

    from api_server import start_api_server

    start_api_server()
    threading.Thread(target=deadman_loop, daemon=True, name="deadman").start()

    first_run = not store.PRESSURE_LOG_PATH.exists()

    if first_run:
        try:
            log_data = backfill_initial()
            store.save_pressure_log(log_data)
            store.touch_heartbeat()
            check_and_alert(log_data)
            update_status(log_data, True)
            cur = store.current_hpa(log_data.get("readings", []))
            if cur is not None:
                send_startup_notification(cur)
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
        time.sleep(cfg.POLL_INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
