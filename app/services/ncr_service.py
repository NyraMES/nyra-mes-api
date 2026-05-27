"""Non-Conformance Report (NCR) service."""

from __future__ import annotations

from typing import List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.models.quality import NCR
from app.schemas.quality import NCRCreate, NCROut
from app.services import resolver
from app.utils.ids import generate_business_id


def _to_out(db: Session, row: NCR) -> NCROut:
    return NCROut(
        id=row.id,
        ncr_id=row.ncr_code,
        inspection_id=(
            resolver.inspection_code(db, row.inspection_result_id)
            if row.inspection_result_id
            else None
        ),
        defect_id=resolver.defect_code(db, row.defect_id) if row.defect_id else None,
        rejected_quantity=row.rejected_quantity,
        disposition=row.disposition,
        root_cause=row.root_cause,
        corrective_action=row.corrective_action,
        status=row.status,
        created_at=row.created_at,
    )


def list_ncrs(db: Session) -> List[NCROut]:
    rows = db.query(NCR).order_by(NCR.id).all()
    return [_to_out(db, r) for r in rows]


def create_ncr(db: Session, payload: NCRCreate) -> NCROut:
    code = (payload.ncr_id or "").strip() or generate_business_id(
        db,
        prefix=settings.id_prefix_ncr,
        sequence="trn.ncr_seq",
        fallback_table="trn.ncr",
        fallback_column="ncr_code",
    )
    if db.query(NCR).filter(NCR.ncr_code == code).first():
        raise ConflictError(f"NCR '{code}' already exists")

    row = NCR(
        ncr_code=code,
        inspection_result_id=(
            resolver.inspection_id(db, payload.inspection_id)
            if payload.inspection_id
            else None
        ),
        defect_id=resolver.defect_id(db, payload.defect_id) if payload.defect_id else None,
        rejected_quantity=payload.rejected_quantity,
        disposition=payload.disposition,
        root_cause=payload.root_cause,
        corrective_action=payload.corrective_action,
        status=payload.status or "Open",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"NCR '{code}' could not be committed: {exc.orig}")
    db.refresh(row)
    return _to_out(db, row)


def has_open_ncrs_for_lot(db: Session, lot_code: str) -> bool:
    """Cheap gate for dispatch_service."""
    pk = resolver.lot_id(db, lot_code)
    # ncr -> inspection_result.lot_id; we need to join.
    from app.models.quality import InspectionResult

    count = (
        db.query(NCR.id)
        .join(InspectionResult, NCR.inspection_result_id == InspectionResult.id)
        .filter(InspectionResult.lot_id == pk)
        .filter(NCR.status.in_(("Open", "Investigating")))
        .count()
    )
    return count > 0
