#!/usr/bin/env python3
"""Apply migrate_routing_operation_code_unique.sql using API .env credentials."""
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text

ENV_PATH = Path("/home/ubuntu/nyra-mes-api/.env")
SQL_PATH = Path("/tmp/migrate_routing_operation_code_unique.sql")

env = dotenv_values(ENV_PATH)
url = (
    f"postgresql://{env['MES_CORE_DB_USER']}:{env['MES_CORE_DB_PASSWORD']}"
    f"@{env['MES_CORE_DB_HOST']}:{env['MES_CORE_DB_PORT']}/{env['MES_CORE_DB_NAME']}"
)
sql = SQL_PATH.read_text(encoding="utf-8")
engine = create_engine(url)
with engine.begin() as conn:
    for statement in sql.split(";"):
        stmt = statement.strip()
        if stmt:
            conn.execute(text(stmt))
print("migration ok")
