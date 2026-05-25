# Home server deployment — instructions for AI agent

Give this document to your home-server AI (or follow it yourself) to add **Migraine Barometric Pressure Tracker** to an existing Docker Compose homelab.

**GitHub repository:** `https://github.com/hameriii/migraine-pressure-tracker`  
**Docker image (GHCR):** `ghcr.io/hameriii/migraine-pressure-tracker:latest`  
**Built automatically** on every push to `main` via GitHub Actions.

---

## Goal

Run two optional services:

1. **`migraine-tracker`** (required) — polls pressure hourly, sends ntfy alerts, stores logs in `/data`, exposes migraine-log API on port **8780**.
2. **`migraine-app`** (optional) — nginx serves the phone PWA on port **8765** and proxies `/api/` to the tracker.

Do **not** replace or modify unrelated services in the user’s existing `docker-compose.yml`. Only **append** new service blocks and create a dedicated directory for config/data.

---

## Prerequisites (verify first)

- [ ] Docker and Docker Compose v2 on the home server
- [ ] Outbound HTTPS to `api.open-meteo.com`
- [ ] User has a working **ntfy** instance (URL + topic)
- [ ] For GHCR: image is **public**, or user has logged in: `docker login ghcr.io`

---

## Step 1 — Directory layout on the home server

Pick a base path (example: `/opt/migraine-pressure-tracker`). Create:

```text
/opt/migraine-pressure-tracker/
├── migraine-tracker/
│   ├── .env                 # user config (never commit)
│   ├── .env.example         # reference
│   ├── data/                # persistent JSON logs
│   │   └── .gitkeep
│   ├── app/
│   │   └── index.html       # phone UI
│   └── nginx/
│       └── default.conf     # only if using migraine-app
```

**Clone repo** (config + static app only; runtime uses pre-built image):

```bash
sudo mkdir -p /opt/migraine-pressure-tracker
sudo git clone https://github.com/hameriii/migraine-pressure-tracker.git /opt/migraine-pressure-tracker
cd /opt/migraine-pressure-tracker
cp migraine-tracker/.env.example migraine-tracker/.env
```

Tell the user to edit `migraine-tracker/.env` (location, ntfy, thresholds). Minimum required:

- `LATITUDE`, `LONGITUDE`, `TIMEZONE`
- `NTFY_URL` (no trailing slash), `NTFY_TOPIC`
- `DATA_DIR=/data` (keep as-is inside container)

---

## Step 2 — Pull the Docker image

```bash
docker pull ghcr.io/hameriii/migraine-pressure-tracker:latest
```

If pull fails with “denied”, the package may be private — run `docker login ghcr.io` with a GitHub PAT that has `read:packages`.

---

## Step 3 — Add services to existing `docker-compose.yml`

Open the user’s main compose file (often `/opt/docker/docker-compose.yml` or similar). Under `services:`, add:

### Required: tracker daemon

```yaml
  migraine-tracker:
    image: ghcr.io/hameriii/migraine-pressure-tracker:latest
    container_name: migraine-tracker
    restart: unless-stopped
    env_file: /opt/migraine-pressure-tracker/migraine-tracker/.env
    volumes:
      - /opt/migraine-pressure-tracker/migraine-tracker/data:/data
    ports:
      - "8780:8780"
    healthcheck:
      test: ["CMD", "python", "-c", "import os,time; f='/data/heartbeat'; t=os.path.getmtime(f) if os.path.exists(f) else 0; exit(0 if time.time()-t < 7200 else 1)"]
      interval: 30m
      timeout: 10s
      retries: 2
      start_period: 90s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

**Important:** Do **not** bind-mount the whole `migraine-tracker` source over `/app` in production — the image already contains `tracker.py`. Only mount `data` and use `env_file`.

Adjust absolute paths if the clone location differs.

### Optional: phone app (nginx)

```yaml
  migraine-app:
    image: nginx:alpine
    container_name: migraine-app
    restart: unless-stopped
    ports:
      - "8765:80"
    volumes:
      - /opt/migraine-pressure-tracker/migraine-tracker/app:/usr/share/nginx/html:ro
      - /opt/migraine-pressure-tracker/migraine-tracker/nginx/default.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - migraine-tracker
```

If port `8765` or `8780` is already in use, change the host side of `ports` and tell the user the new URL.

---

## Step 4 — Start and verify

```bash
cd /path/to/compose/project
docker compose up -d migraine-tracker
docker compose logs -f migraine-tracker
```

**Expect on first run:**

- Log lines about archive backfill
- Files created: `data/pressure_log.json`, `data/heartbeat`
- ntfy message: “Migraine Tracker started” (if ntfy is configured)

**Test ntfy manually:**

```bash
source /opt/migraine-pressure-tracker/migraine-tracker/.env
curl -d "test" -H "Title: Migraine test" "${NTFY_URL%/}/${NTFY_TOPIC}"
```

**Test migraine API:**

```bash
curl -s http://127.0.0.1:8780/api/health
```

**Start phone app (optional):**

```bash
docker compose up -d migraine-app
```

User opens `http://<server-ip>:8765` on phone → Add to Home Screen. In `app/index.html`, ensure `CONFIG.apiBase` is `"/api"` and `CONFIG.apiToken` matches `API_TOKEN` in `.env` if set.

---

## Step 5 — Updates

When the image is updated on GitHub:

```bash
docker pull ghcr.io/hameriii/migraine-pressure-tracker:latest
docker compose up -d migraine-tracker
```

To update the phone UI only (no image rebuild):

```bash
cd /opt/migraine-pressure-tracker && git pull
docker compose restart migraine-app
```

---

## Troubleshooting (for the AI)

| Symptom | Action |
|--------|--------|
| No ntfy | Check `NTFY_URL` has no trailing slash; `curl` test; read tracker logs |
| Unhealthy container | `heartbeat` older than 2h — check Open-Meteo reachability and `data/` permissions |
| App chart works, log not on server | User must open app via nginx `:8765`, not `file://`; tracker must be running |
| Image pull 403 | `docker login ghcr.io` or make GHCR package public in GitHub repo Packages settings |

---

## Network reference

| Port | Service | Purpose |
|------|---------|---------|
| 8780 | migraine-tracker | Migraine log REST API (`/api/migraines`) |
| 8765 | migraine-app | Phone PWA + `/api` proxy to tracker |

---

## Files in this repo for copy-paste

- [`docker-compose.service.yml`](../docker-compose.service.yml) — tracker service block
- [`docker-compose.nginx.yml`](../docker-compose.nginx.yml) — optional nginx block
- [`migraine-tracker/.env.example`](../migraine-tracker/.env.example) — all environment variables
