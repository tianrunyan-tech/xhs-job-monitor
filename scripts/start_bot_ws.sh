#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.local"
CONFIG_FILE="$ROOT_DIR/config.local.yaml"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy .env.local.example to .env.local and fill MINIMAX_API_KEY." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

if [[ -z "${MINIMAX_API_KEY:-}" || "${MINIMAX_API_KEY}" == "replace_with_your_minimax_api_key" ]]; then
  echo "MINIMAX_API_KEY is not configured in $ENV_FILE." >&2
  exit 1
fi

cd "$ROOT_DIR"
exec /usr/bin/python3 "$ROOT_DIR/scripts/bot_ws_client.py" \
  --config "$CONFIG_FILE" \
  --limit "${XHS_JOB_MONITOR_LIMIT:-50}"
