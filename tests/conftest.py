"""Test fixtures.

The tests run against the live Postgres DB configured in ``.env`` (the same
one the dev backend uses). We don't try to re-create the schema in SQLite
anymore - the model surface relies on Postgres sequences and views.

Auth is disabled for API tests so ``TestClient`` does not need Cognito tokens.
"""

import os

# Must be set before ``app`` (and ``settings``) are imported — dotenv won't
# override an env var that is already present.
os.environ["AUTH_ENABLED"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import SessionLocal
from app.main import app


def db_reachable() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
    except Exception:
        return False


requires_live_db = pytest.mark.skipif(
    os.getenv("NYRA_SKIP_DB_TESTS") == "1" or not db_reachable(),
    reason="Live Postgres DB unreachable; set NYRA_SKIP_DB_TESTS=0 to require it.",
)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
