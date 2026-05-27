"""Customer master-data service.

Business contract:

* ``customer_id`` over the wire == ``customer_code`` in the DB
  (e.g. ``"CUST00001"``).
* The DB also has a surrogate ``id`` (bigint) which is exposed alongside.
* Auto-generates the next code from ``mst.customer_seq`` when the client
  doesn't supply one.
"""

from __future__ import annotations

from typing import List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerOut
from app.utils.ids import generate_business_id


def _to_out(row: Customer) -> CustomerOut:
    return CustomerOut(
        id=row.id,
        customer_id=row.customer_code,
        customer_name=row.customer_name,
        customer_type=row.customer_type,
        created_at=row.created_at,
    )


def list_customers(db: Session) -> List[CustomerOut]:
    rows = db.query(Customer).order_by(Customer.id).all()
    return [_to_out(r) for r in rows]


def get_customer(db: Session, code: str) -> CustomerOut:
    row = db.query(Customer).filter(Customer.customer_code == code).first()
    if not row:
        raise NotFoundError(f"Customer '{code}' not found")
    return _to_out(row)


def create_customer(db: Session, payload: CustomerCreate) -> CustomerOut:
    code = (payload.customer_id or "").strip() or generate_business_id(
        db,
        prefix=settings.id_prefix_customer,
        sequence="mst.customer_seq",
        fallback_table="mst.customer",
        fallback_column="customer_code",
    )

    if db.query(Customer).filter(Customer.customer_code == code).first():
        raise ConflictError(f"Customer '{code}' already exists")

    row = Customer(
        customer_code=code,
        customer_name=payload.customer_name,
        customer_type=payload.customer_type,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError(f"Customer '{code}' already exists")
    db.refresh(row)
    return _to_out(row)
