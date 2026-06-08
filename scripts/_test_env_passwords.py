from pathlib import Path
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]


def test(label: str, env_file: str) -> bool:
    load_dotenv(ROOT / env_file, override=True)
    password = os.getenv("MES_CORE_DB_PASSWORD", "")
    url = (
        f"postgresql+psycopg2://{quote_plus(os.getenv('MES_CORE_DB_USER', ''))}:"
        f"{quote_plus(password)}@{os.getenv('MES_CORE_DB_HOST')}:{os.getenv('MES_CORE_DB_PORT')}/"
        f"{os.getenv('MES_CORE_DB_NAME')}"
    )
    try:
        engine = create_engine(url, connect_args={"sslmode": "require"}, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("select 1")).scalar()
        print(f"{label}: OK (len={len(password)})")
        return True
    except Exception as exc:
        print(f"{label}: FAIL (len={len(password)}) — {exc}")
        return False


ok_env = test(".env", ".env")
ok_prod = test(".env.production", ".env.production")
sys.exit(0 if (ok_env or ok_prod) else 1)
