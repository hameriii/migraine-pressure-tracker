# Migraine Barometric Pressure Tracker

[![Build Docker image](https://github.com/hameriii/migraine-pressure-tracker/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/hameriii/migraine-pressure-tracker/actions/workflows/docker-publish.yml)

A Docker-based daemon polls barometric pressure from [Open-Meteo](https://open-meteo.com/), logs readings, detects migraine-risk pressure patterns, and sends push notifications via [ntfy](https://ntfy.sh/). A self-contained phone app (`index.html`) charts pressure and syncs migraine logs to your home server.

**Repository:** [github.com/hameriii/migraine-pressure-tracker](https://github.com/hameriii/migraine-pressure-tracker)  
**Docker image:** `ghcr.io/hameriii/migraine-pressure-tracker:latest`

### Deploy on your home server

Give your homelab AI this file: **[docs/HOME_SERVER_AI_INSTRUCTIONS.md](docs/HOME_SERVER_AI_INSTRUCTIONS.md)**

## What’s included

| Component | Role |
|-----------|------|
| `migraine-tracker/tracker.py` | Hourly poller, JSON log, alerts |
| `migraine-tracker/app/index.html` | PWA-style chart + migraine log (syncs to server) |
| `docker-compose.service.yml` | Service block for your compose file |
| `docker-compose.nginx.yml` | Optional nginx static file server |

## Local testing (before deploying)

From the repo root:

```bash
# 1. Config (edit NTFY_* if you want push notifications)
cp migraine-tracker/.env.example migraine-tracker/.env

# 2. One-shot poll — fetches Open-Meteo, writes data/pressure_log.json
./scripts/test-poll.sh

# 3. Run the daemon continuously
docker compose up -d migraine-tracker
docker compose logs -f migraine-tracker

# 4. Phone app at http://localhost:8765 (includes /api proxy to tracker)
docker compose up -d migraine-app
# Or without Docker: python3 -m http.server 8765 --directory migraine-tracker/app
#   (migraine log stays on phone unless tracker API is reachable)

# Stop
docker compose down
docker compose --profile app down
```

To test ntfy locally, set `NTFY_URL` and `NTFY_TOPIC` in `.env` (public `https://ntfy.sh` works for a quick test). Without valid ntfy settings, polling still works; notifications are skipped with a warning in the logs.

---

## Production image (GHCR)

GitHub Actions builds and pushes on every push to `main`:

```bash
docker pull ghcr.io/hameriii/migraine-pressure-tracker:latest
```

Use the service blocks in `docker-compose.service.yml` (production) — mount only `data/` and `env_file`, not the Python source.

---

## Requirements

- Docker and Docker Compose on your server
- A self-hosted (or public) ntfy instance
- Terminal access to copy files and edit `.env`

---

## Installation

### 1. Copy the project to your server

Copy the entire `migraine-tracker/` folder (and optionally the compose snippets) to your Docker host, e.g. next to your existing `docker-compose.yml`.

### 2. Configure environment

```bash
cd migraine-tracker
cp .env.example .env
nano .env   # or your preferred editor
```

| Variable | Description |
|----------|-------------|
| `LATITUDE` / `LONGITUDE` | Your location for Open-Meteo |
| `TIMEZONE` | IANA timezone (e.g. `Europe/Stockholm`) — used for timestamps and the phone app |
| `NTFY_URL` | Base URL of your ntfy server (**no trailing slash**) |
| `NTFY_TOPIC` | Topic name subscribers listen on |
| `NTFY_TOKEN` | Bearer token if using token auth (leave blank otherwise) |
| `NTFY_USERNAME` / `NTFY_PASSWORD` | Basic auth if not using a token |
| `RAPID_DROP_HPA` / `RAPID_DROP_HOURS` | Alert if pressure falls this much in this window |
| `SUSTAINED_DROP_HPA` / `SUSTAINED_DROP_HOURS` | Sustained fall alert |
| `RISE_RECOVERY_HPA` / `RISE_RECOVERY_HOURS` | Recovery notification after a drop |
| `POLL_INTERVAL_MINUTES` | How often to poll (default `60`) |
| `LOG_RETENTION_DAYS` | Days of readings kept in `pressure_log.json` |
| `DATA_DIR` | Path inside container (keep `/data`) |

### 3. ntfy authentication

**Token (recommended for self-hosted ntfy):**

```bash
ntfy token add yourusername
```

Put the token in `.env` as `NTFY_TOKEN=...` and leave `NTFY_USERNAME` / `NTFY_PASSWORD` empty.

**Username and password:**

Set `NTFY_USERNAME` and `NTFY_PASSWORD` in `.env` and leave `NTFY_TOKEN` empty.

Use **one** method, not both.

### 4. Add the service to Docker Compose

Open your existing `docker-compose.yml` and paste the contents of [`docker-compose.service.yml`](docker-compose.service.yml) under `services:`.

The service builds from `migraine-tracker/Dockerfile` so the `requests` library is installed. The `/app` volume lets you edit `tracker.py` and `.env` without rebuilding; persistent data lives in `./migraine-tracker/data` mounted at `/data`.

### 5. Start the tracker

From the directory that contains `docker-compose.yml`:

```bash
docker compose up -d migraine-tracker
```

### 6. Check logs

```bash
docker compose logs -f migraine-tracker
```

On first run you should see archive backfill, then hourly polls. Data files appear in `migraine-tracker/data/`:

- `pressure_log.json` — pressure readings
- `alert_state.json` — alert deduplication state
- `heartbeat` — touched after each successful poll (used by healthcheck)

### 7. Verify ntfy

On **first startup** (no existing `pressure_log.json`), the daemon sends:

> **🌡 Migraine Tracker started** — Monitoring pressure at … Current: … hPa.

Test manually:

```bash
curl -d "test" https://your-ntfy-server.example.com/your-topic
```

Match `NTFY_URL` and `NTFY_TOPIC` in `.env` to that URL.

### 8. Phone app

**Option A — no server:** Open `migraine-tracker/app/index.html` in Safari (file:// or AirDrop/email). The app calls Open-Meteo directly; no backend required for the chart.

**Option B — nginx (optional):** Paste [`docker-compose.nginx.yml`](docker-compose.nginx.yml) into compose and run:

```bash
docker compose up -d migraine-app
```

Open `http://your-server:8765` on your phone.

Edit coordinates and thresholds at the top of the `<script>` block in `index.html` (`CONFIG`) to match your `.env`.

**Migraine log on the server:** With the app served via nginx (`migraine-app`), entries are stored in `migraine-tracker/data/migraine_log.json` on your home server. In `index.html`, keep `CONFIG.apiBase: "/api"`. If you set `API_TOKEN` in `.env`, set the same value in `CONFIG.apiToken`. To use phone-only storage again, set `CONFIG.apiBase: ""`.

### 9. Add to iPhone Home Screen

1. Open the app URL in **Safari**
2. Tap **Share** → **Add to Home Screen**
3. Name it (e.g. “Pressure”) and add

---

## Troubleshooting

### No notifications received

- Confirm `NTFY_URL` has **no trailing slash**
- Confirm `NTFY_TOPIC` matches what you subscribe to in the ntfy app
- Test with: `curl -d "test" https://your-ntfy/your-topic`
- Check logs: `docker compose logs migraine-tracker` for `ntfy failed`
- If using auth, verify `NTFY_TOKEN` or username/password

### Container keeps restarting or unhealthy

```bash
docker compose logs migraine-tracker
docker inspect --format='{{json .State.Health}}' $(docker compose ps -q migraine-tracker)
```

The healthcheck fails if `data/heartbeat` is older than 2 hours — usually means polls or writes are failing. Check network access to `api.open-meteo.com` and write permissions on `./migraine-tracker/data`.

### Chart is empty (phone app)

- Open browser developer tools → Console for fetch/CORS errors
- Open-Meteo must be reachable from the phone
- Confirm `CONFIG.latitude`, `CONFIG.longitude`, and `CONFIG.timezone` in `index.html`

### Wrong timezone on chart

- Set `TIMEZONE` in `.env` to your IANA zone
- Set the same value in `CONFIG.timezone` in `index.html`

### Migraine log not saving to server

- Open the app via nginx (`http://your-server:8765`), not as a raw `file://` URL
- Ensure `migraine-tracker` is running (API on port 8780 inside Docker)
- If `API_TOKEN` is set in `.env`, set `CONFIG.apiToken` in `index.html` to match
- Check `migraine-tracker/data/migraine_log.json` exists after logging an entry

---

## Migraine log API

The tracker exposes a small JSON API (stdlib, same container as `tracker.py`):

| Method | Path | Action |
|--------|------|--------|
| GET | `/api/migraines` | List all entries |
| POST | `/api/migraines` | Body: `{"time":"ISO","note":"..."}` |
| DELETE | `/api/migraines?time=...` | Remove one entry |

Optional auth: set `API_TOKEN` in `.env`, send `Authorization: Bearer <token>` from the app.

---

## Alert behaviour (daemon)

| Alert | Condition | Cooldown |
|-------|-----------|----------|
| Rapid drop | ≥ `RAPID_DROP_HPA` in `RAPID_DROP_HOURS` | 6 hours |
| Sustained drop | ≥ `SUSTAINED_DROP_HPA` in `SUSTAINED_DROP_HOURS` | 12 hours |
| Recovery | After a drop alert, rise ≥ `RISE_RECOVERY_HPA` | Once per event |

Notifications are best-effort; API or ntfy failures do not stop the daemon.

## License

Use and modify as you need for personal health tracking.
