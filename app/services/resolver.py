"""Code <-> ID translation helpers shared by every service.

In the new schema, FK columns are BIGINT pointing at ``<entity>.id``. The
public API still speaks in business codes (``CUST00001``, ``ORD00001``,
...), so services need a quick way to translate between the two.

These helpers are intentionally thin (one SELECT per call) and cache
nothing: services should batch lookups when they need many.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.customer import Customer
from app.models.dispatch import Dispatch
from app.models.order import CustomerOrder, CustomerOrderLine
from app.models.part import Part
from app.models.production import ProductionLot, ProductionOrder
from app.models.quality import (
    Defect,
    InspectionPlan,
    InspectionResult,
    NCR,
)
from app.models.resource import (
    Machine,
    Material,
    Tool,
    WorkCenter,
    WorkforceRole,
)
from app.models.routing import Routing, RoutingOperation
from app.models.schedule import ProductionSchedule
from app.models.work_order import WorkOrder


# ---------------------------------------------------------------------------
# Master-data resolvers
# ---------------------------------------------------------------------------

def customer_id(db: Session, code: str) -> int:
    row = db.query(Customer.id).filter(Customer.customer_code == code).first()
    if not row:
        raise NotFoundError(f"Customer '{code}' not found")
    return int(row[0])


def customer_code(db: Session, id_: int) -> Optional[str]:
    row = db.query(Customer.customer_code).filter(Customer.id == id_).first()
    return row[0] if row else None


def part_id(db: Session, code: str) -> int:
    row = db.query(Part.id).filter(Part.part_code == code).first()
    if not row:
        raise NotFoundError(f"Part '{code}' not found")
    return int(row[0])


def part_code(db: Session, id_: int) -> Optional[str]:
    row = db.query(Part.part_code).filter(Part.id == id_).first()
    return row[0] if row else None


def machine_id(db: Session, code: str) -> int:
    row = db.query(Machine.id).filter(Machine.machine_code == code).first()
    if not row:
        raise NotFoundError(f"Machine '{code}' not found")
    return int(row[0])


def machine_code(db: Session, id_: int) -> Optional[str]:
    row = db.query(Machine.machine_code).filter(Machine.id == id_).first()
    return row[0] if row else None


def work_center_id(db: Session, code: str) -> int:
    row = (
        db.query(WorkCenter.id)
        .filter(WorkCenter.work_center_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Work center '{code}' not found")
    return int(row[0])


def work_center_code(db: Session, id_: int) -> Optional[str]:
    row = (
        db.query(WorkCenter.work_center_code)
        .filter(WorkCenter.id == id_)
        .first()
    )
    return row[0] if row else None


def tool_id(db: Session, code: str) -> int:
    row = db.query(Tool.id).filter(Tool.tool_code == code).first()
    if not row:
        raise NotFoundError(f"Tool '{code}' not found")
    return int(row[0])


def material_id(db: Session, code: str) -> int:
    row = db.query(Material.id).filter(Material.material_code == code).first()
    if not row:
        raise NotFoundError(f"Material '{code}' not found")
    return int(row[0])


def workforce_role_id(db: Session, code: str) -> int:
    row = (
        db.query(WorkforceRole.id)
        .filter(WorkforceRole.role_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Workforce role '{code}' not found")
    return int(row[0])


def routing_id(db: Session, code: str) -> int:
    row = db.query(Routing.id).filter(Routing.routing_code == code).first()
    if not row:
        raise NotFoundError(f"Routing '{code}' not found")
    return int(row[0])


def routing_code_for(db: Session, id_: int) -> Optional[str]:
    row = db.query(Routing.routing_code).filter(Routing.id == id_).first()
    return row[0] if row else None


def routing_operation_id(db: Session, code: str) -> int:
    row = (
        db.query(RoutingOperation.id)
        .filter(RoutingOperation.operation_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Routing operation '{code}' not found")
    return int(row[0])


def operation_code(db: Session, id_: int) -> Optional[str]:
    row = (
        db.query(RoutingOperation.operation_code)
        .filter(RoutingOperation.id == id_)
        .first()
    )
    return row[0] if row else None


def defect_id(db: Session, code: str) -> int:
    row = db.query(Defect.id).filter(Defect.defect_code == code).first()
    if not row:
        raise NotFoundError(f"Defect '{code}' not found")
    return int(row[0])


def defect_code(db: Session, id_: int) -> Optional[str]:
    row = db.query(Defect.defect_code).filter(Defect.id == id_).first()
    return row[0] if row else None


def inspection_plan_id(db: Session, code: str) -> int:
    row = (
        db.query(InspectionPlan.id)
        .filter(InspectionPlan.inspection_plan_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Inspection plan '{code}' not found")
    return int(row[0])


def inspection_plan_code(db: Session, id_: int) -> Optional[str]:
    row = (
        db.query(InspectionPlan.inspection_plan_code)
        .filter(InspectionPlan.id == id_)
        .first()
    )
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Transactional resolvers
# ---------------------------------------------------------------------------

def order_id(db: Session, code: str) -> int:
    row = db.query(CustomerOrder.id).filter(CustomerOrder.order_code == code).first()
    if not row:
        raise NotFoundError(f"Order '{code}' not found")
    return int(row[0])


def order_code(db: Session, id_: int) -> Optional[str]:
    row = db.query(CustomerOrder.order_code).filter(CustomerOrder.id == id_).first()
    return row[0] if row else None


def order_line_required(db: Session, line_id: int) -> CustomerOrderLine:
    row = (
        db.query(CustomerOrderLine)
        .filter(CustomerOrderLine.id == line_id)
        .first()
    )
    if not row:
        raise NotFoundError(f"Order line '{line_id}' not found")
    return row


def order_line_id(db: Session, code: str) -> int:
    """Resolve an ``ORDLxxxxx`` business code into its bigint PK."""
    row = (
        db.query(CustomerOrderLine.id)
        .filter(CustomerOrderLine.order_line_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Order line '{code}' not found")
    return int(row[0])


def order_line_code(db: Session, id_: int) -> Optional[str]:
    row = (
        db.query(CustomerOrderLine.order_line_code)
        .filter(CustomerOrderLine.id == id_)
        .first()
    )
    return row[0] if row else None


def production_order_id(db: Session, code: str) -> int:
    row = (
        db.query(ProductionOrder.id)
        .filter(ProductionOrder.production_order_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Production order '{code}' not found")
    return int(row[0])


def production_order_code(db: Session, id_: int) -> Optional[str]:
    row = (
        db.query(ProductionOrder.production_order_code)
        .filter(ProductionOrder.id == id_)
        .first()
    )
    return row[0] if row else None


def lot_id(db: Session, code: str) -> int:
    row = (
        db.query(ProductionLot.id)
        .filter(ProductionLot.lot_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Production lot '{code}' not found")
    return int(row[0])


def lot_code(db: Session, id_: int) -> Optional[str]:
    row = db.query(ProductionLot.lot_code).filter(ProductionLot.id == id_).first()
    return row[0] if row else None


def schedule_id(db: Session, code: str) -> int:
    row = (
        db.query(ProductionSchedule.id)
        .filter(ProductionSchedule.schedule_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Production schedule '{code}' not found")
    return int(row[0])


def schedule_code(db: Session, id_: int) -> Optional[str]:
    row = (
        db.query(ProductionSchedule.schedule_code)
        .filter(ProductionSchedule.id == id_)
        .first()
    )
    return row[0] if row else None


def work_order_id(db: Session, code: str) -> int:
    row = (
        db.query(WorkOrder.id)
        .filter(WorkOrder.work_order_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Work order '{code}' not found")
    return int(row[0])


def work_order_code(db: Session, id_: int) -> Optional[str]:
    row = (
        db.query(WorkOrder.work_order_code)
        .filter(WorkOrder.id == id_)
        .first()
    )
    return row[0] if row else None


def inspection_id(db: Session, code: str) -> int:
    row = (
        db.query(InspectionResult.id)
        .filter(InspectionResult.inspection_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Inspection result '{code}' not found")
    return int(row[0])


def inspection_code(db: Session, id_: int) -> Optional[str]:
    row = (
        db.query(InspectionResult.inspection_code)
        .filter(InspectionResult.id == id_)
        .first()
    )
    return row[0] if row else None


def dispatch_id(db: Session, code: str) -> int:
    row = (
        db.query(Dispatch.id).filter(Dispatch.dispatch_code == code).first()
    )
    if not row:
        raise NotFoundError(f"Dispatch '{code}' not found")
    return int(row[0])


def dispatch_code(db: Session, id_: int) -> Optional[str]:
    row = db.query(Dispatch.dispatch_code).filter(Dispatch.id == id_).first()
    return row[0] if row else None


def ncr_code(db: Session, id_: int) -> Optional[str]:
    row = db.query(NCR.ncr_code).filter(NCR.id == id_).first()
    return row[0] if row else None
