"""Legacy oemauto database session (optional).

When ``LEGACY_DB_ENABLED=false`` (nyra_mes_core-only mode), no connection is
opened to oemauto and legacy domain routers are not mounted in ``app.main``.

Active workflow: ``app.db.mes_core_database`` + ``/api/*`` routes.
"""

from __future__ import annotations

from typing import Generator, Optional
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_legacy_engine: Optional[Engine] = None
_LegacySessionLocal: Optional[sessionmaker] = None


def _legacy_db_configured() -> bool:
    return bool(
        settings.legacy_db_host
        and settings.legacy_db_name
        and settings.legacy_db_user
    )


def get_legacy_engine() -> Optional[Engine]:
    """Lazy-create the legacy engine only when explicitly enabled."""
    global _legacy_engine, _LegacySessionLocal
    if not settings.legacy_db_enabled or not _legacy_db_configured():
        return None
    if _legacy_engine is None:
        url = (
            f"postgresql+psycopg2://{quote_plus(settings.legacy_db_user)}:"
            f"{quote_plus(settings.legacy_db_password)}"
            f"@{settings.legacy_db_host}:{settings.legacy_db_port}/"
            f"{settings.legacy_db_name}"
        )
        _legacy_engine = create_engine(
            url,
            connect_args={"sslmode": "require"},
            pool_pre_ping=True,
        )
        _LegacySessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=_legacy_engine,
        )
    return _legacy_engine


def _require_legacy_session_local() -> sessionmaker:
    get_legacy_engine()
    if _LegacySessionLocal is None:
        from app.core.exceptions import ServiceUnavailableError

        raise ServiceUnavailableError(
            "Legacy oemauto database is disabled. Use nyra_mes_core /api/* routes. "
            "Set LEGACY_DB_ENABLED=true only if you still need /customer, /part, …"
        )
    return _LegacySessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for legacy single-tenant routes."""
    db = _require_legacy_session_local()()
    try:
        yield db
    finally:
        db.close()


class _SessionLocalFactory:
    def __call__(self) -> Session:
        return _require_legacy_session_local()()


SessionLocal = _SessionLocalFactory()


class _EngineProxy:
    """Lazy proxy so ``database.engine`` is never created when legacy is off."""

    def connect(self, *args, **kwargs):
        eng = get_legacy_engine()
        if eng is None:
            raise RuntimeError("Legacy database is disabled (LEGACY_DB_ENABLED=false)")
        return eng.connect(*args, **kwargs)

    def __getattr__(self, name: str):
        eng = get_legacy_engine()
        if eng is None:
            raise RuntimeError("Legacy database is disabled (LEGACY_DB_ENABLED=false)")
        return getattr(eng, name)


engine = _EngineProxy()
