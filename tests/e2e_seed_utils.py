"""Shared seed/cleanup helpers for API pytest and Playwright E2E tests."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import text

from app.db.database import SessionLocal
from app.models.customer import Customer
from app.models.feasibility import FeasibilityGate
from app.models.order import CustomerOrder, CustomerOrderLine
from app.models.part import Part
from app.models.production import ProductionLot, ProductionOrder
from app.models.routing import Routing, RoutingOperation
from app.models.schedule import ProductionSchedule
from app.models.work_order import WorkOrder


def new_suffix() -> str:
    return uuid.uuid4().hex[:8].upper()


def build_seed_codes(suffix: str | None = None) -> dict:
    suffix = suffix or new_suffix()
    return {
        "suffix": suffix,
        "customer_code": f"E2E-CUST-{suffix}",
        "part_code": f"E2E-PART-{suffix}",
        "order_code": f"E2E-ORD-{suffix}",
        "order_line_code": f"E2E-ORDL-{suffix}",
        "routing_code": f"E2E-ROUTE-{suffix}",
        "process_a": f"E2E-PA-{suffix}",
        "process_b": f"E2E-PB-{suffix}",
        "process_code_a": f"EPCA-{suffix[:6]}",
        "process_code_b": f"EPCB-{suffix[:6]}",
        "op_code_1": f"E2E-OP1-{suffix[:6]}",
        "op_code_2": f"E2E-OP2-{suffix[:6]}",
    }


def seed_workflow_context(codes: dict | None = None) -> dict:
    """Insert master + order line + routing (+ optional PO/lot). Returns context dict."""
    codes = codes or build_seed_codes()
    suffix = codes["suffix"]
    db = SessionLocal()

    customer = Customer(
        customer_code=codes["customer_code"],
        customer_name=f"E2E Customer {suffix}",
    )
    db.add(customer)
    db.flush()

    part = Part(part_code=codes["part_code"], part_name=f"E2E Part {suffix}")
    db.add(part)
    db.flush()

    order = CustomerOrder(order_code=codes["order_code"], customer_id=customer.id)
    db.add(order)
    db.flush()

    line = CustomerOrderLine(
        order_line_code=codes["order_line_code"],
        order_id=order.id,
        part_id=part.id,
        quantity=100,
    )
    db.add(line)
    db.flush()

    db.execute(
        text(
            """
            INSERT INTO mst.process_library
                (process_id, process_code, process_name, process_type, is_active)
            VALUES
                (:pid_a, :pcode_a, 'Moulding', 'Casting', true),
                (:pid_b, :pcode_b, 'Pouring', 'Casting', true)
            """
        ),
        {
            "pid_a": codes["process_a"],
            "pcode_a": codes["process_code_a"],
            "pid_b": codes["process_b"],
            "pcode_b": codes["process_code_b"],
        },
    )
    db.flush()

    routing = Routing(
        routing_code=codes["routing_code"],
        part_id=part.id,
        routing_version="1",
        process_type="Casting",
        is_active=True,
    )
    db.add(routing)
    db.flush()

    for seq, (name, proc, op_code) in enumerate(
        [
            ("Moulding", codes["process_a"], codes["op_code_1"]),
            ("Pouring", codes["process_b"], codes["op_code_2"]),
        ],
        start=1,
    ):
        db.add(
            RoutingOperation(
                operation_code=op_code,
                routing_id=routing.id,
                operation_sequence=seq,
                operation_name=name,
                process_id=proc,
                standard_cycle_time_minutes=Decimal("30"),
            )
        )

    db.commit()

    ctx = {
        **codes,
        "order_line_id": codes["order_line_code"],
        "order_line_pk": line.id,
        "part_id": codes["part_code"],
        "routing_id": codes["routing_code"],
        "customer_pk": customer.id,
        "order_pk": order.id,
        "part_pk": part.id,
        "routing_pk": routing.id,
        "lot_id": None,
        "production_order_id": None,
    }
    db.close()
    return ctx


def seed_production_order_with_lot(ctx: dict) -> dict:
    """Create PO + single lot for an existing seeded order line. Mutates and returns ctx."""
    from app.services import production_service
    from app.schemas.production import ProductionLotCreate, ProductionOrderWithLotsCreate

    db = SessionLocal()
    payload = ProductionOrderWithLotsCreate(
        order_line_id=ctx["order_line_id"],
        planned_quantity=Decimal("100"),
        status="Planned",
        lots=[ProductionLotCreate(lot_quantity=Decimal("100"), status="Created")],
    )
    po, lots = production_service.create_production_order_with_lots(db, payload)
    ctx = {
        **ctx,
        "production_order_id": po.production_order_id,
        "lot_id": lots[0].lot_id,
    }
    db.close()
    return ctx


def cleanup_seed_context(ctx: dict) -> None:
    """Remove all rows created by ``seed_workflow_context`` / PO helpers."""
    line_pk = ctx.get("order_line_pk")
    if not line_pk:
        return

    db = SessionLocal()
    lot_pks = [
        row[0]
        for row in db.query(ProductionLot.id)
        .join(ProductionOrder, ProductionLot.production_order_id == ProductionOrder.id)
        .filter(ProductionOrder.order_line_id == line_pk)
        .all()
    ]
    if lot_pks:
        db.query(WorkOrder).filter(WorkOrder.lot_id.in_(lot_pks)).delete(
            synchronize_session=False
        )
        db.query(ProductionSchedule).filter(
            ProductionSchedule.lot_id.in_(lot_pks)
        ).delete(synchronize_session=False)
        db.query(FeasibilityGate).filter(FeasibilityGate.lot_id.in_(lot_pks)).delete(
            synchronize_session=False
        )
    db.query(ProductionLot).filter(
        ProductionLot.production_order_id.in_(
            db.query(ProductionOrder.id).filter(ProductionOrder.order_line_id == line_pk)
        )
    ).delete(synchronize_session=False)
    db.query(ProductionOrder).filter(ProductionOrder.order_line_id == line_pk).delete(
        synchronize_session=False
    )
    routing_pk = ctx.get("routing_pk")
    if routing_pk:
        db.query(RoutingOperation).filter(RoutingOperation.routing_id == routing_pk).delete(
            synchronize_session=False
        )
        db.query(Routing).filter(Routing.id == routing_pk).delete()
    db.query(CustomerOrderLine).filter(CustomerOrderLine.id == line_pk).delete()
    db.query(CustomerOrder).filter(CustomerOrder.id == ctx.get("order_pk")).delete()
    db.query(Part).filter(Part.id == ctx.get("part_pk")).delete()
    db.query(Customer).filter(Customer.id == ctx.get("customer_pk")).delete()
    db.execute(
        text("DELETE FROM mst.process_library WHERE process_id IN (:a, :b)"),
        {"a": ctx.get("process_a"), "b": ctx.get("process_b")},
    )
    db.commit()
    db.close()
