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

_mes_core_engine: Optional[Engine] = None
_MesCoreSessionLocal: Optional[sessionmaker] = None


def _build_mes_core_url() -> str:
    return (
        f"postgresql+psycopg2://{quote_plus(settings.mes_core_db_user)}:"
        f"{quote_plus(settings.mes_core_db_password)}"
        f"@{settings.mes_core_db_host}:{settings.mes_core_db_port}/"
        f"{settings.mes_core_db_name}"
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
