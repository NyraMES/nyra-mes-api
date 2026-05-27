"""Business ID generation utility.

The platform prefers human-readable, monotonically increasing business IDs
(``CUST00001``, ``ORD00001``, ``LOT00001``, ``WO00001``, ...) over UUIDs.
These codes are stored in ``<entity>_code`` columns alongside a separate
bigint surrogate PK named ``id``.

Strategy
--------
1. **PostgreSQL sequences** (preferred): each entity has a dedicated sequence
   (e.g. ``mst.customer_seq``, ``trn.order_seq``, ``trn.lot_seq``). The
   utility calls ``SELECT nextval('<sequence>')`` to grab a lock-free,
   gap-tolerant, monotonically increasing integer.
2. **MAX(<entity>_code) fallback**: if the sequence does not exist (older
   environments, sqlite test fixtures, etc.), the utility synthesises the
   next number from the existing data using
   ``SELECT MAX(<column>) FROM <table> WHERE <column> LIKE 'PREFIX%'``
   and increments. This keeps the API usable before a DBA materialises the
   sequence DDL.

Both paths return a string formed as ``f"{prefix}{n:0{width}d}"``.

Example::

    code = generate_business_id(
        db,
        prefix="CUST",
        sequence="mst.customer_seq",
        fallback_table="mst.customer",
        fallback_column="customer_code",
    )
    # -> "CUST00001"
"""

from __future__ import annotations

import re
import threading
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings


_lock = threading.Lock()


def _is_postgres(session: Session) -> bool:
    bind: Optional[Engine] = session.get_bind() if hasattr(session, "get_bind") else None
    try:
        return bool(bind and bind.dialect.name == "postgresql")
    except Exception:
        return False


def _next_from_sequence(session: Session, sequence: Optional[str]) -> Optional[int]:
    """``SELECT nextval(sequence)``; ``None`` on absence/error."""
    if not (sequence and _is_postgres(session)):
        return None
    try:
        result = session.execute(text(f"SELECT nextval('{sequence}')")).scalar()
        return int(result) if result is not None else None
    except SQLAlchemyError:
        session.rollback()
        return None


def _next_from_max(
    session: Session,
    prefix: str,
    table: Optional[str],
    column: Optional[str],
) -> int:
    """Compute the next number by scanning existing codes of the form
    ``PREFIXNNNNN`` in ``table.column``. Returns ``1`` when none exist."""
    if not (table and column):
        return 1
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    try:
        rows = session.execute(
            text(
                f"SELECT {column} FROM {table} "
                f"WHERE {column} LIKE :p ESCAPE '\\'"
            ),
            {"p": f"{prefix}%"},
        ).all()
    except SQLAlchemyError:
        session.rollback()
        return 1
    max_n = 0
    for (raw,) in rows:
        if not raw:
            continue
        match = pattern.match(str(raw))
        if match:
            try:
                n = int(match.group(1))
                if n > max_n:
                    max_n = n
            except ValueError:
                continue
    return max_n + 1


def generate_business_id(
    db: Session,
    prefix: str,
    *,
    sequence: Optional[str] = None,
    fallback_table: Optional[str] = None,
    fallback_column: Optional[str] = None,
    pad_width: Optional[int] = None,
    # Backwards-compatibility shim: legacy callers still pass
    # ``schema=``, ``table=``, ``column=``.
    schema: Optional[str] = None,
    table: Optional[str] = None,
    column: Optional[str] = None,
) -> str:
    """Generate the next business ID for ``prefix``.

    Parameters
    ----------
    db:
        SQLAlchemy session bound to the application database.
    prefix:
        ID prefix (e.g. ``"CUST"``, ``"ORD"``, ``"LOT"``, ``"WO"``).
    sequence:
        Fully-qualified PostgreSQL sequence (e.g. ``"trn.order_seq"``).
        Preferred. If ``None`` the function falls back to MAX(column).
    fallback_table, fallback_column:
        Used for the MAX(<column>) fallback when the sequence does not
        exist. Pass the fully-qualified table (``"mst.customer"``) and the
        ``<entity>_code`` column (``"customer_code"``).
    pad_width:
        Width of the numeric tail. Defaults to ``settings.id_pad_width``.

    Returns
    -------
    str
        Business ID formed as ``"{prefix}{n:0{width}d}"``.
    """
    if not prefix:
        raise ValueError("prefix is required")

    # Legacy parameter forwarding (older call sites pass ``table`` / ``column``).
    fallback_table = fallback_table or (
        f"{schema}.{table}" if schema and table else table
    )
    fallback_column = fallback_column or column

    width = pad_width if pad_width is not None else settings.id_pad_width

    with _lock:
        n = _next_from_sequence(db, sequence)
        if n is None:
            n = _next_from_max(db, prefix, fallback_table, fallback_column)

    return f"{prefix}{n:0{width}d}"


__all__ = ["generate_business_id"]
