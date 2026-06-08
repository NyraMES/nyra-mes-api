"""Transactional dispatch records (trn.dispatch) — tenant/workspace scoped."""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.tenant_context import TenantContext
from app.models.mes_core.transaction import Dispatch
from app.schemas.mes_core.schemas import TrnDispatchCreate, TrnDispatchOut, TrnDispatchUpdate
from app.services.mes_core.base import TenantRepository


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def list_dispatches(db: Session, tenant: TenantContext) -> List[TrnDispatchOut]:
    rows = (
        _repo(db, tenant)
        .query(Dispatch)
        .order_by(Dispatch.created_at.desc())
        .all()
    )
    return [TrnDispatchOut.model_validate(r) for r in rows]


def create_dispatch(
    db: Session, tenant: TenantContext, payload: TrnDispatchCreate
) -> TrnDispatchOut:
    repo = _repo(db, tenant)
    row = repo.add(
        Dispatch(
            customer_order_id=payload.customer_order_id,
            production_lot_id=payload.production_lot_id,
            finished_goods_lot_no=payload.finished_goods_lot_no,
            grade=payload.grade,
            bag_count=payload.bag_count,
            total_weight=payload.total_weight,
            vehicle_no=payload.vehicle_no,
            dispatch_date=payload.dispatch_date,
            invoice_ref=payload.invoice_ref,
            destination=payload.destination,
            status=payload.status or "PLANNED",
        )
    )
    return TrnDispatchOut.model_validate(repo.commit_refresh(row))


def update_dispatch(
    db: Session,
    tenant: TenantContext,
    dispatch_id: UUID,
    payload: TrnDispatchUpdate,
) -> TrnDispatchOut:
    repo = _repo(db, tenant)
    row = repo.get_by_pk(Dispatch, Dispatch.id, dispatch_id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if hasattr(row, key):
            setattr(row, key, value)
    return TrnDispatchOut.model_validate(repo.commit_refresh(row))


def get_dispatch(
    db: Session, tenant: TenantContext, dispatch_id: UUID
) -> TrnDispatchOut:
    row = _repo(db, tenant).get_by_pk(Dispatch, Dispatch.id, dispatch_id)
    return TrnDispatchOut.model_validate(row)
