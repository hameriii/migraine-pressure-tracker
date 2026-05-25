#!/usr/bin/env bash
# Send a test ntfy notification using migraine-tracker/.env settings.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/migraine-tracker/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE — copy from .env.example first."
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

if [[ -z "${NTFY_URL:-}" || -z "${NTFY_TOPIC:-}" ]]; then
  echo "Set NTFY_URL and NTFY_TOPIC in $ENV_FILE"
  exit 1
fi

URL="${NTFY_URL%/}/${NTFY_TOPIC}"
echo "==> POST $URL"

AUTH=()
if [[ -n "${NTFY_TOKEN:-}" ]]; then
  AUTH=(-H "Authorization: Bearer ${NTFY_TOKEN}")
elif [[ -n "${NTFY_USERNAME:-}" && -n "${NTFY_PASSWORD:-}" ]]; then
  AUTH=(-u "${NTFY_USERNAME}:${NTFY_PASSWORD}")
fi

RESP=$(curl -sS -w "\n%{http_code}" "${AUTH[@]}" \
  -H "Title: Migraine tracker test" \
  -H "Tags: white_check_mark" \
  -H "Content-Type: text/plain" \
  -d "Test from scripts/test-ntfy.sh at $(date -Iseconds)" \
  --connect-timeout 10 --max-time 15 \
  "$URL")

BODY=$(echo "$RESP" | head -n -1)
CODE=$(echo "$RESP" | tail -n 1)

echo "$BODY"
if [[ "$CODE" == "200" ]]; then
  echo "==> Success (HTTP $CODE). Check the ntfy app on topic: $NTFY_TOPIC"
  exit 0
fi
echo "==> Failed (HTTP $CODE)"
exit 1
