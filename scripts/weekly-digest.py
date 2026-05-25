#!/usr/bin/env python3
"""Send weekly pressure + migraine summary via ntfy. Cron example:
0 9 * * 1 cd /opt/migraine-pressure-tracker && python3 scripts/weekly-digest.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "migraine-tracker"
sys.path.insert(0, str(ROOT))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def main() -> None:
    load_env_file(ROOT / ".env")
    from zoneinfo import ZoneInfo

    import data_store as store
    import settings as cfg
    from migraine_store import load_migraine_log
    from tracker import notify

    tz = ZoneInfo(cfg.TIMEZONE)
    now = datetime.now(tz)
    week_ago = now - timedelta(days=7)
    readings = [
        r
        for r in store.load_pressure_log().get("readings", [])
        if store.parse_reading_time(r["time"]) >= week_ago
    ]
    migraines = [
        e
        for e in load_migraine_log().get("entries", [])
        if store.parse_reading_time(e["time"]) >= week_ago
    ]
    if readings:
        hpas = [r["hpa"] for r in readings]
        body = (
            f"Weekly summary ({week_ago.date()} – {now.date()})\n"
            f"Pressure: {min(hpas):.0f}–{max(hpas):.0f} hPa, now {readings[-1]['hpa']:.1f} hPa\n"
            f"Migraines logged: {len(migraines)}"
        )
    else:
        body = f"Weekly summary: no pressure readings. Migraines logged: {len(migraines)}"
    notify("📊 Weekly pressure digest", body, "low", "bar_chart", bypass_quiet=True)


if __name__ == "__main__":
    main()
