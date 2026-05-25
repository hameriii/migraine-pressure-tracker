"""Persistent migraine log on the home server (DATA_DIR/migraine_log.json)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import settings as cfg

DATA_DIR = Path(cfg.DATA_DIR)
MIGRAINE_LOG_PATH = DATA_DIR / "migraine_log.json"


def _now_iso(timezone: str = "UTC") -> str:
    return datetime.now(ZoneInfo(timezone)).isoformat()


def load_migraine_log() -> dict[str, Any]:
    if not MIGRAINE_LOG_PATH.exists():
        return {"updated": None, "entries": []}
    with open(MIGRAINE_LOG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("entries", [])
    return data


def save_migraine_log(data: dict[str, Any], timezone: str = "UTC") -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data["updated"] = _now_iso(timezone)
    tmp = MIGRAINE_LOG_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, MIGRAINE_LOG_PATH)


def list_entries() -> list[dict[str, Any]]:
    return load_migraine_log().get("entries", [])


def add_entry(time: str, note: str, timezone: str = "UTC") -> dict[str, Any]:
    note = (note or "")[:100]
    data = load_migraine_log()
    entries = data["entries"]
    # Replace duplicate timestamp
    entries = [e for e in entries if e.get("time") != time]
    entry = {"time": time, "note": note}
    entries.append(entry)
    entries.sort(key=lambda e: e.get("time", ""))
    data["entries"] = entries
    save_migraine_log(data, timezone)
    return entry


def delete_entry(time: str, timezone: str = "UTC") -> bool:
    data = load_migraine_log()
    before = len(data["entries"])
    data["entries"] = [e for e in data["entries"] if e.get("time") != time]
    if len(data["entries"]) == before:
        return False
    save_migraine_log(data, timezone)
    return True
