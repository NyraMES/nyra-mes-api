#!/usr/bin/env bash
# Sync nyra_mes_core DB config on testbed — prefer Secrets Manager over stale .env password.
set -euo pipefail

API_DIR="${1:-/home/ubuntu/nyra-mes-api}"
SECRET_ID="${2:-}"
SERVICE="${3:-nyra-mes-api}"
API_PORT="${4:-8010}"

cd "$API_DIR"
ENV_FILE="$API_DIR/.env"
PYTHON="${API_DIR}/venv/bin/python"

if [[ -z "$SECRET_ID" ]]; then
  if [[ -f "$API_DIR/scripts/deploy/discover_rds_secret.py" ]]; then
    DISCOVER_OUT="$("$PYTHON" "$API_DIR/scripts/deploy/discover_rds_secret.py" 2>&1)" || true
    SECRET_ID="$(echo "$DISCOVER_OUT" | grep '^MES_CORE_DB_SECRET_ID=' | cut -d= -f2- || true)"
    if [[ -z "$SECRET_ID" ]]; then
      echo "$DISCOVER_OUT" >&2
    fi
  fi
fi

if [[ -z "$SECRET_ID" ]]; then
  echo "ERROR: MES_CORE_DB_SECRET_ID not provided and auto-discovery failed." >&2
  echo "Fix: attach IAM role to EC2 (scripts/iam/ec2-mes-core-secret-read.json) OR set MesCoreDbSecretId in deploy-config.ps1" >&2
  echo "RDS console: nyra-mes-core -> Configuration -> Manage credentials -> Secret ARN" >&2
  exit 1
fi

echo "Using MES_CORE_DB_SECRET_ID (length ${#SECRET_ID})"

# Args before heredoc — placing them after <<PY wrongly runs .env as a Python script.
"$PYTHON" - "$ENV_FILE" "$SECRET_ID" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
secret_id = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

updates = {
    "MES_CORE_DB_SECRET_ID": secret_id,
    "MES_CORE_AWS_REGION": "eu-north-1",
    "MES_CORE_DB_PASSWORD": "",
}
seen = set()
out = []
for line in lines:
    if "=" in line and not line.strip().startswith("#"):
        key = line.split("=", 1)[0].strip()
        if key in updates:
            val = updates[key]
            out.append(f"{key}={val}")
            seen.add(key)
            continue
    out.append(line)
for key, val in updates.items():
    if key not in seen:
        out.append(f"{key}={val}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"Updated {path} — password cleared, secret id set.")
PY

"$PYTHON" "$API_DIR/scripts/resolve_mes_core_secret.py" || {
  echo "ERROR: DB connection failed after secret sync." >&2
  exit 1
}

if systemctl is-active --quiet "$SERVICE" 2>/dev/null || systemctl list-units --type=service --all 2>/dev/null | grep -q "$SERVICE"; then
  sudo systemctl restart "$SERVICE"
  sleep 2
fi

curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null && echo "API health OK on port ${API_PORT}" || echo "WARN: health check failed on port ${API_PORT}"
