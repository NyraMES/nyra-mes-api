"""Inspection results and NCRs for nyra_mes_core.

Both are stored in ``qms.quality_check`` distinguished by ``check_type``:
  - ``LOT_INSPECTION`` — lot inspection results (legacy inspection-result)
  - ``NCR`` — non-conformance reports linked to an inspection check_code
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core import ProductionLot, QualityCheck, QualityResult
from app.schemas.quality import InspectionResultCreate, InspectionResultOut, NCRCreate, NCROut
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.ids import resolve_business_code

_INSPECT_TYPE = "LOT_INSPECTION"
_NCR_TYPE = "NCR"


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _meta(row: QualityCheck) -> dict[str, Any]:
    data = row.metadata_ or {}
    return data if isinstance(data, dict) else {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slug_code(name: str, index: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip()).strip("_").upper()
    return slug or f"PARAM_{index + 1}"


def _lot_code(db: Session, tenant: TenantContext, lot_pk) -> Optional[str]:
    lot = (
        _repo(db, tenant)
        .query(ProductionLot)
        .filter(ProductionLot.production_lot_id == lot_pk)
        .first()
    )
    return lot.lot_code if lot else None


def _to_inspection_out(
    db: Session, tenant: TenantContext, row: QualityCheck
) -> InspectionResultOut:
    meta = _meta(row)
    lot_code = _lot_code(db, tenant, row.production_lot_id)
    inspection_status = meta.get("inspection_status")
    if not inspection_status:
        inspection_status = "Passed" if (row.status or "").upper() == "PASSED" else "Failed"
    return InspectionResultOut(
        inspection_id=row.check_code,
        work_order_id=meta.get("work_order_id"),
        lot_id=lot_code,
        inspection_plan_id=meta.get("inspection_plan_id"),
        inspected_quantity=_decimal_or_none(meta.get("inspected_quantity")),
        accepted_quantity=_decimal_or_none(meta.get("accepted_quantity")),
        rejected_quantity=_decimal_or_none(meta.get("rejected_quantity")),
        inspection_status=inspection_status,
        inspected_at=_parse_dt(meta.get("inspected_at")) or row.created_at,
    )


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


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


def list_inspection_results(
    db: Session, tenant: TenantContext
) -> List[InspectionResultOut]:
    rows = (
        _repo(db, tenant)
        .query(QualityCheck)
        .filter(QualityCheck.check_type == _INSPECT_TYPE)
        .order_by(QualityCheck.created_at.desc())
        .all()
    )
    return [_to_inspection_out(db, tenant, r) for r in rows]


def create_inspection_result(
    db: Session,
    tenant: TenantContext,
    payload: InspectionResultCreate,
    *,
    parameters: Optional[list[dict[str, str]]] = None,
) -> InspectionResultOut:
    if not payload.lot_id:
        raise ValidationError("lot_id is required")

    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, payload.lot_id)

    code = resolve_business_code(
        db,
        provided=payload.inspection_id,
        entity="inspection_result",
    )
    inspection_status = payload.inspection_status or "Pending"
    row_status = "PASSED" if inspection_status == "Passed" else "FAILED" if inspection_status == "Failed" else "OPEN"

    meta = {
        "work_order_id": (payload.work_order_id or "").strip() or None,
        "inspection_plan_id": (payload.inspection_plan_id or "").strip() or None,
        "inspected_quantity": (
            str(payload.inspected_quantity) if payload.inspected_quantity is not None else None
        ),
        "accepted_quantity": (
            str(payload.accepted_quantity) if payload.accepted_quantity is not None else None
        ),
        "rejected_quantity": (
            str(payload.rejected_quantity) if payload.rejected_quantity is not None else None
        ),
        "inspection_status": inspection_status,
        "inspected_at": (payload.inspected_at or _utcnow()).isoformat(),
    }

    row = repo.add(
        QualityCheck(
            check_code=code,
            production_lot_id=lot.production_lot_id,
            check_type=_INSPECT_TYPE,
            status=row_status,
            metadata_=meta,
        )
    )
    repo.db.flush()

    for index, param in enumerate(parameters or []):
        name = (param.get("name") or "").strip()
        if not name:
            continue
        char_code = _slug_code(name, index)
        spec = (param.get("spec") or "").strip()
        observed = (param.get("observed") or "").strip()
        repo.add(
            QualityResult(
                quality_check_id=row.quality_check_id,
                characteristic_code=char_code,
                characteristic_name=name,
                measured_text=observed or None,
                metadata_={"spec": spec} if spec else {},
                result_status="PASS",
            )
        )

    return _to_inspection_out(db, tenant, repo.commit_refresh(row))


def _to_ncr_out(db: Session, tenant: TenantContext, row: QualityCheck) -> NCROut:
    meta = _meta(row)
    return NCROut(
        ncr_id=row.check_code,
        inspection_id=meta.get("inspection_id") or meta.get("inspection_result_id"),
        defect_id=meta.get("defect_id"),
        rejected_quantity=_decimal_or_none(meta.get("rejected_quantity")),
        disposition=meta.get("disposition"),
        root_cause=meta.get("root_cause"),
        corrective_action=meta.get("corrective_action"),
        status=row.status,
        created_at=row.created_at,
    )


def list_ncrs(db: Session, tenant: TenantContext) -> List[NCROut]:
    rows = (
        _repo(db, tenant)
        .query(QualityCheck)
        .filter(QualityCheck.check_type == _NCR_TYPE)
        .order_by(QualityCheck.created_at.desc())
        .all()
    )
    return [_to_ncr_out(db, tenant, r) for r in rows]


def create_ncr(db: Session, tenant: TenantContext, payload: NCRCreate) -> NCROut:
    repo = _repo(db, tenant)
    inspection_code = (payload.inspection_id or "").strip()
    if not inspection_code:
        raise ValidationError("inspection_id is required")

    inspection = repo.get_by_code(QualityCheck, QualityCheck.check_code, inspection_code)
    if inspection.check_type != _INSPECT_TYPE:
        raise NotFoundError(f"Inspection '{inspection_code}' not found")

    code = resolve_business_code(db, provided=payload.ncr_id, entity="ncr")
    meta = {
        "inspection_id": inspection_code,
        "inspection_result_id": inspection_code,
        "defect_id": (payload.defect_id or "").strip() or None,
        "rejected_quantity": (
            str(payload.rejected_quantity) if payload.rejected_quantity is not None else None
        ),
        "disposition": payload.disposition,
        "root_cause": payload.root_cause,
        "corrective_action": payload.corrective_action,
    }
    row = repo.add(
        QualityCheck(
            check_code=code,
            production_lot_id=inspection.production_lot_id,
            check_type=_NCR_TYPE,
            status=payload.status or "Open",
            metadata_=meta,
        )
    )
    return _to_ncr_out(db, tenant, repo.commit_refresh(row))
