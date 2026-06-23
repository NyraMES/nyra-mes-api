"""Apply working nyra_mes_core credentials to server .env (reads from local env file)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-env", required=True, help="Path to local env file with working creds")
    parser.add_argument("--target", default=str(ROOT / ".env"))
    args = parser.parse_args()

    src = Path(args.from_env)
    if not src.exists():
        print(f"Missing {src}", file=sys.stderr)
        return 1

    values = dotenv_values(src)
    password = values.get("MES_CORE_DB_PASSWORD") or ""
    secret_id = (values.get("MES_CORE_DB_SECRET_ID") or "").strip()
    if not password and not secret_id:
        print("No MES_CORE_DB_PASSWORD or MES_CORE_DB_SECRET_ID in source", file=sys.stderr)
        return 1

    target = Path(args.target)
    lines = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    updates = {
        "MES_CORE_DB_HOST": values.get("MES_CORE_DB_HOST") or "",
        "MES_CORE_DB_PORT": values.get("MES_CORE_DB_PORT") or "5432",
        "MES_CORE_DB_NAME": values.get("MES_CORE_DB_NAME") or "postgres",
        "MES_CORE_DB_USER": values.get("MES_CORE_DB_USER") or "mescore",
        "MES_CORE_DB_SECRET_ID": secret_id,
        "MES_CORE_AWS_REGION": values.get("MES_CORE_AWS_REGION") or "eu-north-1",
        "MES_CORE_DB_PASSWORD": password if not secret_id else "",
    }

    out = []
    seen = set()
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key = line.split("=", 1)[0]
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)
    for key, val in updates.items():
        if key not in seen and val is not None:
            out.append(f"{key}={val}")
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Updated {target} (secret_id={'yes' if secret_id else 'no'}, password={'yes' if password else 'no'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
