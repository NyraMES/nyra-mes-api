"""Database engine and session for nyra_mes_core (multi-tenant platform DB).

The legacy API continues to use ``app.db.database`` (``DB_*`` env vars).
This module is only used by ``/api/*`` routes and tenant context resolution.

Set ``MES_CORE_ENABLED=true`` and ``MES_CORE_DB_*`` in ``.env`` to activate.
"""

from __future__ import annotations

from typing import Generator, Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.mes_core_credentials import get_mes_core_db_credentials

_mes_core_engine: Optional[Engine] = None
_MesCoreSessionLocal: Optional[sessionmaker] = None


def _build_mes_core_url() -> str:
    creds = get_mes_core_db_credentials()
    return (
        f"postgresql+psycopg2://{quote_plus(creds.user)}:"
        f"{quote_plus(creds.password)}"
        f"@{creds.host}:{creds.port}/{creds.name}"
    )


def get_mes_core_engine() -> Optional[Engine]:
    """Lazy-create the nyra_mes_core engine when the feature is enabled."""
    global _mes_core_engine, _MesCoreSessionLocal
    if not settings.mes_core_enabled:
        return None
    if _mes_core_engine is None:
        _mes_core_engine = create_engine(
            _build_mes_core_url(),
            connect_args={"sslmode": "require"},
            pool_pre_ping=True,
        )
        _MesCoreSessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=_mes_core_engine,
        )
    return _mes_core_engine


def open_mes_core_session() -> Optional[Session]:
    """A short-lived session, or None when nyra_mes_core is not configured."""
    get_mes_core_engine()
    if _MesCoreSessionLocal is None:
        return None
    return _MesCoreSessionLocal()


def get_mes_core_db() -> Generator[Session, None, None]:
    """FastAPI dependency — yields a session bound to nyra_mes_core."""
    engine = get_mes_core_engine()
    if engine is None or _MesCoreSessionLocal is None:
        from app.core.exceptions import ServiceUnavailableError

        raise ServiceUnavailableError(
            "nyra_mes_core is not configured. Set MES_CORE_ENABLED=true and "
            "MES_CORE_DB_* variables in .env."
        )
    db = _MesCoreSessionLocal()
    try:
        yield db
    finally:
        db.close()
