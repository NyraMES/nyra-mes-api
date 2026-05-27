"""Part master-data service."""

from __future__ import annotations

from typing import List

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.part import Part
from app.schemas.part import PartCreate, PartOut
from app.utils.ids import generate_business_id


def _to_out(row: Part) -> PartOut:
    return PartOut(
        id=row.id,
        part_id=row.part_code,
        part_name=row.part_name,
        part_type=row.part_type,
        unit_of_measure=row.unit_of_measure,
        created_at=row.created_at,
    )


def list_parts(db: Session) -> List[PartOut]:
    rows = db.query(Part).order_by(Part.id).all()
    return [_to_out(r) for r in rows]


def get_part(db: Session, code: str) -> PartOut:
    row = db.query(Part).filter(Part.part_code == code).first()
    if not row:
        raise NotFoundError(f"Part '{code}' not found")
    return _to_out(row)


def create_part(db: Session, payload: PartCreate) -> PartOut:
    code = (payload.part_id or "").strip() or generate_business_id(
        db,
        prefix=settings.id_prefix_part,
        sequence="mst.part_seq",
        fallback_table="mst.part",
        fallback_column="part_code",
    )

    if db.query(Part).filter(Part.part_code == code).first():
        raise ConflictError(f"Part '{code}' already exists")

    row = Part(
        part_code=code,
        part_name=payload.part_name,
        part_type=payload.part_type,
        unit_of_measure=payload.unit_of_measure,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConflictError(f"Part '{code}' already exists")
    db.refresh(row)
    return _to_out(row)
