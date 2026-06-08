"""Rule-based Ask Nyra reasoning over nyra_mes_core workflow data."""

from __future__ import annotations

import re
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError, WorkflowError
from app.core.tenant_context import TenantContext
from app.models.mes_core import ProductionLot, QualityCheck
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.dispatch_workflow import _assert_lot_dispatch_eligible
from app.services.mes_core.execution_workflow import lot_execution_summary
from app.services.mes_core.feasibility import get_feasibility_for_lot
from app.services.mes_core.quality_workflow import (
    _NCR_TYPE,
    _to_ncr_out,
    list_inspection_results,
)
from app.services.mes_core.traceability_workflow import get_traceability

_LOT_CODE_RE = re.compile(r"\b(LOT[A-Z0-9_-]+)\b", re.I)


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _extract_lot_code(question: str, lot_id: Optional[str]) -> Optional[str]:
    explicit = (lot_id or "").strip()
    if explicit:
        return explicit.upper() if not explicit.upper().startswith("LOT") else explicit.upper()
    match = _LOT_CODE_RE.search(question or "")
    return match.group(1).upper() if match else None


def _ncrs_for_lot(db: Session, tenant: TenantContext, lot: ProductionLot):
    rows = (
        _repo(db, tenant)
        .query(QualityCheck)
        .filter(
            QualityCheck.check_type == _NCR_TYPE,
            QualityCheck.production_lot_id == lot.production_lot_id,
        )
        .order_by(QualityCheck.created_at.desc())
        .all()
    )
    return [_to_ncr_out(db, tenant, row) for row in rows]


def _lot_context(db: Session, tenant: TenantContext, lot_code: str) -> dict[str, Any]:
    repo = _repo(db, tenant)
    lot = repo.get_by_code(ProductionLot, ProductionLot.lot_code, lot_code)
    inspections = [r for r in list_inspection_results(db, tenant) if r.lot_id == lot_code]
    return {
        "lot": lot,
        "feasibility": get_feasibility_for_lot(db, tenant, lot_code),
        "execution": lot_execution_summary(db, tenant, lot_code, sync=False),
        "inspections": inspections,
        "ncrs": _ncrs_for_lot(db, tenant, lot),
        "trace": get_traceability(db, tenant, lot_code),
    }


def _why_blocked(ctx: dict[str, Any], lot_code: str) -> str:
    reasons: List[str] = []
    feas = ctx["feasibility"]
    if (feas.overall_status or "").upper() not in ("OK", "READY", "PASSED"):
        reasons.append(
            f"Feasibility gate is {feas.overall_status or 'BLOCKED'}"
            + (f": {feas.blocked_reason}" if feas.blocked_reason else "")
        )

    ex = ctx["execution"]
    total = ex.get("operations_total") or 0
    completed = ex.get("operations_completed") or 0
    if total == 0:
        reasons.append("No shop-floor work orders exist — schedule and run execution first.")
    elif completed < total:
        reasons.append(
            f"Execution incomplete: {completed} of {total} routing step(s) finished."
        )

    inspections = ctx["inspections"]
    if not any((i.inspection_status or "") == "Passed" for i in inspections):
        if inspections:
            reasons.append("Inspection recorded but none with Passed status.")
        else:
            reasons.append("No quality inspection recorded for this lot.")

    open_ncrs = [n for n in ctx["ncrs"] if (n.status or "").upper() in ("OPEN", "INVESTIGATING")]
    if open_ncrs:
        reasons.append(
            f"{len(open_ncrs)} open NCR(s): "
            + ", ".join(n.ncr_id for n in open_ncrs[:3])
        )

    if not reasons:
        return (
            f"Lot {lot_code} is not blocked by the standard workflow gates. "
            "Feasibility, execution, inspection, and NCR checks look clear for dispatch."
        )
    return f"Lot {lot_code} is blocked because:\n" + "\n".join(f"• {r}" for r in reasons)


def _traceability_answer(ctx: dict[str, Any], lot_code: str) -> str:
    t = ctx["trace"]
    chain = []
    if t.customer_id:
        chain.append(f"Customer {t.customer_id}")
    if t.order_id:
        chain.append(f"Order {t.order_id}")
    if t.production_order_id:
        chain.append(f"Production order {t.production_order_id}")
    if t.part_id:
        chain.append(f"Part {t.part_id}")
    chain.append(f"Lot {lot_code} (qty {t.lot_quantity}, status {t.status})")
    ex = ctx["execution"]
    if ex.get("operations_total"):
        chain.append(
            f"{ex.get('operations_completed', 0)}/{ex.get('operations_total')} operations complete"
        )
    if ctx["inspections"]:
        latest = ctx["inspections"][-1]
        chain.append(
            f"Inspection {latest.inspection_id}: {latest.inspection_status}"
        )
    if ctx["ncrs"]:
        chain.append(f"NCR(s): {', '.join(n.ncr_id for n in ctx['ncrs'])}")
    if t.dispatch_id:
        chain.append(f"Dispatch {t.dispatch_id}")
    return "Traceability chain:\n" + " → ".join(chain)


def _ncr_answer(ctx: dict[str, Any], lot_code: str) -> str:
    if not ctx["ncrs"]:
        return f"No NCRs are linked to lot {lot_code}."
    parts = []
    for n in ctx["ncrs"]:
        parts.append(
            f"NCR {n.ncr_id} ({n.status}): rejected qty {n.rejected_quantity}, "
            f"disposition {n.disposition or '—'}. "
            f"Root cause: {n.root_cause or 'not recorded'}."
        )
    return "\n".join(parts)


def _machine_delay_answer(ctx: dict[str, Any], lot_code: str) -> str:
    ops = ctx["execution"].get("operations") or []
    delays = [
        op
        for op in ops
        if op.get("downtime_minutes") not in (None, "", 0)
    ]
    if not delays:
        held = [op for op in ops if op.get("status") == "On Hold"]
        if held:
            hold = held[0]
            reason = hold.get("hold_reason") or "reason not recorded"
            return (
                f"No downtime logged on lot {lot_code}, but "
                f"{hold.get('operation_name')} is on hold: {reason}."
            )
        return f"No machine downtime or hold events recorded for lot {lot_code}."
    op = max(delays, key=lambda o: float(o.get("downtime_minutes") or 0))
    machine = op.get("actual_machine_id") or op.get("assigned_machine_id") or "unknown machine"
    return (
        f"Highest downtime on lot {lot_code}: {op.get('operation_name')} "
        f"on {machine} — {op.get('downtime_minutes')} minutes."
    )


def _dispatch_answer(db: Session, tenant: TenantContext, lot_code: str) -> str:
    try:
        _assert_lot_dispatch_eligible(db, tenant, lot_code)
        return f"Lot {lot_code} passes all dispatch gates and can be shipped."
    except WorkflowError as exc:
        return f"Lot {lot_code} cannot dispatch yet: {exc.message}"


def ask_nyra(
    db: Session,
    tenant: TenantContext,
    *,
    question: str,
    lot_id: Optional[str] = None,
) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        raise ValidationError("question is required")

    lot_code = _extract_lot_code(q, lot_id)
    q_lower = q.lower()

    if "oee" in q_lower:
        return {
            "question": q,
            "lot_id": lot_code,
            "answer": (
                "OEE trend data is not yet available in nyra_mes_core Ask Nyra. "
                "Use the OEE Dashboard stage or migrate OEE daily summaries to mes_core."
            ),
            "sources": ["oee"],
        }

    if not lot_code and any(
        k in q_lower
        for k in ("lot", "blocked", "traceability", "ncr", "dispatch", "machine", "delay")
    ):
        return {
            "question": q,
            "lot_id": None,
            "answer": (
                "Pick a lot in the workflow (or include a lot code like LOT00001 in your question) "
                "so I can reason over feasibility, execution, quality, and dispatch data."
            ),
            "sources": ["workflow_context"],
        }

    if lot_code:
        try:
            ctx = _lot_context(db, tenant, lot_code)
        except NotFoundError:
            return {
                "question": q,
                "lot_id": lot_code,
                "answer": f"Production lot '{lot_code}' was not found in nyra_mes_core.",
                "sources": [],
            }

        if "traceability" in q_lower or "trace" in q_lower or "genealogy" in q_lower:
            answer = _traceability_answer(ctx, lot_code)
        elif "ncr" in q_lower or "non-conformance" in q_lower or "non conformance" in q_lower:
            answer = _ncr_answer(ctx, lot_code)
        elif "machine" in q_lower or "delay" in q_lower or "downtime" in q_lower:
            answer = _machine_delay_answer(ctx, lot_code)
        elif "dispatch" in q_lower or "ship" in q_lower:
            answer = _dispatch_answer(db, tenant, lot_code)
        elif "block" in q_lower or "why" in q_lower:
            answer = _why_blocked(ctx, lot_code)
        else:
            answer = (
                _why_blocked(ctx, lot_code)
                + "\n\n"
                + _traceability_answer(ctx, lot_code)
            )

        return {
            "question": q,
            "lot_id": lot_code,
            "answer": answer,
            "sources": ["feasibility", "execution", "quality", "traceability"],
        }

    return {
        "question": q,
        "lot_id": None,
        "answer": (
            "I can answer questions about lots, blockers, traceability, NCRs, machines, and dispatch. "
            "Try: “Why is LOT00001 blocked?” or “Show traceability for this lot.”"
        ),
        "sources": ["help"],
    }
