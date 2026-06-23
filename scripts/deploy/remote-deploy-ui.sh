#!/usr/bin/env bash
set -euo pipefail

UI_DIR="${1:-/var/www/nyraservices-testbed/mes}"
STAGING="${2:-/tmp/nyra-mes-ui-dist}"

if [[ ! -d "$STAGING" ]]; then
  echo "ERROR: staging dir missing: $STAGING"
  exit 1
fi

sudo mkdir -p "$UI_DIR"
sudo rsync -a --delete "$STAGING"/ "$UI_DIR"/
echo "UI synced to $UI_DIR"
ls -la "$UI_DIR" | head -n 10
