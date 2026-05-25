#!/usr/bin/env bash
# Run a single poll cycle (no infinite loop). Works with Docker or native Python.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if command -v docker &>/dev/null && docker compose version &>/dev/null; then
  echo "==> Building image (if needed)..."
  docker compose build migraine-tracker
  echo "==> Running one poll cycle in container..."
  docker compose run --rm migraine-tracker python -c "
from tracker import ensure_data_dir, poll_cycle, PRESSURE_LOG_PATH, HEARTBEAT_PATH
import json
ensure_data_dir()
poll_cycle()
print('pressure_log:', PRESSURE_LOG_PATH, 'exists=', PRESSURE_LOG_PATH.exists())
print('heartbeat:', HEARTBEAT_PATH, 'exists=', HEARTBEAT_PATH.exists())
if PRESSURE_LOG_PATH.exists():
    log = json.load(open(PRESSURE_LOG_PATH))
    n = len(log.get('readings', []))
    last = log['readings'][-1] if n else None
    print(f'readings: {n}, latest: {last}')
"
else
  echo "==> Running one poll cycle with local Python..."
  cd migraine-tracker
  export DATA_DIR="${DATA_DIR:-./data}"
  mkdir -p "$DATA_DIR"
  pip3 install -q -r requirements.txt
  python3 -c "
from tracker import ensure_data_dir, poll_cycle, PRESSURE_LOG_PATH, HEARTBEAT_PATH
import json
ensure_data_dir()
poll_cycle()
print('pressure_log:', PRESSURE_LOG_PATH.resolve())
print('heartbeat exists:', HEARTBEAT_PATH.exists())
if PRESSURE_LOG_PATH.exists():
    log = json.load(open(PRESSURE_LOG_PATH))
    print('readings:', len(log.get('readings', [])))
    print('latest:', log['readings'][-1] if log.get('readings') else None)
"
fi

echo "==> Done. Inspect migraine-tracker/data/ for pressure_log.json"
