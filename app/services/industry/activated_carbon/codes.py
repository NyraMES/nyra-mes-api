"""Activated Carbon business codes — PostgreSQL nextval with AC prefixes."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.mes_core.ids import _nextval

AC_ID_PAD_WIDTH = 4

# entity key -> (sequence name, human-readable prefix)
AC_CODE_SPECS: dict[str, tuple[str, str]] = {
    "ac_customer": ("core.customer_code_seq", "CUST-AC-"),
    "ac_supplier": ("core.supplier_code_seq", "SUP-AC-"),
    "ac_raw_product": ("core.product_code_seq", "RAW-AC-"),
    "ac_finished_product": ("core.product_code_seq", "FG-AC-"),
    "ac_routing": ("core.routing_code_seq", "RT-AC-"),
    "ac_customer_order": ("core.customer_order_code_seq", "ORD-AC-"),
    "ac_customer_order_line": ("core.customer_order_line_code_seq", "ORDL-AC-"),
    "ac_production_order": ("core.production_order_code_seq", "PO-AC-"),
    "ac_production_lot": ("core.lot_code_seq", "LOT-AC-"),
    "ac_quality_check": ("core.quality_check_code_seq", "QC-AC-"),
    "ac_dispatch": ("core.dispatch_code_seq", "DISP-AC-"),
    "ac_operation_execution": ("core.execution_code_seq", "EXEC-AC-"),
}

# Minimum suffix already issued for demo seed (next code = floor + 1 when DB empty).
AC_SEQUENCE_FLOORS: dict[str, int] = {
    "core.customer_code_seq": 0,
    "core.customer_order_code_seq": 0,
    "core.customer_order_line_code_seq": 0,
    "core.production_order_code_seq": 0,
    "core.lot_code_seq": 0,
    "core.quality_check_code_seq": 0,
    "core.execution_code_seq": 0,
    "core.feasibility_check_code_seq": 0,
    "core.schedule_code_seq": 0,
    "core.dispatch_code_seq": 0,
}

# Shared PostgreSQL sequences — table/column + optional LIKE filter on business code.
AC_SEQUENCE_CODE_SOURCES: dict[str, list[tuple[str, str, Optional[str]]]] = {
    "core.customer_code_seq": [("mst.customer", "customer_code", "CUST-AC-%")],
    "core.customer_order_code_seq": [("trn.customer_order", "order_code", "ORD-AC-%")],
    "core.customer_order_line_code_seq": [
        ("trn.customer_order_line", "line_code", "ORDL-AC-%")
    ],
    "core.production_order_code_seq": [
        ("trn.production_order", "production_order_code", "PO-AC-%")
    ],
    "core.lot_code_seq": [("trn.production_lot", "lot_code", "LOT-AC-%")],
    "core.quality_check_code_seq": [("qms.quality_check", "check_code", "QC-AC-%")],
    "core.execution_code_seq": [
        ("exec.operation_execution", "execution_code", "EXEC-AC-%")
    ],
    "core.dispatch_code_seq": [
        ("qms.quality_check", "check_code", "DISP-AC-%")
    ],
    "core.feasibility_check_code_seq": [
        ("trn.feasibility_check", "check_code", "FEAS%")
    ],
}


def _max_numeric_suffix(
    db: Session,
    table: str,
    column: str,
    tenant_id: Optional[UUID] = None,
    code_like: Optional[str] = None,
) -> int:
    """Highest trailing integer suffix for a business-code column."""
    where = []
    params: dict = {}
    if tenant_id is not None:
        where.append("tenant_id = :tenant_id")
        params["tenant_id"] = str(tenant_id)
    if code_like:
        where.append(f"{column} LIKE :code_like")
        params["code_like"] = code_like
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    row = db.execute(
        text(
            f"""
            SELECT COALESCE(
                MAX((regexp_match({column}, '([0-9]+)$'))[1]::bigint),
                0
            )
            FROM {table}
            {where_sql}
            """
        ),
        params,
    ).scalar()
    return int(row or 0)


def generate_ac_business_code(db: Session, entity: str) -> str:
    if entity not in AC_CODE_SPECS:
        raise ValueError(f"Unknown AC entity for ID generation: {entity}")
    sequence, prefix = AC_CODE_SPECS[entity]
    n = _nextval(db, sequence)
    return f"{prefix}{n}"


def resolve_ac_business_code(
    db: Session,
    *,
    provided: Optional[str],
    entity: str,
) -> str:
    code = (provided or "").strip()
    if code:
        return code
    return generate_ac_business_code(db, entity)


def sync_ac_sequences(db: Session, tenant_id: Optional[UUID] = None) -> None:
    """Advance sequences past existing business codes (shared PostgreSQL seq).

    When ``tenant_id`` is None, scan all tenants — use after wiping every AC tenant.
    """
    for seq, floor in AC_SEQUENCE_FLOORS.items():
        max_used = floor
        for table, column, code_like in AC_SEQUENCE_CODE_SOURCES.get(seq, ()):
            max_used = max(
                max_used,
                _max_numeric_suffix(db, table, column, tenant_id, code_like),
            )
        if max_used <= 0:
            db.execute(text(f"SELECT setval('{seq}', 1, false)"))
        else:
            db.execute(
                text(f"SELECT setval('{seq}', :value, true)"),
                {"value": max_used},
            )
    db.commit()


def reset_ac_sequences_to_seed(db: Session, tenant_id: Optional[UUID] = None) -> None:
    """Re-align shared sequences from tenant data (or demo floors when empty)."""
    sync_ac_sequences(db, tenant_id)


def sync_ac_sequences_global(db: Session) -> None:
    """Re-align shared sequences from all tenants (after multi-tenant wipe + seed)."""
    sync_ac_sequences(db, tenant_id=None)


def reset_ac_sequences_empty(db: Session) -> None:
    """Set AC-related PostgreSQL sequences so the next generated code uses suffix 1."""
    sequences = set(AC_SEQUENCE_FLOORS) | {spec[0] for spec in AC_CODE_SPECS.values()}
    for seq in sorted(sequences):
        # PostgreSQL sequences cannot be set below 1; is_called=false => next nextval returns 1.
        db.execute(text(f"SELECT setval('{seq}', 1, false)"))
    db.commit()
