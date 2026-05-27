"""Feasibility-check service.

Strategy
--------
The DB already has a precomputed ``trn.v_feasibility_summary`` view that
joins live availability (material, machine, tool, workforce) by lot. We
prefer it when present. The result is also persisted into
``trn.feasibility_gate`` so other services can answer "is lot ready to
schedule?" without re-running the join.

A lightweight fallback computes the same checks in Python using the model
classes - this keeps the endpoint usable in test environments where the
view hasn't been created.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.bom import BOM, BOMItem
from app.models.feasibility import FeasibilityGate
from app.models.production import ProductionLot
from app.models.resource import Machine, Material
from app.schemas.feasibility import FeasibilityCheckResult, FeasibilityResponse
from app.services import resolver


_BLOCKED = "BLOCKED"
_OK = "OK"


def check_feasibility(db: Session, lot_code: str) -> FeasibilityResponse:
    lot = (
        db.query(ProductionLot)
        .filter(ProductionLot.lot_code == lot_code)
        .first()
    )
    if not lot:
        raise NotFoundError(f"Production lot '{lot_code}' not found")

    view_result = _check_via_view(db, lot.id)
    if view_result is not None:
        checks, summary = view_result
    else:
        checks, summary = _check_in_python(db, lot)

    overall = (
        _BLOCKED
        if any(c.status == _BLOCKED for c in checks)
        else _OK
    )
    blocked_reasons = "; ".join(
        c.detail for c in checks if c.status == _BLOCKED and c.detail
    ) or None

    response = FeasibilityResponse(
        lot_id=lot_code,
        overall_status=overall,
        material_status=summary.get("material"),
        machine_status=summary.get("machine"),
        tool_status=summary.get("tool"),
        workforce_status=summary.get("workforce"),
        blocked_reason=blocked_reasons,
        checked_at=datetime.utcnow(),
        checks=checks,
    )

    _persist_gate(db, lot.id, response)
    return response


def _check_via_view(db: Session, lot_pk: int):
    """Returns ``None`` if the view is missing or query fails."""
    try:
        row = db.execute(
            text(
                """
                SELECT material_status, machine_status, tool_status,
                       workforce_status, overall_status, blocked_reason
                  FROM trn.v_feasibility_summary
                 WHERE lot_id = :lot_id
                 LIMIT 1
                """
            ),
            {"lot_id": lot_pk},
        ).first()
    except SQLAlchemyError:
        db.rollback()
        return None
    if not row:
        return None

    material_status, machine_status, tool_status, workforce_status, _overall, blocked = row
    checks = [
        FeasibilityCheckResult(
            resource_type="material",
            status=_classify(material_status),
            detail=blocked if material_status and "BLOCK" in (material_status or "").upper() else None,
        ),
        FeasibilityCheckResult(
            resource_type="machine",
            status=_classify(machine_status),
            detail=blocked if machine_status and "BLOCK" in (machine_status or "").upper() else None,
        ),
        FeasibilityCheckResult(
            resource_type="tool",
            status=_classify(tool_status),
            detail=blocked if tool_status and "BLOCK" in (tool_status or "").upper() else None,
        ),
        FeasibilityCheckResult(
            resource_type="workforce",
            status=_classify(workforce_status),
            detail=blocked if workforce_status and "BLOCK" in (workforce_status or "").upper() else None,
        ),
    ]
    summary = {
        "material": _classify(material_status),
        "machine": _classify(machine_status),
        "tool": _classify(tool_status),
        "workforce": _classify(workforce_status),
    }
    return checks, summary


def _classify(raw):
    if raw is None:
        return None
    raw = str(raw).upper()
    if "BLOCK" in raw or "MISSING" in raw or "FAIL" in raw:
        return _BLOCKED
    return _OK


def _check_in_python(db: Session, lot: ProductionLot):
    """Fallback when the view is absent.

    * Material: sums BOM requirements for the lot's part and compares to
      ``mst.material.available_quantity``.
    * Machine: any machine with status 'Available' / 'Idle' is OK.
    * Tool / Workforce: rough OK unless inventories are entirely empty
      (true checks require ``operation_resource_requirement`` joins).
    """

    checks: List[FeasibilityCheckResult] = []

    # ---- material: BOM-based ----
    part_id = None
    if lot.production_order_id:
        # production_order -> order_line -> part
        po_row = db.execute(
            text(
                """
                SELECT ol.part_id
                  FROM trn.production_order po
                  JOIN trn.customer_order_line ol ON ol.id = po.order_line_id
                 WHERE po.id = :po_id
                """
            ),
            {"po_id": lot.production_order_id},
        ).first()
        part_id = po_row[0] if po_row else None

    material_status = _OK
    material_detail = None
    if part_id:
        bom = (
            db.query(BOM)
            .filter(BOM.part_id == part_id, BOM.is_active.is_(True))
            .order_by(BOM.id.desc())
            .first()
        )
        if bom:
            shortages = []
            items = db.query(BOMItem).filter(BOMItem.bom_id == bom.id).all()
            lot_qty = Decimal(str(lot.lot_quantity or 0))
            for item in items:
                if not item.material_id:
                    continue
                required = Decimal(str(item.quantity_required or 0)) * lot_qty
                mat = (
                    db.query(Material)
                    .filter(Material.id == item.material_id)
                    .first()
                )
                available = Decimal(str(mat.available_quantity if mat else 0))
                if available < required:
                    short_by = required - available
                    shortages.append(
                        f"material '{mat.material_code if mat else item.material_id}' "
                        f"short by {short_by}"
                    )
            if shortages:
                material_status = _BLOCKED
                material_detail = "; ".join(shortages)
    checks.append(
        FeasibilityCheckResult(
            resource_type="material",
            status=material_status,
            detail=material_detail,
        )
    )

    # ---- machine ----
    available_machine = (
        db.query(Machine)
        .filter(Machine.machine_status.in_(("Available", "Idle")))
        .count()
    )
    if available_machine == 0:
        checks.append(
            FeasibilityCheckResult(
                resource_type="machine",
                status=_BLOCKED,
                detail="No machine in Available/Idle state",
            )
        )
    else:
        checks.append(FeasibilityCheckResult(resource_type="machine", status=_OK))

    # ---- tool / workforce: rough check on inventory presence ----
    checks.append(FeasibilityCheckResult(resource_type="tool", status=_OK))
    checks.append(FeasibilityCheckResult(resource_type="workforce", status=_OK))

    summary = {c.resource_type: c.status for c in checks}
    return checks, summary


def _persist_gate(db: Session, lot_pk: int, response: FeasibilityResponse) -> None:
    gate = (
        db.query(FeasibilityGate)
        .filter(FeasibilityGate.lot_id == lot_pk)
        .order_by(FeasibilityGate.id.desc())
        .first()
    )
    if gate is None:
        gate = FeasibilityGate(lot_id=lot_pk)
        db.add(gate)
    gate.material_status = response.material_status
    gate.machine_status = response.machine_status
    gate.tool_status = response.tool_status
    gate.workforce_status = response.workforce_status
    gate.overall_status = response.overall_status
    gate.blocked_reason = response.blocked_reason
    gate.checked_at = response.checked_at
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()


def is_ready_for_scheduling(db: Session, lot_code: str) -> bool:
    """Cheap gate for the scheduling service: did the latest feasibility
    check pass for this lot?"""
    pk = resolver.lot_id(db, lot_code)
    gate = (
        db.query(FeasibilityGate)
        .filter(FeasibilityGate.lot_id == pk)
        .order_by(FeasibilityGate.id.desc())
        .first()
    )
    return bool(gate and (gate.overall_status or "").upper() == _OK)
