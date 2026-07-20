#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env.local"
CONFIG_FILE="$ROOT_DIR/config.local.yaml"
LOG_DIR="$ROOT_DIR/logs"

mkdir -p "$LOG_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE. Copy .env.local.example to .env.local and fill the LLM API key env var referenced by llm.api_key_env." >&2
  exit 1
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Missing $CONFIG_FILE. Copy references/config.example.yaml to config.local.yaml and fill your Feishu/XHS/LLM settings." >&2
  exit 1
fi

set -a
source "$ENV_FILE"
set +a

cd "$ROOT_DIR"
exec /usr/bin/python3 "$ROOT_DIR/scripts/bot_ws_client.py" \
  --config "$CONFIG_FILE" \
  --limit "${XHS_JOB_MONITOR_LIMIT:-50}"
