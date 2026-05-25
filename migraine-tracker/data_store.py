"""JSON persistence for pressure log, alert state, and runtime status."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import settings as cfg

DATA_DIR = Path(cfg.DATA_DIR)
PRESSURE_LOG_PATH = DATA_DIR / "pressure_log.json"
ALERT_STATE_PATH = DATA_DIR / "alert_state.json"
STATUS_PATH = DATA_DIR / "status.json"
HEARTBEAT_PATH = DATA_DIR / "heartbeat"

DEFAULT_ALERT_STATE: dict[str, Any] = {
    "last_rapid_alert_time": None,
    "last_sustained_alert_time": None,
    "last_recovery_alert_time": None,
    "last_pre_alert_time": None,
    "last_deadman_alert_time": None,
    "drop_alert_active": False,
    "peak_hpa_since_drop": None,
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def parse_reading_time(time_str: str) -> datetime:
    dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(cfg.TIMEZONE))
    return dt


def load_pressure_log() -> dict[str, Any]:
    if not PRESSURE_LOG_PATH.exists():
        return {
            "updated": None,
            "location": {
                "lat": cfg.LATITUDE,
                "lon": cfg.LONGITUDE,
                "timezone": cfg.TIMEZONE,
            },
            "readings": [],
        }
    with open(PRESSURE_LOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_pressure_log(log: dict[str, Any]) -> None:
    atomic_write_json(PRESSURE_LOG_PATH, log)


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


def load_status() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return {}
    with open(STATUS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_status(status: dict[str, Any]) -> None:
    atomic_write_json(STATUS_PATH, status)


def touch_heartbeat() -> None:
    HEARTBEAT_PATH.touch()


def heartbeat_age_seconds() -> float | None:
    if not HEARTBEAT_PATH.exists():
        return None
    return datetime.now().timestamp() - HEARTBEAT_PATH.stat().st_mtime


def readings_in_window(
    readings: list[dict[str, Any]],
    end: datetime,
    hours: float,
) -> list[dict[str, Any]]:
    start = end - timedelta(hours=hours)
    out = []
    for r in readings:
        dt = parse_reading_time(r["time"])
        if start <= dt <= end:
            out.append(r)
    return out


def smoothed_hpa(
    readings: list[dict[str, Any]],
    at: datetime,
    window_hours: float,
) -> float | None:
    window = readings_in_window(readings, at, window_hours)
    if not window:
        past = [r for r in readings if parse_reading_time(r["time"]) <= at]
        if not past:
            return None
        return past[-1]["hpa"]
    return sum(r["hpa"] for r in window) / len(window)


def reading_at_hours_ago(
    readings: list[dict[str, Any]],
    hours: float,
    *,
    smooth: bool = False,
) -> float | None:
    tz = ZoneInfo(cfg.TIMEZONE)
    now = datetime.now(tz)
    target = now - timedelta(hours=hours)
    if smooth and cfg.SMOOTHING_HOURS > 0:
        return smoothed_hpa(readings, target, cfg.SMOOTHING_HOURS)
    best = None
    best_dt = None
    for r in readings:
        dt = parse_reading_time(r["time"])
        if dt <= target and (best_dt is None or dt > best_dt):
            best = r
            best_dt = dt
    return best["hpa"] if best else None


def current_hpa(readings: list[dict[str, Any]], *, smooth: bool = False) -> float | None:
    tz = ZoneInfo(cfg.TIMEZONE)
    now = datetime.now(tz)
    if smooth and cfg.SMOOTHING_HOURS > 0:
        return smoothed_hpa(readings, now, cfg.SMOOTHING_HOURS)
    past = [r for r in readings if parse_reading_time(r["time"]) <= now]
    if past:
        return past[-1]["hpa"]
    return readings[-1]["hpa"] if readings else None


def pressure_change_hours(
    readings: list[dict[str, Any]],
    hours: float,
    *,
    smooth: bool = True,
) -> float | None:
    cur = current_hpa(readings, smooth=smooth)
    past = reading_at_hours_ago(readings, hours, smooth=smooth)
    if cur is None or past is None:
        return None
    return cur - past


def correlate_migraine_time(iso_time: str, hours_before: float = 6) -> dict[str, Any]:
    readings = load_pressure_log().get("readings", [])
    if not readings:
        return {"dropHpa": None, "hours": hours_before, "summary": "No pressure data"}
    try:
        event = parse_reading_time(iso_time)
    except ValueError:
        return {"dropHpa": None, "summary": "Invalid time"}
    at_event = smoothed_hpa(readings, event, cfg.SMOOTHING_HOURS or 1)
    before = smoothed_hpa(
        readings,
        event - timedelta(hours=hours_before),
        cfg.SMOOTHING_HOURS or 1,
    )
    if at_event is None or before is None:
        return {"dropHpa": None, "summary": "Insufficient readings near event"}
    drop = before - at_event
    if drop >= 1:
        summary = f"Pressure fell {drop:.1f} hPa in {hours_before:.0f}h before this entry"
    elif drop <= -1:
        summary = f"Pressure rose {abs(drop):.1f} hPa in {hours_before:.0f}h before this entry"
    else:
        summary = f"Pressure stable ({drop:+.1f} hPa over {hours_before:.0f}h)"
    return {
        "dropHpa": round(drop, 1),
        "hours": hours_before,
        "hpaAtEvent": round(at_event, 1),
        "summary": summary,
    }


def build_export_csv() -> str:
    pressure = load_pressure_log()
    from migraine_store import load_migraine_log

    migraine = load_migraine_log()
    lines = ["type,time,hpa,note"]
    for r in pressure.get("readings", []):
        lines.append(f"pressure,{r['time']},{r['hpa']},")
    for e in migraine.get("entries", []):
        note = (e.get("note") or "").replace('"', '""')
        lines.append(f'migraine,{e["time"]},,"{note}"')
    return "\n".join(lines) + "\n"
