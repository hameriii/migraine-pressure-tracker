#!/usr/bin/env bash
# Backup migraine-tracker JSON data. Add to cron, e.g. weekly:
# 0 3 * * 0 /opt/migraine-pressure-tracker/scripts/backup-data.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${DATA_DIR:-$ROOT/migraine-tracker/data}"
DEST="${1:-$ROOT/backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
ARCHIVE="$DEST/migraine-data-$STAMP.tar.gz"
tar -czf "$ARCHIVE" -C "$DATA" .
echo "Backup written: $ARCHIVE"
ls -la "$ARCHIVE"
