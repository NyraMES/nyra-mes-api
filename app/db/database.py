import os
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "").strip()
DB_PORT = os.getenv("DB_PORT", "5432").strip()
DB_NAME = os.getenv("DB_NAME", "").strip()
DB_USER = os.getenv("DB_USER", "").strip()
DB_PASSWORD = os.getenv("DB_PASSWORD", "").strip()

# URL-encode user/password so special characters like '#', '@', '/', ' '
# don't corrupt the connection URL.
DB_URL = (
    f"postgresql+psycopg2://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# AWS RDS PostgreSQL requires SSL by default; without it the server replies
# with "no pg_hba.conf entry ... no encryption".
engine = create_engine(
    DB_URL,
    connect_args={"sslmode": "require"},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
