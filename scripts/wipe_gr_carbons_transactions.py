"""Wipe GR Carbons transactional data and realign business-code sequences.

Keeps masters, users, routing, and other tenants. Does not re-seed process flow.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.tenant_context import resolve_tenant
from app.db.mes_core_database import get_mes_core_engine
from app.models.mes_core.master import Equipment, Resource
from app.models.mes_core.platform import Tenant
from app.services.industry.activated_carbon.codes import (
    AC_SEQUENCE_CODE_SOURCES,
    AC_SHOP_CODE_SEQUENCES,
    ALL_CORE_CODE_SEQUENCES,
    _max_numeric_suffix,
    reset_ac_sequences_empty,
)
from app.services.industry.activated_carbon.work_orders import META_KEY as WORK_ORDER_META_KEY

TENANT_CODE = "GR_CARBONS"
WORKSPACE_CODE = "GR_CARBONS_ACTIVATED_CARBON"

TXN_TABLES = (
    "qms.quality_result",
    "qms.quality_check",
    "exec.parameter_reading",
    "exec.operation_execution",
    "trn.feasibility_check",
    "trn.dispatch",
    "trn.production_lot",
    "trn.production_order",
    "trn.customer_order_line",
    "trn.customer_order",
    "kg.triple_store_staging",
)

MASTER_TABLES = (
    "mst.customer",
    "mst.supplier",
    "mst.product",
    "mst.resource",
    "mst.equipment",
    "mst.routing",
)


def _count(db: Session, table: str, tenant_id: str | None = None) -> int:
    if tenant_id is None:
        return int(db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)
    return int(
        db.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        ).scalar()
        or 0
    )


def _print_counts(db: Session, tenant_id: str, title: str) -> None:
    print(title)
    for table in TXN_TABLES:
        print(f"  {table:32} { _count(db, table, tenant_id)}")
    for table in MASTER_TABLES:
        n = _count(db, table, tenant_id)
        print(f"  {table:32} {n}  (kept)")


def wipe_tenant_transactions(db: Session, tenant_id: str) -> None:
    for table in TXN_TABLES:
        result = db.execute(
            text(f"DELETE FROM {table} WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
        print(f"  deleted {result.rowcount:>5}  {table}")
    db.commit()


RESOURCE_TXN_KEYS = (
    "kiln_feed_events",
    "kiln_output_bags",
    "kiln_output_seq",
    "destoning_loaded_bags",
    "destoning_output_bags",
    "destoning_load_events",
    "active_lot_code",
    "active_lot_codes",
    "loaded_kg",
    "kiln_resource_claimed",
    "kiln_live_status",
    "current_work_order_code",
    "claimed_lot_code",
    "in_use_count",
    "active_execution_code",
)


def wipe_shop_floor_metadata(db: Session, tenant_id: str) -> None:
    """Clear kiln/destoner/post-activation bags on resources. Keep destoner CTC and masters."""
    resources = db.query(Resource).filter(Resource.tenant_id == tenant_id).all()
    changed = 0
    for row in resources:
        meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
        dirty = False
        role = str(meta.get("role") or "").lower()
        code = str(row.resource_code or "").upper()
        if role == "post_activation" or code == "RES-POSTACT-01":
            if meta.get("stations"):
                meta["stations"] = {}
                dirty = True
        for key in RESOURCE_TXN_KEYS:
            if key in meta:
                meta.pop(key, None)
                dirty = True
        if dirty:
            row.metadata_ = meta
            flag_modified(row, "metadata_")
            changed += 1
    equipment = db.query(Equipment).filter(Equipment.tenant_id == tenant_id).all()
    for row in equipment:
        meta = dict(row.metadata_ if isinstance(row.metadata_, dict) else {})
        dirty = False
        for key in ("active_lot_code", "active_execution_code", "in_use_count"):
            if key in meta:
                meta.pop(key, None)
                dirty = True
        if dirty:
            row.metadata_ = meta
            flag_modified(row, "metadata_")
            changed += 1
    tenant = db.get(Tenant, tenant_id)
    if tenant is not None:
        meta = dict(tenant.metadata_ if isinstance(tenant.metadata_, dict) else {})
        rows = meta.get(WORK_ORDER_META_KEY)
        if isinstance(rows, list):
            count = len([item for item in rows if isinstance(item, dict)])
            meta[WORK_ORDER_META_KEY] = []
            tenant.metadata_ = meta
            flag_modified(tenant, "metadata_")
            print(f"  deleted {count} work orders")
    db.commit()
    print(f"  cleared shop-floor metadata on {changed} resource/equipment rows")


def realign_sequences(db: Session, tenant_id: str) -> None:
    """Shop bags start at 1. Shared sequences sit past remaining rows in every tenant."""
    reset_ac_sequences_empty(db)
    for seq in (*ALL_CORE_CODE_SEQUENCES, *AC_SHOP_CODE_SEQUENCES):
        db.execute(text(f"CREATE SEQUENCE IF NOT EXISTS {seq}"))
        max_used = 0
        for table, column, code_like in AC_SEQUENCE_CODE_SOURCES.get(seq, ()):
            max_used = max(
                max_used,
                _max_numeric_suffix(db, table, column, None, code_like),
            )
        if seq in AC_SHOP_CODE_SEQUENCES:
            max_used = 0
        if max_used <= 0:
            db.execute(text(f"SELECT setval('{seq}', 1, false)"))
        else:
            db.execute(
                text(f"SELECT setval('{seq}', :value, true)"),
                {"value": max_used},
            )
    db.commit()


def show_sequences(db: Session) -> None:
    rows = db.execute(
        text(
            """
            SELECT schemaname, sequencename,
                   pg_sequence_last_value(format('%I.%I', schemaname, sequencename)::regclass) AS last_value
            FROM pg_sequences
            WHERE schemaname = 'core'
              AND (
                sequencename LIKE '%_code_seq'
                OR sequencename LIKE 'ac_%'
              )
            ORDER BY sequencename
            """
        )
    ).fetchall()
    print("=== sequences (last issued) ===")
    for schema, name, last_value in rows:
        print(f"  {schema}.{name:28} last={last_value}")


def main() -> int:
    engine = get_mes_core_engine()
    if engine is None:
        print("ERROR: MES_CORE is not configured")
        return 1
    db = Session(bind=engine)
    tenant = resolve_tenant(db, TENANT_CODE, WORKSPACE_CODE)
    tid = str(tenant.tenant_id)
    print(f"Tenant {TENANT_CODE}  workspace {WORKSPACE_CODE}")
    _print_counts(db, tid, "Before wipe:")
    print("Wiping GR Carbons transactional rows (masters kept)...")
    wipe_tenant_transactions(db, tid)
    print("Clearing kiln/destoner bags and work-order loads...")
    wipe_shop_floor_metadata(db, tid)
    try:
        sam = resolve_tenant(db, "SAM_CARBONS_DEMO", None)
        print("Wiping SAM_CARBONS_DEMO transactional rows (shared AC sequences)...")
        wipe_tenant_transactions(db, str(sam.tenant_id))
        wipe_shop_floor_metadata(db, sam.tenant_id)
    except Exception as exc:
        print(f"Skip SAM_CARBONS_DEMO wipe: {exc}")
    print("Resetting sequences...")
    realign_sequences(db, tid)
    _print_counts(db, tid, "After wipe:")
    show_sequences(db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
