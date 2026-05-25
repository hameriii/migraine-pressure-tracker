"""Environment configuration and helpers."""

from __future__ import annotations

import os
from datetime import datetime, time
from zoneinfo import ZoneInfo


def env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, default))


def env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))


def env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


LATITUDE = env_float("LATITUDE", 63.83)
LONGITUDE = env_float("LONGITUDE", 20.26)
TIMEZONE = env_str("TIMEZONE", "Europe/Stockholm")

NTFY_URL = env_str("NTFY_URL")
NTFY_TOPIC = env_str("NTFY_TOPIC", "migraines")
NTFY_TOKEN = env_str("NTFY_TOKEN")
NTFY_USERNAME = env_str("NTFY_USERNAME")
NTFY_PASSWORD = env_str("NTFY_PASSWORD")
APP_URL = env_str("APP_URL").rstrip("/")

RAPID_DROP_HPA = env_float("RAPID_DROP_HPA", 3)
RAPID_DROP_HOURS = env_int("RAPID_DROP_HOURS", 3)
SUSTAINED_DROP_HPA = env_float("SUSTAINED_DROP_HPA", 6)
SUSTAINED_DROP_HOURS = env_int("SUSTAINED_DROP_HOURS", 12)
RISE_RECOVERY_HPA = env_float("RISE_RECOVERY_HPA", 2)
RISE_RECOVERY_HOURS = env_int("RISE_RECOVERY_HOURS", 3)

WINTER_RAPID_DROP_HPA = env_float("WINTER_RAPID_DROP_HPA", RAPID_DROP_HPA)
WINTER_SUSTAINED_DROP_HPA = env_float("WINTER_SUSTAINED_DROP_HPA", SUSTAINED_DROP_HPA)
SUMMER_RAPID_DROP_HPA = env_float("SUMMER_RAPID_DROP_HPA", RAPID_DROP_HPA)
SUMMER_SUSTAINED_DROP_HPA = env_float("SUMMER_SUSTAINED_DROP_HPA", SUSTAINED_DROP_HPA)

SMOOTHING_HOURS = env_int("SMOOTHING_HOURS", 3)
PRE_ALERT_ENABLED = env_bool("PRE_ALERT_ENABLED", True)
WATCH_DROP_FRACTION = env_float("WATCH_DROP_FRACTION", 0.5)
PRE_ALERT_COOLDOWN_HOURS = env_int("PRE_ALERT_COOLDOWN_HOURS", 6)

QUIET_HOURS_ENABLED = env_bool("QUIET_HOURS_ENABLED", True)
QUIET_START = env_str("QUIET_START", "22:00")
QUIET_END = env_str("QUIET_END", "07:00")

DEADMAN_ALERT_ENABLED = env_bool("DEADMAN_ALERT_ENABLED", True)
DEADMAN_STALE_HOURS = env_int("DEADMAN_STALE_HOURS", 2)
DEADMAN_CHECK_MINUTES = env_int("DEADMAN_CHECK_MINUTES", 30)
DEADMAN_COOLDOWN_HOURS = env_int("DEADMAN_COOLDOWN_HOURS", 24)

POLL_INTERVAL_MINUTES = env_int("POLL_INTERVAL_MINUTES", 60)
LOG_RETENTION_DAYS = env_int("LOG_RETENTION_DAYS", 30)
DATA_DIR = env_str("DATA_DIR", "/data")

API_PORT = env_int("API_PORT", 8780)
API_TOKEN = env_str("API_TOKEN").strip()
REQUIRE_API_TOKEN = env_bool("REQUIRE_API_TOKEN", False)

RAPID_ALERT_COOLDOWN_HOURS = 6
SUSTAINED_ALERT_COOLDOWN_HOURS = 12


def _parse_hhmm(value: str) -> time:
    parts = value.strip().split(":")
    return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def is_quiet_hours(now: datetime | None = None) -> bool:
    if not QUIET_HOURS_ENABLED:
        return False
    tz = ZoneInfo(TIMEZONE)
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    start = _parse_hhmm(QUIET_START)
    end = _parse_hhmm(QUIET_END)
    t = now.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def seasonal_thresholds(now: datetime | None = None) -> tuple[float, float]:
    tz = ZoneInfo(TIMEZONE)
    now = now or datetime.now(tz)
    month = now.month
    if month in (12, 1, 2):
        return WINTER_RAPID_DROP_HPA, WINTER_SUSTAINED_DROP_HPA
    if month in (6, 7, 8):
        return SUMMER_RAPID_DROP_HPA, SUMMER_SUSTAINED_DROP_HPA
    return RAPID_DROP_HPA, SUSTAINED_DROP_HPA


def public_config() -> dict:
    rapid, sustained = seasonal_thresholds()
    return {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "timezone": TIMEZONE,
        "rapidDropHpa": rapid,
        "rapidDropHours": RAPID_DROP_HOURS,
        "sustainedDropHpa": sustained,
        "sustainedDropHours": SUSTAINED_DROP_HOURS,
        "riseRecoveryHpa": RISE_RECOVERY_HPA,
        "riseRecoveryHours": RISE_RECOVERY_HOURS,
        "watchDropFraction": WATCH_DROP_FRACTION,
        "apiBase": "/api",
        "appUrl": APP_URL,
        "authRequired": bool(API_TOKEN) or REQUIRE_API_TOKEN,
    }
