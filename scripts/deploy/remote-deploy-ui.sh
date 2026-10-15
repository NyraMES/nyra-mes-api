#!/usr/bin/env bash
set -euo pipefail

UI_DIR="${1:-/home/ubuntu/testbed/tenants/mes}"
STAGING="${2:-/tmp/nyra-mes-ui-dist}"

if [[ ! -d "$STAGING" ]]; then
  echo "ERROR: staging dir missing: $STAGING"
  exit 1
fi

mkdir -p "$UI_DIR" "$UI_DIR/assets"
# Replace index.html and root files, but keep older hashed files in assets/.
# A tab opened before this deploy still imports the previous chunk names.
rsync -a --delete --exclude '/assets/' "$STAGING"/ "$UI_DIR"/
rsync -a "$STAGING/assets"/ "$UI_DIR/assets"/
echo "UI synced to $UI_DIR"
ls -la "$UI_DIR" | head -n 10
