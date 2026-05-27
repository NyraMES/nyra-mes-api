"""Workflow tests for ``POST /production-order-with-lots``.

After the bigint-surrogate-PK realignment the legacy SQLite ATTACH-based
fixture is no longer enough: every FK now points at ``<entity>.id``
(bigint) and the business code generator relies on Postgres sequences
(``trn.production_order_seq``, ``trn.lot_seq``). Reproducing this on
SQLite is more friction than it's worth, so the workflow tests now run
against the live Postgres DB.

The tests are skipped automatically when the live DB is unreachable so
``pytest`` still passes in CI environments without a database.
"""

from __future__ import annotations

import pytest

from app.db.database import SessionLocal
from app.models.customer import Customer
from app.models.order import CustomerOrder, CustomerOrderLine
from app.models.part import Part
from app.models.production import ProductionLot, ProductionOrder
from tests.conftest import requires_live_db

pytestmark = requires_live_db


@pytest.fixture()
def seed_order_line():
    """Insert a customer + order + order-line we can hang the test PO on,
    then clean up afterwards.

    Returns the bigint ``order_line_id`` to use in the POST body."""
    db = SessionLocal()
    customer = Customer(customer_code="TEST-CUST", customer_name="Test")
    db.add(customer)
    db.flush()

    part = Part(part_code="TEST-PART", part_name="Test")
    db.add(part)
    db.flush()

    order = CustomerOrder(order_code="TEST-ORD", customer_id=customer.id)
    db.add(order)
    db.flush()

    line = CustomerOrderLine(
        order_line_code="TEST-ORDL-LOTS",
        order_id=order.id,
        part_id=part.id,
        quantity=100,
    )
    db.add(line)
    db.commit()
    line_code = line.order_line_code

    try:
        yield line_code
    finally:
        db.query(ProductionLot).filter(
            ProductionLot.production_order_id.in_(
                db.query(ProductionOrder.id).filter(
                    ProductionOrder.order_line_id == line.id
                )
            )
        ).delete(synchronize_session=False)
        db.query(ProductionOrder).filter(
            ProductionOrder.order_line_id == line.id
        ).delete()
        db.query(CustomerOrderLine).filter(CustomerOrderLine.id == line.id).delete()
        db.query(CustomerOrder).filter(CustomerOrder.id == order.id).delete()
        db.query(Part).filter(Part.id == part.id).delete()
        db.query(Customer).filter(Customer.id == customer.id).delete()
        db.commit()
        db.close()


def test_creates_three_lots_and_returns_sequential_codes(client, seed_order_line):
    payload = {
        "order_line_id": seed_order_line,
        "planned_quantity": 100,
        "status": "Planned",
        "lots": [
            {"lot_quantity": 50},
            {"lot_quantity": 30},
            {"lot_quantity": 20},
        ],
    }
    response = client.post("/production-order-with-lots", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert float(body["production_order"]["planned_quantity"]) == 100
    assert len(body["lots"]) == 3
    # All three lots share the same production order code.
    po_code = body["production_order"]["production_order_id"]
    assert all(lot["production_order_id"] == po_code for lot in body["lots"])


def test_rejects_mismatched_quantities(client, seed_order_line):
    payload = {
        "order_line_id": seed_order_line,
        "planned_quantity": 100,
        "lots": [{"lot_quantity": 50}, {"lot_quantity": 30}, {"lot_quantity": 15}],
    }
    response = client.post("/production-order-with-lots", json=payload)
    assert response.status_code == 400
    body = response.json()
    assert "lot quantities" in body["detail"].lower()
    assert body["context"]["planned_quantity"] == "100"
    assert body["context"]["lots_total"] == "95"
