"""Process library master-data service."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.process import ProcessLibrary
from app.schemas.process import ProcessCreate, ProcessResponse, ProcessUpdate


def _process_to_out(row: ProcessLibrary) -> ProcessResponse:
    return ProcessResponse(
        process_id=row.process_id,
        process_code=row.process_code,
        process_name=row.process_name,
        process_type=row.process_type,
        description=row.description,
        is_active=row.is_active,
        created_at=row.created_at,
    )


def get_process_row(db: Session, process_id: str) -> ProcessLibrary:
    row = (
        db.query(ProcessLibrary)
        .filter(ProcessLibrary.process_id == process_id)
        .first()
    )
    if not row:
        raise NotFoundError(f"Process '{process_id}' not found")
    return row


def list_processes(
    db: Session,
    *,
    process_type: Optional[str] = None,
    active_only: bool = False,
) -> List[ProcessResponse]:
    q = db.query(ProcessLibrary)
    if process_type:
        q = q.filter(ProcessLibrary.process_type == process_type)
    if active_only:
        q = q.filter(ProcessLibrary.is_active.is_(True))
    rows = q.order_by(ProcessLibrary.process_name).all()
    return [_process_to_out(r) for r in rows]


def get_process(db: Session, process_id: str) -> ProcessResponse:
    return _process_to_out(get_process_row(db, process_id))


def create_process(db: Session, payload: ProcessCreate) -> ProcessResponse:
    code = payload.process_code.strip().upper()
    if not code:
        raise ValidationError("process_code is required")

    process_id = (payload.process_id or f"PROC_{code}").strip()
    if db.query(ProcessLibrary).filter(ProcessLibrary.process_id == process_id).first():
        raise ConflictError(f"Process '{process_id}' already exists")
    if db.query(ProcessLibrary).filter(ProcessLibrary.process_code == code).first():
        raise ConflictError(f"Process code '{code}' already exists")

    row = ProcessLibrary(
        process_id=process_id,
        process_code=code,
        process_name=payload.process_name.strip(),
        process_type=payload.process_type,
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Process could not be created: {exc.orig}") from exc
    db.refresh(row)
    return _process_to_out(row)


def update_process(
    db: Session, process_id: str, payload: ProcessUpdate
) -> ProcessResponse:
    row = get_process_row(db, process_id)
    if payload.process_name is not None:
        row.process_name = payload.process_name.strip()
    if payload.process_type is not None:
        row.process_type = payload.process_type
    if payload.description is not None:
        row.description = payload.description
    if payload.is_active is not None:
        row.is_active = payload.is_active
    db.commit()
    db.refresh(row)
    return _process_to_out(row)


def deactivate_process(db: Session, process_id: str) -> ProcessResponse:
    row = get_process_row(db, process_id)
    row.is_active = False
    db.commit()
    db.refresh(row)
    return _process_to_out(row)
