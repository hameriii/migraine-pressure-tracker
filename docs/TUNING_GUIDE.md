# Tuning thresholds from your own data

Alerts use **your** `.env` numbers. Defaults (3 hPa / 3 h, 6 hPa / 12 h) are a starting guess — not universal.

## What you need

- Tracker running at least **2–4 weeks**
- **Migraine-app** on port 8765 (for logging)
- Honest **“Log Migraine Now”** every attack (with optional note)
- ntfy topic subscribed on your phone

## Week 1–2: Collect only

1. Leave defaults in `.env` unless alerts are unbearable.
2. Log every migraine in the PWA (http://your-server:8765).
3. When an alert fires, note: did you get a migraine **that day** or **next day**?
4. Do **not** change thresholds yet — you need ~3–10 logged events for a pattern.

## What to look at in the app

After each log, read the **correlation** line, e.g.:

- *“Pressure fell 4.2 hPa in 6h before this entry”* → drop before attack  
- *“Pressure stable (+0.3 hPa over 6h)”* → weather may not be your trigger that time  

In the list, each migraine shows this under the date.

Optional: export data for a spreadsheet:

```bash
curl -s http://127.0.0.1:8780/api/export -o export.csv
```

## Week 3–4: Adjust `.env`

Edit `migraine-tracker/.env`, then restart:

```bash
docker compose restart migraine-tracker
```

### Too many alerts (crying wolf)

| Symptom | Try |
|--------|-----|
| Rapid alerts but rarely migraine | Raise `RAPID_DROP_HPA` (e.g. 3 → 4 or 5) |
| Still too many | Lengthen `RAPID_DROP_HOURS` (3 → 4) |
| Sustained spam | Raise `SUSTAINED_DROP_HPA` or disable pre-alert: `PRE_ALERT_ENABLED=false` |
| Night noise | Tighten quiet hours: `QUIET_START=21:00` `QUIET_END=08:00` |

### Too few alerts (missed attacks)

| Symptom | Try |
|--------|-----|
| Migraine with clear drop, no alert | Lower `RAPID_DROP_HPA` (e.g. 3 → 2) |
| Drop over ~6h not 3h | Lower `SUSTAINED_DROP_HPA` or `SUSTAINED_DROP_HOURS` |
| Want early warning | Keep `PRE_ALERT_ENABLED=true`, lower `WATCH_DROP_FRACTION` (e.g. 0.4) |

### Lag (attack hours after the storm)

If drops **precede** migraines by many hours but alerts feel “late” for how you feel:

- Note the typical lag from your log (e.g. drop at 14:00, migraine at 22:00).
- Today alerts fire when the drop happens; a future **alert lag** feature would help — for now, treat a rapid alert as “risk window started” for the rest of the day.

### Finding your personal numbers

Rough method from logged migraines:

1. For each migraine, note `dropHpa` from correlation (6h window).
2. Average the drops that **did** match an attack.
3. Set `RAPID_DROP_HPA` slightly **below** that average (so you still get warned).
4. If averages are ~2 hPa / 6h, something like `RAPID_DROP_HPA=2.5` and `RAPID_DROP_HOURS=6` may fit better than 3/3.

Change **one variable at a time**, wait ~1 week, compare.

## Quick reference (`.env`)

```env
RAPID_DROP_HPA=3      # how many hPa fall triggers “fast drop”
RAPID_DROP_HOURS=3    # over this many hours
SUSTAINED_DROP_HPA=6  # longer, larger fall
SUSTAINED_DROP_HOURS=12
PRE_ALERT_ENABLED=true
WATCH_DROP_FRACTION=0.5   # watch = 50% of rapid threshold
```

## APP_URL (notification → chart)

Set on the server (same network you use for ntfy):

```env
APP_URL=http://100.82.171.112:8765
```

- Use the URL your **phone** can open (Tailscale IP, LAN IP, or HTTPS domain).
- Requires `migraine-app` (nginx on 8765) running.
- Restart tracker after changing: `docker compose restart migraine-tracker`
- Tap a test ntfy; it should open Safari to the PWA.

iPhone: install PWA via **Add to Home Screen** from that same URL once.

## When you’re “done” tuning

- Alerts match **your** risk feeling ~70–80% of the time (never 100%).
- You still log migraines for ongoing check-ins.
- Re-tune after a season change (winter storms vs summer) using `WINTER_*` / `SUMMER_*` if needed.
