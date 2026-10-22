#!/usr/bin/env bash
set -euo pipefail

API_DIR="${1:-/home/ubuntu/nyra-mes-api}"
SERVICE="${2:-nyra-mes-api}"
API_PORT="${3:-8010}"

cd "$API_DIR"

if [[ ! -d venv ]]; then
  python3 -m venv venv
fi

source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Prefer Secrets Manager — clears stale MES_CORE_DB_PASSWORD if secret id is set.
if [[ -x "$API_DIR/scripts/deploy/sync_testbed_db_env.sh" ]]; then
  bash "$API_DIR/scripts/deploy/sync_testbed_db_env.sh" "$API_DIR" "" "$SERVICE" "$API_PORT" || {
    echo "WARN: DB secret sync failed — API may not reach nyra_mes_core until MES_CORE_DB_SECRET_ID is set." >&2
  }
fi

if systemctl list-units --type=service --all 2>/dev/null | grep -q "${SERVICE}.service"; then
  sudo systemctl restart "$SERVICE"
  sudo systemctl --no-pager --full status "$SERVICE" | head -n 15
else
  echo "WARN: systemd unit ${SERVICE} not found — start API manually if needed."
fi

curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null && echo "API health OK on port ${API_PORT}" || echo "WARN: local health check failed on port ${API_PORT}"

if systemctl cat nyra-mes-api-demo.service >/dev/null 2>&1; then
  sudo systemctl restart nyra-mes-api-demo
  curl -sf "http://127.0.0.1:8011/health" >/dev/null && echo "Demo API health OK on port 8011" || echo "WARN: demo health check failed on port 8011"
fi
