#!/usr/bin/env bash
set -euo pipefail
set -a
source /home/ubuntu/nyra-mes-api/.env
set +a
export PGPASSWORD="$MES_CORE_DB_PASSWORD"
psql -h "$MES_CORE_DB_HOST" -U "$MES_CORE_DB_USER" -d "$MES_CORE_DB_NAME" -p "$MES_CORE_DB_PORT" -f /tmp/migrate_routing_operation_code_unique.sql
