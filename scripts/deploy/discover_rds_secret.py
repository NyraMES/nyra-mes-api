#!/usr/bin/env python3
"""Print RDS master secret id for nyra_mes_core (run on testbed EC2 with IAM role)."""
from __future__ import annotations

import sys

try:
    import boto3
except ImportError:
    print("ERROR: boto3 not installed", file=sys.stderr)
    raise SystemExit(1)

REGION = "eu-north-1"
HOST_HINT = "nyra-mes-core"

rds = boto3.client("rds", region_name=REGION)
found = False
for db in rds.describe_db_instances().get("DBInstances", []):
    ident = db.get("DBInstanceIdentifier") or ""
    endpoint = (db.get("Endpoint") or {}).get("Address") or ""
    if HOST_HINT not in ident.lower() and HOST_HINT not in endpoint.lower():
        continue
    found = True
    secret = db.get("MasterUserSecret") or {}
    print(f"instance={ident}")
    print(f"endpoint={endpoint}")
    arn = secret.get("SecretArn") or ""
    if arn:
        print(f"MES_CORE_DB_SECRET_ID={arn}")
    else:
        print("WARN: no MasterUserSecret on instance — enable managed password in RDS", file=sys.stderr)
        raise SystemExit(2)

if not found:
    print(f"ERROR: no RDS instance matching {HOST_HINT}", file=sys.stderr)
    raise SystemExit(1)
