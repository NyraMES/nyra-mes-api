"""Seed the NYRA_VIDEO_DEMO tenant with fictional workflow data for client videos.

Creates the demo story from the video script:
  - Apex Automotive / ORD-DEMO-1042 / BRK-PAD-450
  - LOT-DEMO-001 — feasibility BLOCKED (moulding machine down)
  - LOT-DEMO-002 — feasible, scheduled, executed, inspected, traceable

Usage (from repo root, venv active):
  python scripts/seed_video_demo.py --install-tenant   # once: create tenant + master data
  python scripts/seed_video_demo.py --reset            # wipe + re-seed transactional data
  python scripts/seed_video_demo.py                     # seed (skip if order already exists)

Requires MES_CORE_DB_PASSWORD in .env (or .env.demo via run_video_demo.ps1).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env.demo")
load_dotenv(ROOT / ".env")

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext, resolve_tenant
from app.db.mes_core_database import get_mes_core_engine
from app.models.mes_core import Customer, Equipment, Product, Resource
from app.schemas.mes_core.schemas import (
    CustomerOrderCreate,
    CustomerOrderLineCreate,
    ProductionLotCreate,
    ProductionOrderCreate,
    ScheduleCreate,
)
from app.schemas.oee import OEEDailySummaryCreate
from app.schemas.quality import InspectionResultCreate
from app.schemas.schedule import WorkOrderCompleteRequest, WorkOrderStartRequest
from app.services.mes_core import entities as mes_core_entities
from app.services.mes_core import execution_workflow as mes_core_execution
from app.services.mes_core import feasibility as mes_core_feasibility
from app.services.mes_core import oee_intelligence as mes_core_oee
from app.services.mes_core import quality_workflow as mes_core_quality
from app.services.mes_core import scheduling as mes_core_scheduling
from app.services.mes_core.base import TenantRepository

TENANT_CODE = "NYRA_VIDEO_DEMO"
TENANT_ID = "b2000000-0000-4000-8000-000000000002"

CUSTOMER_CODE = "CUST-APEX-001"
PRODUCT_CODE = "BRK-PAD-450"
ORDER_CODE = "ORD-DEMO-1042"
ORDER_LINE_CODE = "ORDL-DEMO-1042"
PO_CODE = "PO-DEMO-1042"
LOT_BLOCKED = "LOT-DEMO-001"
LOT_READY = "LOT-DEMO-002"

MOULD_RESOURCE = "RES-MOULD-L01"
MOULD_EQUIPMENT = "EQ-MOULD-L01"

SQL_FILE = ROOT / "scripts" / "db" / "nyra_video_demo_tenant.sql"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _session() -> Session:
    engine = get_mes_core_engine()
    if engine is None:
        raise RuntimeError("MES_CORE is not enabled — set MES_CORE_ENABLED=true in .env")
    return Session(bind=engine)


def install_tenant_sql() -> None:
    if not SQL_FILE.is_file():
        raise FileNotFoundError(f"Missing SQL file: {SQL_FILE}")
    raw = SQL_FILE.read_text(encoding="utf-8")
    # Strip comment-only lines; execute as one script (BEGIN/COMMIT in file).
    engine = get_mes_core_engine()
    if engine is None:
        raise RuntimeError("MES_CORE is not enabled")
    with engine.begin() as conn:
        conn.execute(text(raw))
    print(f"OK: Applied {SQL_FILE.name}")


def tenant_exists(db: Session) -> bool:
    row = db.execute(
        text("SELECT 1 FROM core.tenant WHERE tenant_code = :code"),
        {"code": TENANT_CODE},
    ).first()
    return row is not None


def reset_transactional_data(db: Session, tenant: TenantContext) -> None:
    """Remove workflow rows for NYRA_VIDEO_DEMO only; keep master data."""
    tid = str(tenant.tenant_id)
    statements = [
        "DELETE FROM qms.quality_result WHERE tenant_id = :tid",
        "DELETE FROM qms.quality_check WHERE tenant_id = :tid",
        "DELETE FROM exec.operation_execution WHERE tenant_id = :tid",
        "DELETE FROM trn.feasibility_check WHERE tenant_id = :tid",
        "DELETE FROM trn.production_lot WHERE tenant_id = :tid",
        "DELETE FROM trn.production_order WHERE tenant_id = :tid",
        "DELETE FROM trn.customer_order_line WHERE tenant_id = :tid",
        "DELETE FROM trn.customer_order WHERE tenant_id = :tid",
    ]
    for stmt in statements:
        db.execute(text(stmt), {"tid": tid})
    # Clear recorded OEE summaries stored in tenant metadata
    db.execute(
        text(
            "UPDATE core.tenant SET metadata = metadata - 'oee_daily_summaries' "
            "WHERE tenant_id = :tid"
        ),
        {"tid": tid},
    )
    db.commit()
    print("OK: Reset transactional data for NYRA_VIDEO_DEMO")


def _set_machine_status(
    db: Session, tenant: TenantContext, *, available: bool
) -> None:
    status = "ACTIVE" if available else "MAINTENANCE"
    repo = TenantRepository(db, tenant)
    for code, model, col in (
        (MOULD_RESOURCE, Resource, Resource.resource_code),
        (MOULD_EQUIPMENT, Equipment, Equipment.equipment_code),
    ):
        row = repo.get_by_code(model, col, code)
        row.status = status
    db.commit()


def order_already_seeded(db: Session, tenant: TenantContext) -> bool:
    from app.core.exceptions import NotFoundError
    from app.models.mes_core import CustomerOrder

    repo = TenantRepository(db, tenant)
    try:
        repo.get_by_code(CustomerOrder, CustomerOrder.order_code, ORDER_CODE)
        return True
    except NotFoundError:
        return False


def _ensure_labor_pool_capacity(db: Session, tenant: TenantContext) -> None:
    repo = TenantRepository(db, tenant)
    labor = repo.get_by_code(Resource, Resource.resource_code, "RES-OP-CAST-01")
    meta = dict(labor.metadata_ or {})
    meta.setdefault("operators", 2)
    meta.setdefault("capacity", 2)
    labor.metadata_ = meta
    db.commit()


def seed_workflow(db: Session, tenant: TenantContext) -> dict:
    _ensure_labor_pool_capacity(db, tenant)
    repo = TenantRepository(db, tenant)
    customer = repo.get_by_code(Customer, Customer.customer_code, CUSTOMER_CODE)
    product = repo.get_by_code(Product, Product.product_code, PRODUCT_CODE)

    order_resp = mes_core_entities.create_customer_order(
        db,
        tenant,
        CustomerOrderCreate(
            order_code=ORDER_CODE,
            customer_id=customer.customer_id,
            status="OPEN",
            line=CustomerOrderLineCreate(
                line_code=ORDER_LINE_CODE,
                product_id=product.product_id,
                quantity=Decimal("500"),
            ),
        ),
    )

    po = mes_core_entities.create_production_order(
        db,
        tenant,
        ProductionOrderCreate(
            production_order_code=PO_CODE,
            order_line_id=order_resp.line.order_line_id,
            planned_quantity=Decimal("500"),
            status="PLANNED",
        ),
    )

    lot_blocked = mes_core_entities.create_production_lot(
        db,
        tenant,
        ProductionLotCreate(
            lot_code=LOT_BLOCKED,
            production_order_id=po.production_order_id,
            lot_quantity=Decimal("250"),
            status="CREATED",
        ),
    )
    lot_ready = mes_core_entities.create_production_lot(
        db,
        tenant,
        ProductionLotCreate(
            lot_code=LOT_READY,
            production_order_id=po.production_order_id,
            lot_quantity=Decimal("250"),
            status="CREATED",
        ),
    )

    # LOT-DEMO-001: moulding machine unavailable → BLOCKED feasibility
    _set_machine_status(db, tenant, available=False)
    feas_blocked = mes_core_feasibility.run_feasibility_check(db, tenant, LOT_BLOCKED)

    # Restore machines before LOT-DEMO-002 path
    _set_machine_status(db, tenant, available=True)
    feas_ready = mes_core_feasibility.run_feasibility_check(db, tenant, LOT_READY)

    plan = mes_core_scheduling.get_schedule_plan(db, tenant, LOT_READY)
    work_orders: list[str] = []
    now = _utcnow()
    for index, op in enumerate(plan.operations):
        start = now + timedelta(hours=index * 2)
        end = start + timedelta(minutes=op.estimated_duration_minutes or 30)
        mes_core_scheduling.create_schedule(
            db,
            tenant,
            ScheduleCreate(
                lot_id=LOT_READY,
                operation_id=op.operation_id,
                planned_start_time=start,
                planned_end_time=end,
                assigned_machine_id=op.suggested_machine_id,
                assigned_work_center_id=op.suggested_work_center_id,
                schedule_status="Scheduled",
            ),
        )
        summary = mes_core_execution.lot_execution_summary(db, tenant, LOT_READY)
        wo_row = next(
            o for o in summary["operations"] if o["operation_id"] == op.operation_id
        )
        wo_id = wo_row["work_order_id"]
        mes_core_execution.start_execution(
            db,
            tenant,
            wo_id,
            WorkOrderStartRequest(operator_name="Demo Operator"),
        )
        mes_core_execution.complete_execution(
            db,
            tenant,
            wo_id,
            WorkOrderCompleteRequest(
                actual_output_quantity=Decimal("250"),
                operator_name="Demo Operator",
                machine_id=op.suggested_machine_id,
                downtime_minutes=Decimal("5") if index == 0 else Decimal("0"),
            ),
        )
        work_orders.append(wo_id)

    inspection = mes_core_quality.create_inspection_result(
        db,
        tenant,
        InspectionResultCreate(
            lot_id=LOT_READY,
            work_order_id=work_orders[-1] if work_orders else None,
            inspected_quantity=Decimal("250"),
            accepted_quantity=Decimal("250"),
            rejected_quantity=Decimal("0"),
            inspection_status="Passed",
            inspected_at=_utcnow(),
        ),
    )

    # OEE trend data for dashboard scene
    today = date.today()
    for days_ago, (oee_val, avail, perf, qual) in enumerate(
        [
            (72.5, 90.0, 85.0, 94.7),
            (74.0, 91.0, 86.0, 94.8),
            (76.5, 92.0, 87.0, 95.0),
            (78.0, 93.0, 88.0, 95.2),
            (79.5, 94.0, 89.0, 95.3),
        ],
        start=4,
    ):
        mes_core_oee.record_oee_daily_summary(
            db,
            tenant,
            OEEDailySummaryCreate(
                machine_id=MOULD_EQUIPMENT,
                oee_date=today - timedelta(days=days_ago),
                planned_production_minutes=Decimal("480"),
                downtime_minutes=Decimal("45"),
                ideal_cycle_time_minutes=Decimal("2.5"),
                total_quantity=Decimal("200"),
                good_quantity=Decimal("195"),
                availability_percent=Decimal(str(avail)),
                performance_percent=Decimal(str(perf)),
                quality_percent=Decimal(str(qual)),
                oee_percent=Decimal(str(oee_val)),
            ),
        )

    ask_blocked = mes_core_feasibility.get_feasibility_for_lot(db, tenant, LOT_BLOCKED)

    return {
        "tenant_code": TENANT_CODE,
        "customer": CUSTOMER_CODE,
        "product": PRODUCT_CODE,
        "order": ORDER_CODE,
        "production_order": PO_CODE,
        "lot_blocked": {
            "code": LOT_BLOCKED,
            "feasibility": feas_blocked.overall_status,
            "blocked_reason": ask_blocked.blocked_reason,
        },
        "lot_ready": {
            "code": LOT_READY,
            "feasibility": feas_ready.overall_status,
            "work_orders_completed": len(work_orders),
            "inspection": inspection.inspection_status,
        },
        "ask_nyra_hint": f"Why is {LOT_BLOCKED} blocked?",
        "demo_login_local": {
            "auth_enabled": False,
            "email": "demo-viewer@nyra-demo.local",
            "note": "No password when AUTH_ENABLED=false",
        },
        "demo_login_cognito": {
            "email": "demo-viewer@nyra-demo.local",
            "role": "MES_Planner",
            "provision": ".\\scripts\\provision_demo_cognito_user.ps1",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed NYRA_VIDEO_DEMO tenant")
    parser.add_argument(
        "--install-tenant",
        action="store_true",
        help="Apply scripts/db/nyra_video_demo_tenant.sql (idempotent)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete transactional demo data before seeding",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-seed even if ORD-DEMO-1042 already exists (implies --reset)",
    )
    args = parser.parse_args()

    if args.install_tenant:
        install_tenant_sql()

    db = _session()
    try:
        if not tenant_exists(db):
            print(
                "ERROR: Tenant NYRA_VIDEO_DEMO not found.\n"
                "  Run: python scripts/seed_video_demo.py --install-tenant"
            )
            return 1

        tenant = resolve_tenant(db, TENANT_CODE)

        if args.force:
            reset_transactional_data(db, tenant)
        elif args.reset:
            reset_transactional_data(db, tenant)

        if order_already_seeded(db, tenant) and not (args.reset or args.force):
            print(
                f"SKIP: {ORDER_CODE} already exists. "
                "Use --reset or --force to re-seed."
            )
            ctx = {"tenant_code": TENANT_CODE, "order": ORDER_CODE, "status": "existing"}
            print(json.dumps(ctx, indent=2))
            return 0

        ctx = seed_workflow(db, tenant)
        print("\nOK: Video demo data seeded.\n")
        print(json.dumps(ctx, indent=2))
        print("\n--- Demo access ---")
        print("  Tenant header: X-Tenant-Code: NYRA_VIDEO_DEMO")
        print("  API context:   GET http://127.0.0.1:8000/api/context")
        print("  Local login:   demo-viewer@nyra-demo.local (no password, AUTH_ENABLED=false)")
        print("  Cognito:       .\\scripts\\provision_demo_cognito_user.ps1")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
