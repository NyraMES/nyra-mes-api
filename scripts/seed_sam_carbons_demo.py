"""Seed Activated Carbon validation data (non-video demo).

Business-code prefixes (auto-generated when omitted, 3-digit suffix):
  CUST-AC-001 customer (Masters / API)
  SUP-AC-001  supplier
  ORD-AC-001  raw material inward / customer order
  ORDL-AC-*   order lines
  PO-AC-*     production order
  LOT-AC-*    production lots
  EXEC-AC-*   operation executions
  QC-AC-*     quality checks
  RES-KILN-*  activation kiln (machine resource)
  EQ-KILN-*   kiln equipment
  RES-MACH-* / EQ-MACH-*  other machines
  RES-TOOL-* / RES-LAB-*  tools and labor pools

Master SKUs (fixed in SQL): RAW-COCO-SHELL, AC-GRAN-8x30, RT-AC-8x30-V1, RES-KILN-01, …

Usage (venv active, .env with MES_CORE_DB_PASSWORD):
  python scripts/seed_sam_carbons_demo.py --install-master
  python scripts/seed_sam_carbons_demo.py --reset --force
  python scripts/seed_sam_carbons_demo.py --reset-all --install-master --reset-sequences
  .\\scripts\\reset_sam_carbons_full.ps1   # full wipe + master + sequences + seed

Requires migration 003 (tenant + workspace + capabilities).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.tenant_context import resolve_tenant
from app.db.mes_core_database import get_mes_core_engine
from app.models.mes_core import Customer, CustomerOrder, Product, ProductionLot, Resource, Supplier
from app.schemas.mes_core.schemas import (
    AcKilnCreate,
    AcMakeToStockCreate,
    CustomerCreate,
    AcKilnFeedLotCreate,
    AcRawMaterialInwardCreate,
    AcRawMaterialQcCreate,
    SupplierCreate,
)
from app.services.industry.activated_carbon import adapter as ac_adapter
from app.services.industry.activated_carbon.codes import (
    reset_ac_sequences_empty,
    sync_ac_sequences,
)
from app.services.mes_core import feasibility as mes_core_feasibility
from app.services.mes_core.base import TenantRepository

TENANT_CODE = os.getenv("AC_TENANT_CODE", "GR_CARBONS")
WORKSPACE_CODE = os.getenv("AC_WORKSPACE_CODE", "GR_CARBONS_ACTIVATED_CARBON")

# Production client GR_CARBONS; demo playground remains SAM_CARBONS_DEMO*.
AC_TENANT_PREFIX = "GR_CARBONS"

MASTER_CUSTOMER_CODE = "CUST-AC-001"
RAW_PRODUCT_CODE = "RAW-COCO-SHELL"
FINISHED_PRODUCT_CODE = "AC-GRAN-8x30"
DEFAULT_KILN_RESOURCE_CODE = "RES-KILN-01"

MASTER_SQL_FILES = (
    ROOT / "scripts" / "db" / "nyra_sam_carbons_production_tenant.sql",
    ROOT / "scripts" / "db" / "nyra_sam_carbons_demo_tenant.sql",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _session() -> Session:
    engine = get_mes_core_engine()
    if engine is None:
        raise RuntimeError("MES_CORE is not enabled — set MES_CORE_ENABLED=true in .env")
    return Session(bind=engine)


def _ctx(db: Session):
    return resolve_tenant(db, TENANT_CODE, WORKSPACE_CODE)


def normalize_ac_display_names(db: Session, tenant) -> None:
    """Use GR Carbons plant labels in tenant, workspace, and seed customer records."""
    tid = str(tenant.tenant_id)
    db.execute(
        text(
            "UPDATE core.tenant SET tenant_name = 'GR Carbons' "
            "WHERE tenant_id = :tid"
        ),
        {"tid": tid},
    )
    if tenant.workspace_id is not None:
        db.execute(
            text(
                "UPDATE core.project_workspace SET workspace_name = 'GR Carbons — Activated Carbon' "
                "WHERE workspace_id = :wid"
            ),
            {"wid": str(tenant.workspace_id)},
        )
    db.execute(
        text(
            "UPDATE mst.customer SET customer_name = 'Demo Customer' "
            "WHERE tenant_id = :tid AND customer_code LIKE 'CUST-AC-%'"
        ),
        {"tid": tid},
    )
    db.commit()


def install_master_sql() -> None:
    engine = get_mes_core_engine()
    if engine is None:
        raise RuntimeError("MES_CORE is not enabled")
    applied = 0
    for path in MASTER_SQL_FILES:
        if not path.is_file():
            print(f"Skip: {path.name} not found")
            continue
        with engine.begin() as conn:
            conn.execute(text(path.read_text(encoding="utf-8")))
        print(f"OK: Applied {path.name}")
        applied += 1
    if applied == 0:
        raise FileNotFoundError("No master SQL files found under scripts/db/")


def reset_transactional(db: Session, tenant) -> None:
    tid = str(tenant.tenant_id if hasattr(tenant, "tenant_id") else tenant)
    for stmt in [
        "DELETE FROM qms.quality_result WHERE tenant_id = :tid",
        "DELETE FROM qms.quality_check WHERE tenant_id = :tid",
        "DELETE FROM exec.operation_execution WHERE tenant_id = :tid",
        "DELETE FROM trn.feasibility_check WHERE tenant_id = :tid",
        "DELETE FROM trn.production_lot WHERE tenant_id = :tid",
        "DELETE FROM trn.production_order WHERE tenant_id = :tid",
        "DELETE FROM trn.customer_order_line WHERE tenant_id = :tid",
        "DELETE FROM trn.customer_order WHERE tenant_id = :tid",
        "DELETE FROM trn.dispatch WHERE tenant_id = :tid",
        "DELETE FROM exec.parameter_reading WHERE tenant_id = :tid",
        "DELETE FROM kg.triple_store_staging WHERE tenant_id = :tid",
    ]:
        db.execute(text(stmt), {"tid": tid})
    db.commit()


def list_ac_tenant_codes(db: Session) -> list[str]:
    rows = db.execute(
        text(
            "SELECT tenant_code FROM core.tenant "
            "WHERE tenant_code LIKE :gr OR tenant_code LIKE :sam "
            "ORDER BY tenant_code"
        ),
        {"gr": f"{AC_TENANT_PREFIX}%", "sam": "SAM_CARBONS%"},
    ).fetchall()
    return [str(row[0]) for row in rows]


def reset_transactional_all_ac_tenants(db: Session) -> None:
    """Delete transactional data for every SAM_CARBONS* tenant (shared sequences)."""
    codes = list_ac_tenant_codes(db)
    if not codes:
        print(f"WARN: No tenants matching {AC_TENANT_PREFIX}%")
        return
    for code in codes:
        tenant = resolve_tenant(db, code, None)
        reset_transactional(db, tenant)
        print(f"OK: Reset transactional data for {code}")


def reset_all_for_tenant(db: Session, tenant) -> None:
    """Remove transactional data and tenant master rows (products, routing, resources)."""
    reset_transactional(db, tenant)
    tid = str(tenant.tenant_id)
    for stmt in [
        "DELETE FROM mst.operation_resource_requirement WHERE tenant_id = :tid",
        "DELETE FROM mst.routing_operation_parameter WHERE tenant_id = :tid",
        "DELETE FROM mst.routing_operation WHERE tenant_id = :tid",
        "DELETE FROM mst.routing WHERE tenant_id = :tid",
        "DELETE FROM mst.equipment WHERE tenant_id = :tid",
        "DELETE FROM mst.resource WHERE tenant_id = :tid",
        "DELETE FROM mst.product WHERE tenant_id = :tid",
        "DELETE FROM mst.supplier WHERE tenant_id = :tid",
        "DELETE FROM mst.customer WHERE tenant_id = :tid",
    ]:
        db.execute(text(stmt), {"tid": tid})
    db.commit()


def has_transactional_seed(db: Session, tenant) -> bool:
    repo = TenantRepository(db, tenant)
    return repo.query(CustomerOrder).count() > 0


def _ensure_demo_customer(db: Session, tenant) -> Customer:
    repo = TenantRepository(db, tenant)
    try:
        return repo.get_by_code(Customer, Customer.customer_code, MASTER_CUSTOMER_CODE)
    except NotFoundError:
        pass
    created = ac_adapter.create_ac_customer(
        db,
        tenant,
        CustomerCreate(customer_name="Demo Customer", status="ACTIVE"),
    )
    return repo.get_by_pk(Customer, Customer.customer_id, created.customer_id)


def _ensure_demo_supplier(db: Session, tenant) -> Supplier:
    repo = TenantRepository(db, tenant)
    rows = repo.query(Supplier).order_by(Supplier.supplier_code).all()
    if rows:
        return rows[0]
    created = ac_adapter.create_ac_supplier(
        db,
        tenant,
        SupplierCreate(supplier_name="Coastal Shell Traders", status="ACTIVE"),
    )
    return repo.get_by_pk(Supplier, Supplier.supplier_id, created.supplier_id)


def seed_story(db: Session, tenant) -> dict:
    repo = TenantRepository(db, tenant)
    customer = _ensure_demo_customer(db, tenant)
    supplier = _ensure_demo_supplier(db, tenant)
    raw_product = repo.get_by_code(Product, Product.product_code, RAW_PRODUCT_CODE)

    try:
        kiln = repo.get_by_code(Resource, Resource.resource_code, DEFAULT_KILN_RESOURCE_CODE)
        kiln_code = kiln.resource_code
    except NotFoundError:
        kiln_out = ac_adapter.create_kiln(
            db,
            tenant,
            AcKilnCreate(kiln_name="Activation Kiln 01", status="ACTIVE"),
        )
        kiln_code = kiln_out.resource_code

    inward = ac_adapter.create_raw_material_inward(
        db,
        tenant,
        AcRawMaterialInwardCreate(
            supplier_id=supplier.supplier_id,
            product_id=raw_product.product_id,
            quantity=Decimal("7500"),
            uom="KG",
            create_production_order=False,
        ),
    )

    order_code = inward.order.order_code

    ac_adapter.create_raw_material_qc(
        db,
        tenant,
        AcRawMaterialQcCreate(
            customer_order_id=inward.order.customer_order_id,
            moisture_pct=Decimal("10.5"),
            ash_pct=Decimal("2.1"),
            foreign_matter_pct=Decimal("0.3"),
            stones_kg=Decimal("42"),
            unburnt_kg=Decimal("28"),
            minus20_kg=Decimal("289"),
            operator_remarks="Seed — feedstock accepted for demo lots",
            qc_status="PASS",
        ),
    )

    release = ac_adapter.create_make_to_stock_production_order(
        db,
        tenant,
        AcMakeToStockCreate(
            inward_order_id=inward.order.customer_order_id,
            quantity=Decimal("7500"),
            uom="KG",
        ),
    )
    if not release.production_order or not release.production_lot:
        raise RuntimeError("Seed requires PO + planned lot from release to production")

    po_code = release.production_order.production_order_code
    po_id = release.production_order.production_order_id
    lot_act_code = release.production_lot.lot_code

    activation_lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_act_code)
    activation_lot.lot_quantity = Decimal("4000")
    db.flush()

    mes_core_feasibility.run_feasibility_check(db, tenant, lot_act_code)

    lot_activation = ac_adapter.create_kiln_feed_lot(
        db,
        tenant,
        AcKilnFeedLotCreate(
            production_lot_id=release.production_lot.production_lot_id,
            lot_quantity=Decimal("4000"),
            status="IN_PROGRESS",
            kiln_resource_code=kiln_code,
        ),
    )
    lot_act_code = lot_activation.lot_code

    return {
        "tenant_code": TENANT_CODE,
        "workspace_code": WORKSPACE_CODE,
        "customer": customer.customer_code,
        "raw_product": RAW_PRODUCT_CODE,
        "finished_product": FINISHED_PRODUCT_CODE,
        "kiln_resource": kiln_code,
        "order": order_code,
        "production_order": po_code,
        "lot_activation": lot_act_code,
        "ui_url": "http://127.0.0.1:5173/activated-carbon/dashboard",
        "api_context": (
            "GET http://127.0.0.1:8000/api/context "
            f"Headers: X-Tenant-Code={TENANT_CODE}, X-Workspace-Code={WORKSPACE_CODE}"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Activated Carbon demo data")
    parser.add_argument("--install-master", action="store_true", help="Apply master data SQL")
    parser.add_argument("--reset", action="store_true", help="Delete transactional data first")
    parser.add_argument(
        "--reset-all",
        action="store_true",
        help="Delete transactional + tenant master data (then use --install-master)",
    )
    parser.add_argument(
        "--reset-all-ac-tenants",
        action="store_true",
        help="Delete transactional data for all SAM_CARBONS* tenants (testbed reset)",
    )
    parser.add_argument(
        "--reset-sequences",
        action="store_true",
        help="Reset PostgreSQL business-code sequences (empty DB -> suffix 1)",
    )
    parser.add_argument("--force", action="store_true", help="Re-seed even if orders exist")
    parser.add_argument(
        "--masters-only",
        action="store_true",
        help="Install master data only — no inward orders, lots, or dashboard seed story",
    )
    parser.add_argument("--tenant", default=None, help="Tenant code (default: AC_TENANT_CODE)")
    parser.add_argument("--workspace", default=None, help="Workspace code")
    args = parser.parse_args()

    global TENANT_CODE, WORKSPACE_CODE
    if args.tenant:
        TENANT_CODE = args.tenant
    if args.workspace:
        WORKSPACE_CODE = args.workspace

    db = _session()
    try:
        tenant = _ctx(db)
    except NotFoundError as exc:
        print(f"ERROR: {exc}")
        print("Run migrations 003 + 004 first (tenant + workspace + template route)")
        return 1

    if args.reset_all_ac_tenants:
        reset_transactional_all_ac_tenants(db)
    elif args.reset_all:
        reset_all_for_tenant(db, tenant)
        print(f"OK: Reset all tenant data for {TENANT_CODE} (masters + transactions)")

    if args.reset and not args.reset_all and not args.reset_all_ac_tenants:
        reset_transactional(db, tenant)
        print(f"OK: Reset transactional data for {TENANT_CODE}")

    if args.install_master:
        install_master_sql()

    if args.reset_sequences:
        reset_ac_sequences_empty(db)
        print("OK: Reset AC business-code sequences to start at suffix 1")

    if has_transactional_seed(db, tenant) and not args.reset and not args.force and not args.reset_all:
        print("Skip: customer orders already exist (use --reset --force or --reset-all)")
        return 0

    if has_transactional_seed(db, tenant) and (args.force or args.reset_all):
        reset_transactional(db, tenant)

    if args.masters_only:
        normalize_ac_display_names(db, tenant)
        if args.reset_all_ac_tenants or args.reset_sequences:
            sync_ac_sequences(db, tenant.tenant_id)
            print(f"OK: Synced AC business code sequences for {TENANT_CODE}")
        elif args.reset_sequences:
            reset_ac_sequences_empty(db)
            print("OK: Reset AC business code sequences to start at suffix 1")
        print("OK: Master data ready — empty plant (no inward orders or lots)")
        print(f"  tenant_code: {TENANT_CODE}")
        print(f"  workspace_code: {WORKSPACE_CODE}")
        print("  Start production: Raw Material -> Inward -> Prep -> QC -> Release -> ...")
        return 0

    result = seed_story(db, tenant)
    normalize_ac_display_names(db, tenant)

    if args.reset_all_ac_tenants or args.reset_sequences:
        sync_ac_sequences(db, tenant.tenant_id)
        print(f"OK: Synced AC business code sequences for {TENANT_CODE}")
    else:
        reset_ac_sequences_to_seed(db, tenant.tenant_id)
        print("OK: Synced AC business code sequences from tenant data")
    print("OK: Activated Carbon validation data seeded")
    for key, val in result.items():
        print(f"  {key}: {val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
