"""Dispatch workflow for nyra_mes_core.

Dispatch records are stored in ``qms.quality_check`` with ``check_type = DISPATCH``.
Line details live in ``metadata`` (legacy ``/dispatch`` contract preserved).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError, WorkflowError
from app.core.tenant_context import TenantContext
from app.models.mes_core import ProductionLot, QualityCheck
from app.schemas.dispatch import DispatchCreate, DispatchOut
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.execution_workflow import lot_execution_summary
from app.services.mes_core.ids import resolve_business_code
from app.services.mes_core.quality_workflow import list_inspection_results

_DISPATCH_TYPE = "DISPATCH"
_NCR_TYPE = "NCR"


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _meta(row: QualityCheck) -> dict[str, Any]:
    data = row.metadata_ or {}
    return data if isinstance(data, dict) else {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _lot_code(db: Session, tenant: TenantContext, lot_pk) -> Optional[str]:
    lot = (
        _repo(db, tenant)
        .query(ProductionLot)
        .filter(ProductionLot.production_lot_id == lot_pk)
        .first()
    )
    return lot.lot_code if lot else None


def dispatch_quantity_kg(meta: dict[str, Any]) -> Decimal:
    from decimal import Decimal

    total = Decimal("0")
    for line in meta.get("lines") or []:
        if isinstance(line, dict):
            total += Decimal(str(line.get("dispatch_quantity") or 0))
    if total <= 0:
        total = Decimal(str(meta.get("last_dispatch_kg") or meta.get("quantity_kg") or 0))
    return total


def _to_dispatch_out(db: Session, tenant: TenantContext, row: QualityCheck) -> DispatchOut:
    meta = _meta(row)
    return DispatchOut(
        dispatch_id=row.check_code,
        customer_id=meta.get("customer_id"),
        order_id=meta.get("order_id"),
        work_order_code=meta.get("work_order_code"),
        quantity_kg=dispatch_quantity_kg(meta),
        dispatch_date=_parse_dt(meta.get("dispatch_date")) or row.created_at,
        vehicle_number=meta.get("vehicle_number"),
        transporter_name=meta.get("transporter_name"),
        dispatch_status=row.status or meta.get("dispatch_status"),
        remarks=meta.get("remarks"),
        created_at=row.created_at,
    )


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _has_open_ncrs_for_lot(db: Session, tenant: TenantContext, lot_code: str) -> bool:
    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
    open_statuses = {"OPEN", "INVESTIGATING"}
    rows = (
        repo.query(QualityCheck)
        .filter(
            QualityCheck.check_type == _NCR_TYPE,
            QualityCheck.production_lot_id == lot.production_lot_id,
        )
        .all()
    )
    return any((r.status or "").upper() in open_statuses for r in rows)


def _assert_lot_dispatch_eligible(
    db: Session, tenant: TenantContext, lot_code: str
) -> ProductionLot:
    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)

    summary = lot_execution_summary(db, tenant, lot_code, sync=False)
    total = summary.get("operations_total") or 0
    completed = summary.get("operations_completed") or 0
    if total == 0:
        raise WorkflowError(
            f"Lot '{lot_code}' has no completed operations; run execution first"
        )
    if completed != total:
        raise WorkflowError(
            f"Lot '{lot_code}' has {total - completed} incomplete operation(s); cannot dispatch"
        )

    inspections = [
        r
        for r in list_inspection_results(db, tenant)
        if r.lot_id == lot_code and (r.inspection_status or "") == "Passed"
    ]
    if not inspections:
        raise WorkflowError(
            f"Lot '{lot_code}' has no passed inspection result; cannot dispatch"
        )

    if _has_open_ncrs_for_lot(db, tenant, lot_code):
        raise WorkflowError(
            f"Lot '{lot_code}' has open NCRs; resolve them before dispatch"
        )

    return lot


def list_dispatches(db: Session, tenant: TenantContext) -> List[DispatchOut]:
    rows = (
        _repo(db, tenant)
        .query(QualityCheck)
        .filter(QualityCheck.check_type == _DISPATCH_TYPE)
        .order_by(QualityCheck.created_at.desc())
        .all()
    )
    return [_to_dispatch_out(db, tenant, r) for r in rows]


def create_dispatch(
    db: Session, tenant: TenantContext, payload: DispatchCreate
) -> DispatchOut:
    if not payload.lines:
        raise ValidationError("At least one dispatch line is required")

    repo = _repo(db, tenant)
    primary_lot: Optional[ProductionLot] = None
    line_payloads = []
    for line in payload.lines:
        lot = _assert_lot_dispatch_eligible(db, tenant, line.lot_id)
        if primary_lot is None:
            primary_lot = lot
        line_payloads.append(
            {
                "lot_id": line.lot_id,
                "part_id": line.part_id,
                "dispatch_quantity": str(line.dispatch_quantity),
                "accepted_quantity": (
                    str(line.accepted_quantity)
                    if line.accepted_quantity is not None
                    else str(line.dispatch_quantity)
                ),
                "rejected_quantity": str(line.rejected_quantity or 0),
            }
        )
        lot.status = "DISPATCHED"

    if primary_lot is None:
        raise ValidationError("Dispatch line lot could not be resolved")

    code = resolve_business_code(
        db,
        provided=payload.dispatch_id,
        entity="dispatch",
    )
    meta = {
        "customer_id": payload.customer_id,
        "order_id": payload.order_id,
        "vehicle_number": payload.vehicle_number,
        "transporter_name": payload.transporter_name,
        "dispatch_status": payload.dispatch_status or "Ready",
        "dispatch_date": (payload.dispatch_date or _utcnow()).isoformat(),
        "remarks": payload.remarks,
        "lines": line_payloads,
    }
    row = repo.add(
        QualityCheck(
            check_code=code,
            production_lot_id=primary_lot.production_lot_id,
            check_type=_DISPATCH_TYPE,
            status=payload.dispatch_status or "Ready",
            metadata_=meta,
        )
    )
    return _to_dispatch_out(db, tenant, repo.commit_refresh(row))
