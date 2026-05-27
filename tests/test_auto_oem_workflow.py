"""End-to-end Auto OEM workflow tests.

Covers the manufacturing path exercised by the UI:

  Customer order line → Production order + lot split → Routing master →
  Routing plan → Generate route (work orders) → Feasibility → Scheduling gate

Runs against the live Postgres DB (same as dev). Skipped when unreachable.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
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
from tests.conftest import requires_live_db

pytestmark = requires_live_db


@pytest.fixture()
def workflow_context():
    """Seed customer → part → order line → routing with two operations."""
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8].upper()
    part_code = f"TEST-PART-{suffix}"
    customer_code = f"TEST-CUST-{suffix}"
    order_code = f"TEST-ORD-{suffix}"
    order_line_code = f"TEST-ORDL-{suffix}"
    routing_code = f"TEST-ROUTE-{suffix}"
    process_a = f"TEST-PROC-A-{suffix}"
    process_b = f"TEST-PROC-B-{suffix}"

    customer = Customer(customer_code=customer_code, customer_name="Auto OEM Test")
    db.add(customer)
    db.flush()

    part = Part(part_code=part_code, part_name="Test Casting")
    db.add(part)
    db.flush()

    order = CustomerOrder(order_code=order_code, customer_id=customer.id)
    db.add(order)
    db.flush()

    line = CustomerOrderLine(
        order_line_code=order_line_code,
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
            "pid_a": process_a,
            "pcode_a": f"PRC-A-{suffix}",
            "pid_b": process_b,
            "pcode_b": f"PRC-B-{suffix}",
        },
    )
    db.flush()

    routing = Routing(
        routing_code=routing_code,
        part_id=part.id,
        routing_version="1",
        process_type="Casting",
        is_active=True,
    )
    db.add(routing)
    db.flush()

    op_codes = []
    for seq, (name, proc) in enumerate(
        [("Moulding", process_a), ("Pouring", process_b)], start=1
    ):
        op_code = f"TEST-OP-{suffix}-{seq}"
        op_codes.append(op_code)
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

    line_id = line.id
    part_id = part_code
    ctx = {
        "order_line_id": order_line_code,
        "order_line_pk": line_id,
        "part_id": part_id,
        "routing_id": routing_code,
        "operation_codes": op_codes,
        "process_ids": [process_a, process_b],
        "customer_id": customer.id,
        "order_id": order.id,
        "part_pk": part.id,
        "routing_pk": routing.id,
    }

    try:
        yield ctx
    finally:
        db = SessionLocal()
        lot_pks = [
            row[0]
            for row in db.query(ProductionLot.id)
            .join(ProductionOrder, ProductionLot.production_order_id == ProductionOrder.id)
            .filter(ProductionOrder.order_line_id == line_id)
            .all()
        ]
        if lot_pks:
            db.query(WorkOrder).filter(WorkOrder.lot_id.in_(lot_pks)).delete(
                synchronize_session=False
            )
            db.query(ProductionSchedule).filter(
                ProductionSchedule.lot_id.in_(lot_pks)
            ).delete(synchronize_session=False)
            db.query(FeasibilityGate).filter(
                FeasibilityGate.lot_id.in_(lot_pks)
            ).delete(synchronize_session=False)
        db.query(ProductionLot).filter(
            ProductionLot.production_order_id.in_(
                db.query(ProductionOrder.id).filter(
                    ProductionOrder.order_line_id == line_id
                )
            )
        ).delete(synchronize_session=False)
        db.query(ProductionOrder).filter(
            ProductionOrder.order_line_id == line_id
        ).delete(synchronize_session=False)
        db.query(RoutingOperation).filter(
            RoutingOperation.routing_id == ctx["routing_pk"]
        ).delete(synchronize_session=False)
        db.query(Routing).filter(Routing.id == ctx["routing_pk"]).delete()
        db.query(CustomerOrderLine).filter(CustomerOrderLine.id == line_id).delete()
        db.query(CustomerOrder).filter(CustomerOrder.id == ctx["order_id"]).delete()
        db.query(Part).filter(Part.id == ctx["part_pk"]).delete()
        db.query(Customer).filter(Customer.id == ctx["customer_id"]).delete()
        db.execute(
            text("DELETE FROM mst.process_library WHERE process_id IN (:a, :b)"),
            {"a": process_a, "b": process_b},
        )
        db.commit()
        db.close()


def _create_po_with_single_lot(client, order_line_id: int, qty: int = 100) -> dict:
    payload = {
        "order_line_id": order_line_id,
        "planned_quantity": qty,
        "status": "Planned",
        "lots": [{"lot_quantity": qty}],
    }
    response = client.post("/production-order-with-lots", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# TC-01 … TC-03 — Production order quantity gates
# ---------------------------------------------------------------------------

def test_tc01_po_quantity_must_match_order_line(client, workflow_context):
    """TC-01: PO planned qty must equal order line qty."""
    payload = {
        "order_line_id": workflow_context["order_line_id"],
        "planned_quantity": 90,
        "lots": [{"lot_quantity": 90}],
    }
    response = client.post("/production-order-with-lots", json=payload)
    assert response.status_code == 400
    body = response.json()
    assert "order line quantity" in body["detail"].lower()
    assert float(body["context"]["order_line_quantity"]) == 100
    assert float(body["context"]["planned_quantity"]) == 90


def test_tc02_lot_split_must_sum_to_planned(client, workflow_context):
    """TC-02: Lot quantities must sum to planned quantity."""
    payload = {
        "order_line_id": workflow_context["order_line_id"],
        "planned_quantity": 100,
        "lots": [{"lot_quantity": 60}, {"lot_quantity": 30}],
    }
    response = client.post("/production-order-with-lots", json=payload)
    assert response.status_code == 400
    body = response.json()
    assert "lot quantities" in body["detail"].lower()
    assert body["context"]["planned_quantity"] == "100"
    assert body["context"]["lots_total"] == "90"


def test_tc03_creates_po_and_balanced_lots(client, workflow_context):
    """TC-03: Valid PO + lot split is accepted."""
    body = _create_po_with_single_lot(client, workflow_context["order_line_id"])
    assert float(body["production_order"]["planned_quantity"]) == 100
    assert len(body["lots"]) == 1
    assert float(body["lots"][0]["lot_quantity"]) == 100


# ---------------------------------------------------------------------------
# TC-04 … TC-08 — Routing plan and generate route
# ---------------------------------------------------------------------------

def test_tc04_routing_plan_shows_pending_before_generate(client, workflow_context):
    """TC-04: Routing plan lists operations with pending work orders."""
    body = _create_po_with_single_lot(client, workflow_context["order_line_id"])
    lot_id = body["lots"][0]["lot_id"]

    response = client.get(f"/lot/{lot_id}/routing-plan")
    assert response.status_code == 200, response.text
    plan = response.json()

    assert plan["lot_id"] == lot_id
    assert plan["part_id"] == workflow_context["part_id"]
    assert plan["routing_id"] == workflow_context["routing_id"]
    assert plan["total_operations"] == 2
    assert plan["generated_work_orders"] == 0
    assert plan["pending_work_orders"] == 2
    assert plan["can_generate"] is True
    assert plan["routing_complete"] is False
    assert all(not op["work_order_generated"] for op in plan["operations"])


def test_tc05_generate_route_creates_work_orders_and_feasibility(
    client, workflow_context
):
    """TC-05: Generate route materialises WOs and runs feasibility."""
    body = _create_po_with_single_lot(client, workflow_context["order_line_id"])
    lot_id = body["lots"][0]["lot_id"]

    response = client.post(f"/lot/{lot_id}/generate-route")
    assert response.status_code == 200, response.text
    result = response.json()

    assert result["lot_id"] == lot_id
    assert result["operation_count"] == 2
    assert len(result["operations"]) == 2
    assert "feasibility" in result
    assert result["feasibility"]["lot_id"] == lot_id
    assert result["feasibility"]["overall_status"] in ("OK", "BLOCKED")


def test_tc06_routing_plan_complete_after_generate(client, workflow_context):
    """TC-06: After generate, routing plan shows all WOs generated."""
    body = _create_po_with_single_lot(client, workflow_context["order_line_id"])
    lot_id = body["lots"][0]["lot_id"]
    client.post(f"/lot/{lot_id}/generate-route")

    plan = client.get(f"/lot/{lot_id}/routing-plan").json()
    assert plan["generated_work_orders"] == 2
    assert plan["pending_work_orders"] == 0
    assert plan["can_generate"] is False
    assert plan["routing_complete"] is True
    assert all(op["work_order_generated"] for op in plan["operations"])


def test_tc07_generate_route_is_idempotent(client, workflow_context):
    """TC-07: Second generate-route call does not duplicate work orders."""
    body = _create_po_with_single_lot(client, workflow_context["order_line_id"])
    lot_id = body["lots"][0]["lot_id"]

    first = client.post(f"/lot/{lot_id}/generate-route").json()
    second = client.post(f"/lot/{lot_id}/generate-route").json()

    assert first["operation_count"] == 2
    assert second["operation_count"] == 0
    plan = client.get(f"/lot/{lot_id}/routing-plan").json()
    assert plan["generated_work_orders"] == 2


def test_tc08_feasibility_endpoint_persists_gate(client, workflow_context):
    """TC-08: GET /feasibility returns a persisted gate record."""
    body = _create_po_with_single_lot(client, workflow_context["order_line_id"])
    lot_id = body["lots"][0]["lot_id"]
    client.post(f"/lot/{lot_id}/generate-route")

    response = client.get(f"/feasibility/{lot_id}")
    assert response.status_code == 200, response.text
    feas = response.json()
    assert feas["lot_id"] == lot_id
    assert feas["overall_status"] in ("OK", "BLOCKED")
    assert feas["checked_at"] is not None
    assert len(feas["checks"]) >= 1


# ---------------------------------------------------------------------------
# TC-09 … TC-10 — Scheduling gate
# ---------------------------------------------------------------------------

def test_tc09_schedule_blocked_before_feasibility(client, workflow_context):
    """TC-09: Scheduling is blocked before feasibility has been checked."""
    body = _create_po_with_single_lot(client, workflow_context["order_line_id"])
    lot_id = body["lots"][0]["lot_id"]
    client.post(f"/lot/{lot_id}/generate-route")

    op_id = workflow_context["operation_codes"][0]
    payload = {
        "lot_id": lot_id,
        "operation_id": op_id,
    }
    # Remove feasibility gate to simulate pre-check state.
    db = SessionLocal()
    lot_pk = (
        db.query(ProductionLot.id)
        .filter(ProductionLot.lot_code == lot_id)
        .scalar()
    )
    db.query(FeasibilityGate).filter(FeasibilityGate.lot_id == lot_pk).delete()
    db.commit()
    db.close()

    response = client.post("/schedule", json=payload)
    assert response.status_code == 422
    assert "feasibility" in response.json()["detail"].lower()


def test_tc10_schedule_respects_feasibility_verdict(client, workflow_context):
    """TC-10: Schedule succeeds only when feasibility gate is OK."""
    body = _create_po_with_single_lot(client, workflow_context["order_line_id"])
    lot_id = body["lots"][0]["lot_id"]
    client.post(f"/lot/{lot_id}/generate-route")

    feas = client.get(f"/feasibility/{lot_id}").json()
    op_id = workflow_context["operation_codes"][0]
    payload = {"lot_id": lot_id, "operation_id": op_id}

    response = client.post("/schedule", json=payload)
    if feas["overall_status"] == "OK":
        assert response.status_code == 201, response.text
        assert response.json()["lot_id"] == lot_id
    else:
        assert response.status_code == 422
        assert "feasibility" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# TC-11 — Sync new routing operation
# ---------------------------------------------------------------------------

def test_tc11_sync_new_routing_operation(client, workflow_context):
    """TC-11: Adding a routing op enables sync of one new work order."""
    body = _create_po_with_single_lot(client, workflow_context["order_line_id"])
    lot_id = body["lots"][0]["lot_id"]
    client.post(f"/lot/{lot_id}/generate-route")

    suffix = uuid.uuid4().hex[:6].upper()
    new_op_code = f"T-OP3-{suffix}"
    db = SessionLocal()
    db.add(
        RoutingOperation(
            operation_code=new_op_code,
            routing_id=workflow_context["routing_pk"],
            operation_sequence=3,
            operation_name="Fettling",
            process_id=workflow_context["process_ids"][0],
            standard_cycle_time_minutes=Decimal("15"),
        )
    )
    db.commit()
    db.close()

    try:
        plan = client.get(f"/lot/{lot_id}/routing-plan").json()
        assert plan["total_operations"] == 3
        assert plan["pending_work_orders"] == 1
        assert plan["can_generate"] is True

        sync = client.post(f"/lot/{lot_id}/generate-route").json()
        assert sync["operation_count"] == 1

        plan_after = client.get(f"/lot/{lot_id}/routing-plan").json()
        assert plan_after["generated_work_orders"] == 3
        assert plan_after["routing_complete"] is True
    finally:
        db = SessionLocal()
        lot_pk = (
            db.query(ProductionLot.id)
            .filter(ProductionLot.lot_code == lot_id)
            .scalar()
        )
        op_pk = (
            db.query(RoutingOperation.id)
            .filter(RoutingOperation.operation_code == new_op_code)
            .scalar()
        )
        if lot_pk and op_pk:
            db.query(WorkOrder).filter(
                WorkOrder.lot_id == lot_pk,
                WorkOrder.routing_operation_id == op_pk,
            ).delete(synchronize_session=False)
        db.query(RoutingOperation).filter(
            RoutingOperation.operation_code == new_op_code
        ).delete(synchronize_session=False)
        db.commit()
        db.close()
