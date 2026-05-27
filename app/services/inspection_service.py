"""Inspection-result and parameter-result service."""

from __future__ import annotations

from datetime import datetime
from typing import List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.quality import InspectionResult, InspectionResultParameter
from app.schemas.quality import (
    InspectionParameterResultCreate,
    InspectionParameterResultOut,
    InspectionResultCreate,
    InspectionResultOut,
)
from app.services import resolver
from app.utils.ids import generate_business_id


def _result_to_out(db: Session, row: InspectionResult) -> InspectionResultOut:
    return InspectionResultOut(
        id=row.id,
        inspection_id=row.inspection_code,
        work_order_id=resolver.work_order_code(db, row.work_order_id) if row.work_order_id else None,
        lot_id=resolver.lot_code(db, row.lot_id) if row.lot_id else None,
        inspection_plan_id=(
            resolver.inspection_plan_code(db, row.inspection_plan_id)
            if row.inspection_plan_id
            else None
        ),
        inspected_quantity=row.inspected_quantity,
        accepted_quantity=row.accepted_quantity,
        rejected_quantity=row.rejected_quantity,
        inspection_status=row.inspection_status,
        inspected_at=row.inspected_at,
    )


def _param_to_out(db: Session, row: InspectionResultParameter) -> InspectionParameterResultOut:
    return InspectionParameterResultOut(
        id=row.id,
        inspection_id=resolver.inspection_code(db, row.inspection_result_id) if row.inspection_result_id else None,
        parameter_id=row.inspection_parameter_id,
        observed_value=row.observed_value,
        result_status=row.result_status,
    )


def list_inspection_results(db: Session) -> List[InspectionResultOut]:
    rows = db.query(InspectionResult).order_by(InspectionResult.id).all()
    return [_result_to_out(db, r) for r in rows]


def create_inspection_result(
    db: Session, payload: InspectionResultCreate
) -> InspectionResultOut:
    code = (payload.inspection_id or "").strip() or generate_business_id(
        db,
        prefix=settings.id_prefix_inspection_result,
        sequence="trn.inspection_seq",
        fallback_table="trn.inspection_result",
        fallback_column="inspection_code",
    )
    if (
        db.query(InspectionResult)
        .filter(InspectionResult.inspection_code == code)
        .first()
    ):
        raise ConflictError(f"Inspection result '{code}' already exists")

    row = InspectionResult(
        inspection_code=code,
        work_order_id=(
            resolver.work_order_id(db, payload.work_order_id)
            if payload.work_order_id
            else None
        ),
        lot_id=resolver.lot_id(db, payload.lot_id) if payload.lot_id else None,
        inspection_plan_id=(
            resolver.inspection_plan_id(db, payload.inspection_plan_id)
            if payload.inspection_plan_id
            else None
        ),
        inspected_quantity=payload.inspected_quantity,
        accepted_quantity=payload.accepted_quantity,
        rejected_quantity=payload.rejected_quantity,
        inspection_status=payload.inspection_status or "Pending",
        inspected_at=payload.inspected_at or datetime.utcnow(),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Inspection result '{code}' could not be committed: {exc.orig}")
    db.refresh(row)
    return _result_to_out(db, row)


def create_parameter_result(
    db: Session, payload: InspectionParameterResultCreate
) -> InspectionParameterResultOut:
    inspection_pk = resolver.inspection_id(db, payload.inspection_id)
    row = InspectionResultParameter(
        inspection_result_id=inspection_pk,
        inspection_parameter_id=payload.parameter_id,
        observed_value=payload.observed_value,
        result_status=payload.result_status,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"Inspection parameter result could not be committed: {exc.orig}"
        )
    db.refresh(row)
    return _param_to_out(db, row)


def list_inspection_results_for_lot(
    db: Session, lot_code: str
) -> List[InspectionResultOut]:
    lot_pk = resolver.lot_id(db, lot_code)
    rows = (
        db.query(InspectionResult)
        .filter(InspectionResult.lot_id == lot_pk)
        .order_by(InspectionResult.id)
        .all()
    )
    return [_result_to_out(db, r) for r in rows]
