"""Resolve nyra_mes_core credentials from AWS Secrets Manager or validate env setup.

Usage (venv active, from repo root):
    python scripts/resolve_mes_core_secret.py              # test connection
    python scripts/resolve_mes_core_secret.py --write-env  # sync password into .env
    python scripts/resolve_mes_core_secret.py --print-env  # print export lines (no secrets in logs)

Requires either MES_CORE_DB_SECRET_ID (AWS creds or EC2 role) or MES_CORE_DB_PASSWORD in .env.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _env_path() -> Path:
    return ROOT / ".env"


def _update_env_file(creds) -> None:
    path = _env_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updates = {
        "MES_CORE_DB_HOST": creds.host,
        "MES_CORE_DB_PORT": creds.port,
        "MES_CORE_DB_NAME": creds.name,
        "MES_CORE_DB_USER": creds.user,
        "MES_CORE_DB_PASSWORD": creds.password,
    }
    seen = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else None
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve nyra_mes_core DB credentials")
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Write resolved host/user/password into .env (for scripts that still read env directly)",
    )
    parser.add_argument(
        "--print-env",
        action="store_true",
        help="Print MES_CORE_DB_* lines without password value",
    )
    args = parser.parse_args()

    from app.core.mes_core_credentials import clear_mes_core_db_credentials_cache, get_mes_core_db_credentials
    from sqlalchemy import text

    from app.db.mes_core_database import get_mes_core_engine

    clear_mes_core_db_credentials_cache()
    try:
        creds = get_mes_core_db_credentials()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.print_env:
        print(f"MES_CORE_DB_HOST={creds.host}")
        print(f"MES_CORE_DB_PORT={creds.port}")
        print(f"MES_CORE_DB_NAME={creds.name}")
        print(f"MES_CORE_DB_USER={creds.user}")
        print("MES_CORE_DB_PASSWORD=***")
        return 0

    engine = get_mes_core_engine()
    if engine is None:
        print("ERROR: MES_CORE_ENABLED is false", file=sys.stderr)
        return 1

    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT current_database(), current_user")).fetchone()
    except Exception as exc:
        print(f"ERROR: DB connection failed — {exc}", file=sys.stderr)
        return 1

    print(f"OK: connected as {row[1]} on database {row[0]}")
    if args.write_env:
        _update_env_file(creds)
        print(f"Updated {_env_path()} with credentials from Secrets Manager / env")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
