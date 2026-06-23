"""Find env file with working nyra_mes_core RDS credentials (no secrets printed)."""
from pathlib import Path
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

CANDIDATES = [
    Path(__file__).resolve().parents[1] / ".env",
    Path(__file__).resolve().parents[1] / ".env.production",
    Path(r"d:/Sudha/Nyra/MES/ActivatedCarbon/backend-api/.env.production"),
    Path(r"d:/Sudha/Nyra/MES/ActivatedCarbon/backend-api/.env.nyraservices"),
    Path(r"d:/Sudha/Nyra/MES/ActivatedCarbon/backend-api/.env"),
    Path(r"d:/Sudha/Nyra/MES/ActivatedCarbon/testbed/.env.production"),
    Path(r"d:/Sudha/Nyra/MES/.env.local"),
    Path(r"d:/Sudha/Nyra/nyra-smart-modbus-sim-api/.env.production"),
]

HOST = "nyra-mes-core.ct6oskiisvfb.eu-north-1.rds.amazonaws.com"


def try_file(path: Path) -> bool:
    if not path.exists():
        return False
    load_dotenv(path, override=True)
    password = os.getenv("MES_CORE_DB_PASSWORD", "")
    user = os.getenv("MES_CORE_DB_USER", "mescore")
    host = os.getenv("MES_CORE_DB_HOST", HOST)
    port = os.getenv("MES_CORE_DB_PORT", "5432")
    db = os.getenv("MES_CORE_DB_NAME", "postgres")
    secret = os.getenv("MES_CORE_DB_SECRET_ID", "").strip()
    if secret:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from app.core.mes_core_credentials import clear_mes_core_db_credentials_cache, get_mes_core_db_credentials

            os.environ["MES_CORE_DB_SECRET_ID"] = secret
            clear_mes_core_db_credentials_cache()
            creds = get_mes_core_db_credentials()
            password = creds.password
            user = creds.user
            host = creds.host
            port = creds.port
            db = creds.name
        except Exception:
            return False
    if not password:
        return False
    url = (
        f"postgresql+psycopg2://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}"
    )
    try:
        with create_engine(url, connect_args={"sslmode": "require", "connect_timeout": 8}).connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"OK:{path}")
        return True
    except Exception:
        return False


def main() -> int:
    for path in CANDIDATES:
        if try_file(path):
            return 0
    print("NONE")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
