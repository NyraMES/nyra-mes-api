"""Test mes_core DB connection using .env in cwd."""
from pathlib import Path
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

password = os.getenv("MES_CORE_DB_PASSWORD", "")
print("pwd_len", len(password))
print("has_gt", ">" in password)
print("has_lt", "<" in password)

url = (
    f"postgresql+psycopg2://{quote_plus(os.getenv('MES_CORE_DB_USER', ''))}:"
    f"{quote_plus(password)}@{os.getenv('MES_CORE_DB_HOST')}:{os.getenv('MES_CORE_DB_PORT')}/"
    f"{os.getenv('MES_CORE_DB_NAME')}"
)
try:
    engine = create_engine(url, connect_args={"sslmode": "require"}, pool_pre_ping=True)
    with engine.connect() as conn:
        print("db_ok", conn.execute(text("select 1")).scalar())
except Exception as exc:
    print("db_fail", exc)
    sys.exit(1)
