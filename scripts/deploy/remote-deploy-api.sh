#!/usr/bin/env bash
set -euo pipefail

API_DIR="${1:-/home/ubuntu/nyra-mes-api}"
SERVICE="${2:-nyra-mes-api}"

cd "$API_DIR"

if [[ ! -d venv ]]; then
  python3 -m venv venv
fi

source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

if systemctl list-unit-files | grep -q "^${SERVICE}.service"; then
  sudo systemctl restart "$SERVICE"
  sudo systemctl --no-pager --full status "$SERVICE" | head -n 15
else
  echo "WARN: systemd unit ${SERVICE} not found — start API manually if needed."
fi

curl -sf "http://127.0.0.1:8000/health" >/dev/null && echo "API health OK" || echo "WARN: local health check failed (port/path may differ)"
