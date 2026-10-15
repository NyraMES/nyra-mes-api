"""Activated Carbon business codes — PostgreSQL nextval with AC prefixes."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    "ac_customer_po": ("core.ac_customer_po_seq", "CUST_PO_"),
    "ac_work_order": ("core.ac_work_order_seq", "WO-AC-"),
    "ac_debit_note": ("core.ac_debit_note_seq", "DN-AC-"),
    "ac_customer_order_line": ("core.customer_order_line_code_seq", "ORDL-AC-"),
    "ac_production_order": ("core.production_order_code_seq", "PO-AC-"),
    "ac_production_lot": ("core.lot_code_seq", "LOT-AC-"),
    "ac_quality_check": ("core.quality_check_code_seq", "QC-AC-"),
    "ac_dispatch": ("core.dispatch_code_seq", "DISP-AC-"),
    "ac_operation_execution": ("core.execution_code_seq", "EXEC-AC-"),
}

ALL_CORE_CODE_SEQUENCES: tuple[str, ...] = (
    "core.supplier_code_seq",
    "core.customer_code_seq",
    "core.product_code_seq",
    "core.resource_code_seq",
    "core.equipment_code_seq",
    "core.routing_code_seq",
    "core.routing_operation_code_seq",
    "core.customer_order_code_seq",
    "core.customer_order_line_code_seq",
    "core.production_order_code_seq",
    "core.lot_code_seq",
    "core.feasibility_check_code_seq",
    "core.execution_code_seq",
    "core.schedule_code_seq",
    "core.quality_check_code_seq",
    "core.ncr_code_seq",
    "core.dispatch_code_seq",
    "core.ac_customer_po_seq",
    "core.ac_work_order_seq",
    "core.ac_debit_note_seq",
)

# Shop-floor bag sequences — created on first use, one per process prefix.
AC_SHOP_CODE_SEQUENCES: tuple[str, ...] = (
    "core.ac_bag_ri_seq",
    "core.ac_bag_ro_seq",
    "core.ac_kiln_out_ka_seq",
    "core.ac_kiln_out_kb_seq",
    "core.ac_deston_ds_seq",
    "core.ac_post_sc_seq",
    "core.ac_post_dd_seq",
    "core.ac_post_cr_seq",
    "core.ac_post_dm_seq",
    "core.ac_post_bl_seq",
    "core.ac_post_fg_seq",
)

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
    "core.ac_customer_po_seq": 0,
    "core.ac_work_order_seq": 0,
    "core.routing_code_seq": 0,
    "core.product_code_seq": 0,
}

# Shared PostgreSQL sequences — table/column + optional LIKE filter on business code.
AC_SEQUENCE_CODE_SOURCES: dict[str, list[tuple[str, str, Optional[str]]]] = {
    "core.customer_code_seq": [("mst.customer", "customer_code", "CUST-AC-%")],
    "core.customer_order_code_seq": [("trn.customer_order", "order_code", "ORD-AC-%")],
    "core.ac_customer_po_seq": [("trn.customer_order", "order_code", "CUST_PO_%")],
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
    "core.routing_code_seq": [("mst.routing", "routing_code", "RT-AC-%")],
    "core.product_code_seq": [
        ("mst.product", "product_code", "RAW-AC-%"),
        ("mst.product", "product_code", "FG-AC-%"),
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


def generate_ac_business_code(
    db: Session, entity: str, *, tenant_id: Optional[UUID] = None
) -> str:
    if entity not in AC_CODE_SPECS:
        raise ValueError(f"Unknown AC entity for ID generation: {entity}")
    sequence, prefix = AC_CODE_SPECS[entity]
    if entity in {"ac_customer_po", "ac_work_order", "ac_debit_note"}:
        db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {sequence}"))
    for _ in range(32):
        n = _nextval(db, sequence)
        if entity == "ac_supplier" and tenant_id is not None:
            max_used = _max_numeric_suffix(
                db, "mst.supplier", "supplier_code", tenant_id, f"{prefix}%"
            )
            if n <= max_used:
                db.execute(
                    text(f"SELECT setval('{sequence}', :value, true)"),
                    {"value": max_used},
                )
                n = _nextval(db, sequence)
            code = f"{prefix}{n}"
            taken = db.execute(
                text(
                    "SELECT 1 FROM mst.supplier "
                    "WHERE tenant_id = :tenant_id AND supplier_code = :code LIMIT 1"
                ),
                {"tenant_id": str(tenant_id), "code": code},
            ).scalar()
            if taken:
                continue
            return code
        code = f"{prefix}{n}"
        if entity == "ac_customer_po":
            taken = db.execute(
                text(
                    "SELECT 1 FROM trn.customer_order "
                    "WHERE order_code = :code"
                    + (" AND tenant_id = :tenant_id" if tenant_id is not None else "")
                    + " LIMIT 1"
                ),
                {"code": code, **({"tenant_id": str(tenant_id)} if tenant_id is not None else {})},
            ).scalar()
            if not taken:
                return code
            continue
        if entity == "ac_routing" and tenant_id is not None:
            taken = db.execute(
                text(
                    "SELECT 1 FROM mst.routing "
                    "WHERE tenant_id = :tenant_id AND routing_code = :code LIMIT 1"
                ),
                {"tenant_id": str(tenant_id), "code": code},
            ).scalar()
            if not taken:
                return code
            continue
        if entity == "ac_work_order" and tenant_id is not None:
            from app.models.mes_core.platform import Tenant

            tenant = db.get(Tenant, tenant_id)
            block = tenant.metadata_ if tenant is not None and isinstance(tenant.metadata_, dict) else {}
            rows = block.get("ac_activation_work_orders")
            taken = False
            if isinstance(rows, list):
                taken = any(
                    isinstance(item, dict) and str(item.get("work_order_code") or "") == code
                    for item in rows
                )
            if not taken:
                return code
            continue
        return code
    raise ValueError(f"Could not allocate unique code for {entity}")


def kiln_plant_letter(resource_name: str = "", resource_code: str = "") -> str:
    """Kiln A / RES-KILN-01 → A; Kiln B / Klin 02 / RES-KILN-0002 → B."""
    blob = f"{resource_name or ''} {resource_code or ''}".upper()
    match = re.search(r"\bK(?:ILN|LIN)?[-_\s]*([A-F])\b", blob)
    if match:
        return match.group(1)
    digits = re.search(r"(\d+)$", str(resource_code or ""))
    if not digits:
        digits = re.search(r"(\d+)\s*$", str(resource_name or "").strip())
    if digits:
        n = int(digits.group(1))
        if 1 <= n <= 26:
            return chr(64 + n)
    return "A"


def kiln_output_id_prefix(resource_name: str = "", resource_code: str = "") -> str:
    """Kiln A → KA, Kiln B → KB."""
    return f"K{kiln_plant_letter(resource_name, resource_code)}"


def next_process_bag_code(db: Session, process_prefix: str) -> str:
    """Process-prefixed bags: RI_BAG_001, RO_BAG_001."""
    token = re.sub(r"[^A-Z]", "", str(process_prefix or "").upper())
    if len(token) < 2:
        token = "BG"
    token = token[:2]
    seq_name = f"core.ac_bag_{token.lower()}_seq"
    db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name}"))
    n = int(db.execute(text(f"SELECT nextval('{seq_name}')")).scalar() or 1)
    return f"{token}_BAG_{n:03d}"


def plant_now(tz_name: Optional[str] = None) -> datetime:
    """Current time in the customer's plant timezone from core.tenant.timezone.

    Stored audit times stay in UTC. Bag serial dates and the plant day use this clock.
    The machine clock is not used. A blank or unknown timezone stays on UTC.
    """
    name = (tz_name or "").strip() or "UTC"
    try:
        return datetime.now(ZoneInfo(name))
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now(ZoneInfo("UTC"))


def plant_today(tz_name: Optional[str] = None) -> date:
    return plant_now(tz_name).date()


def _business_stamp(tz_name: Optional[str] = None) -> str:
    return plant_now(tz_name).strftime("%d%m%y")


def next_kiln_output_bag_code(db: Session, prefix: str, tz_name: Optional[str] = None) -> str:
    """KA_DDMMYY_##### using a Postgres sequence per kiln prefix."""
    token = str(prefix or "KA").upper()
    if not re.fullmatch(r"K[A-Z]", token):
        token = "KA"
    seq_name = f"core.ac_kiln_out_{token.lower()}_seq"
    db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name}"))
    n = int(db.execute(text(f"SELECT nextval('{seq_name}')")).scalar() or 1)
    return f"{token}_{_business_stamp(tz_name)}_{n:05d}"


def next_destoning_bag_code(db: Session, tz_name: Optional[str] = None) -> str:
    """DS_DDMMYY_##### using a Postgres sequence."""
    seq_name = "core.ac_deston_ds_seq"
    db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name}"))
    n = int(db.execute(text(f"SELECT nextval('{seq_name}')")).scalar() or 1)
    return f"DS_{_business_stamp(tz_name)}_{n:05d}"


def next_post_activation_bag_code(db: Session, prefix: str, tz_name: Optional[str] = None) -> str:
    """SC/CR/DD/DM/BL/FG_DDMMYY_##### using a Postgres sequence per process."""
    token = str(prefix or "PA").upper()
    if not re.fullmatch(r"[A-Z]{2}", token):
        token = "PA"
    seq_name = f"core.ac_post_{token.lower()}_seq"
    db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq_name}"))
    n = int(db.execute(text(f"SELECT nextval('{seq_name}')")).scalar() or 1)
    return f"{token}_{_business_stamp(tz_name)}_{n:05d}"


def resolve_ac_business_code(
    db: Session,
    *,
    provided: Optional[str],
    entity: str,
    tenant_id: Optional[UUID] = None,
) -> str:
    code = (provided or "").strip()
    if code:
        return code
    return generate_ac_business_code(db, entity, tenant_id=tenant_id)


def sync_ac_sequences(db: Session, tenant_id: Optional[UUID] = None) -> None:
    """Advance sequences past existing business codes (shared PostgreSQL seq).

    When ``tenant_id`` is None, scan all tenants — use after wiping every AC tenant.
    """
    for seq, floor in AC_SEQUENCE_FLOORS.items():
        db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq}"))
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
    """Set all core business-code sequences so the next generated code uses suffix 1."""
    for seq in (*ALL_CORE_CODE_SEQUENCES, *AC_SHOP_CODE_SEQUENCES):
        db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq} START 1"))
        # is_called=false => next nextval returns 1.
        db.execute(text(f"SELECT setval('{seq}', 1, false)"))
    db.commit()
