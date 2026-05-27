"""OEE service: daily summary CRUD + machine-level rollup."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.models.maintenance import MachineDowntime, MaintenanceEvent
from app.models.oee import OEEDailySummary
from app.models.schedule import ProductionSchedule
from app.models.work_order import WorkOrder, WorkOrderEvent
from app.schemas.maintenance import (
    MachineDowntimeCreate,
    MachineDowntimeOut,
    MaintenanceEventCreate,
    MaintenanceEventOut,
)
from app.schemas.oee import (
    OEEDailySummaryCreate,
    OEEDailySummaryOut,
    OEEDowntimeHotspot,
    OEEIntelligenceResponse,
    OEEPlantKpis,
    OEEMachineSummary,
)
from app.services import resolver


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------

def _oee_to_out(db: Session, row: OEEDailySummary) -> OEEDailySummaryOut:
    return OEEDailySummaryOut(
        id=row.id,
        machine_id=resolver.machine_code(db, row.machine_id) if row.machine_id else None,
        oee_date=row.oee_date,
        planned_production_minutes=row.planned_production_minutes,
        downtime_minutes=row.downtime_minutes,
        ideal_cycle_time_minutes=row.ideal_cycle_time_minutes,
        total_quantity=row.total_quantity,
        good_quantity=row.good_quantity,
        availability_percent=row.availability_percent,
        performance_percent=row.performance_percent,
        quality_percent=row.quality_percent,
        oee_percent=row.oee_percent,
        created_at=row.created_at,
    )


def _maint_to_out(db: Session, row: MaintenanceEvent) -> MaintenanceEventOut:
    return MaintenanceEventOut(
        id=row.id,
        machine_id=resolver.machine_code(db, row.machine_id) if row.machine_id else None,
        event_type=row.event_type,
        event_status=row.event_status,
        reported_at=row.reported_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
        reported_by=row.reported_by,
        issue_description=row.issue_description,
        action_taken=row.action_taken,
        downtime_minutes=row.downtime_minutes,
    )


def _downtime_to_out(db: Session, row: MachineDowntime) -> MachineDowntimeOut:
    return MachineDowntimeOut(
        id=row.id,
        machine_id=resolver.machine_code(db, row.machine_id) if row.machine_id else None,
        work_order_id=(
            resolver.work_order_code(db, row.work_order_id) if row.work_order_id else None
        ),
        downtime_reason=row.downtime_reason,
        downtime_start=row.downtime_start,
        downtime_end=row.downtime_end,
        downtime_minutes=row.downtime_minutes,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------

_DEFAULT_SHIFT_MINUTES = Decimal("480")
_DOWNTIME_RE = re.compile(r"Downtime:\s*([\d.]+)\s*min", re.I)


def _parse_downtime_minutes(remarks: Optional[str]) -> Decimal:
    if not remarks:
        return Decimal(0)
    m = _DOWNTIME_RE.search(remarks)
    if not m:
        return Decimal(0)
    try:
        return Decimal(m.group(1))
    except Exception:
        return Decimal(0)


def _schedule_planned_minutes(sched: Optional[ProductionSchedule]) -> Decimal:
    if sched and sched.planned_start_time and sched.planned_end_time:
        delta = sched.planned_end_time - sched.planned_start_time
        return Decimal(str(max(delta.total_seconds() / 60.0, 1.0)))
    return _DEFAULT_SHIFT_MINUTES


def _wo_run_minutes(wo: WorkOrder) -> Optional[Decimal]:
    if wo.started_at and wo.completed_at:
        delta = wo.completed_at - wo.started_at
        return Decimal(str(max(delta.total_seconds() / 60.0, 1.0)))
    return None


def compute_shop_floor_oee_rows(db: Session) -> List[OEEDailySummaryOut]:
    """Derive daily OEE per machine from execution + scheduling (no manual OEE save)."""
    buckets: Dict[Tuple[int, date], dict] = {}

    def _bucket(machine_pk: int, day: date) -> dict:
        key = (machine_pk, day)
        if key not in buckets:
            buckets[key] = {
                "planned": Decimal(0),
                "downtime": Decimal(0),
                "total_qty": Decimal(0),
                "good_qty": Decimal(0),
                "on_time": 0,
                "completed": 0,
            }
        return buckets[key]

    rows = (
        db.query(WorkOrder, ProductionSchedule)
        .outerjoin(ProductionSchedule, WorkOrder.schedule_id == ProductionSchedule.id)
        .filter(WorkOrder.completed_at.isnot(None))
        .filter(WorkOrder.work_order_status == "Completed")
        .all()
    )

    for wo, sched in rows:
        if not wo.completed_at:
            continue
        machine_pk = sched.assigned_machine_id if sched else None
        if not machine_pk:
            continue
        day = wo.completed_at.date()
        b = _bucket(machine_pk, day)
        planned = _schedule_planned_minutes(sched)
        b["planned"] += planned
        b["total_qty"] += Decimal(str(wo.actual_output_quantity or 0))
        scrap = Decimal(str(wo.scrap_quantity or 0))
        good = Decimal(str(wo.actual_output_quantity or 0)) - scrap
        if good < 0:
            good = Decimal(0)
        b["good_qty"] += good
        b["completed"] += 1
        if sched and sched.planned_end_time and wo.completed_at <= sched.planned_end_time:
            b["on_time"] += 1

        evt = (
            db.query(WorkOrderEvent)
            .filter(
                WorkOrderEvent.work_order_id == wo.id,
                WorkOrderEvent.event_type == "Completed",
            )
            .order_by(WorkOrderEvent.id.desc())
            .first()
        )
        if evt and evt.remarks:
            b["downtime"] += _parse_downtime_minutes(evt.remarks)

        run_min = _wo_run_minutes(wo)
        if run_min and run_min > planned:
            b["downtime"] += run_min - planned

    for dt in db.query(MachineDowntime).all():
        if not dt.machine_id:
            continue
        day = (
            dt.downtime_start.date()
            if dt.downtime_start
            else datetime.utcnow().date()
        )
        b = _bucket(dt.machine_id, day)
        b["downtime"] += Decimal(str(dt.downtime_minutes or 0))
        if b["planned"] == 0:
            b["planned"] = _DEFAULT_SHIFT_MINUTES

    out: List[OEEDailySummaryOut] = []
    for (machine_pk, day), b in buckets.items():
        code = resolver.machine_code(db, machine_pk)
        if not code:
            continue
        planned = b["planned"] or _DEFAULT_SHIFT_MINUTES
        downtime = min(b["downtime"], planned)
        operating = max(Decimal(0), planned - downtime)
        avail = (operating / planned * Decimal(100)) if planned else Decimal(0)
        perf = (
            Decimal(str(round(100 * b["on_time"] / b["completed"], 2)))
            if b["completed"]
            else Decimal("90")
        )
        total = b["total_qty"]
        good = b["good_qty"]
        if total > 0:
            qual = good / total * Decimal(100)
        else:
            qual = Decimal("95")
        oee = (avail * perf * qual) / Decimal(10000)
        out.append(
            OEEDailySummaryOut(
                machine_id=code,
                oee_date=day,
                planned_production_minutes=planned,
                downtime_minutes=downtime,
                availability_percent=avail,
                performance_percent=perf,
                quality_percent=qual,
                oee_percent=oee,
            )
        )
    return out


def _merge_trend(recorded: List[dict], computed: List[dict]) -> List[dict]:
    """Prefer manually recorded OEE for a day; fill other days from shop-floor."""
    by_day = {p["day"]: p["oee"] for p in computed}
    for p in recorded:
        by_day[p["day"]] = p["oee"]
    return [{"day": d, "oee": by_day[d]} for d in sorted(by_day.keys())]


def _plant_kpis_from_summaries(rows: List[OEEDailySummaryOut]) -> OEEPlantKpis:
    if not rows:
        return OEEPlantKpis()
    n = len(rows)
    tot = {"avail": Decimal(0), "perf": Decimal(0), "qual": Decimal(0), "oee": Decimal(0)}
    for r in rows:
        tot["avail"] += Decimal(str(r.availability_percent or 0))
        tot["perf"] += Decimal(str(r.performance_percent or 0))
        tot["qual"] += Decimal(str(r.quality_percent or 0))
        tot["oee"] += Decimal(str(r.oee_percent or 0))
    return OEEPlantKpis(
        availability=float(tot["avail"] / n),
        performance=float(tot["perf"] / n),
        quality=float(tot["qual"] / n),
        oee=float(tot["oee"] / n),
    )


def build_trend_by_day(rows: List[OEEDailySummaryOut]) -> List[dict]:
    """Average OEE per calendar day (plant-wide trend line)."""
    by_day: Dict[str, List[float]] = {}
    for r in rows:
        if not r.oee_date:
            continue
        day = str(r.oee_date)
        by_day.setdefault(day, []).append(float(r.oee_percent or 0))
    return [
        {"day": day, "oee": round(sum(vals) / len(vals), 2)}
        for day, vals in sorted(by_day.items())
    ]


def _latest_per_machine(rows: List[OEEDailySummaryOut]) -> List[OEEDailySummaryOut]:
    latest: Dict[str, OEEDailySummaryOut] = {}
    for r in rows:
        mid = r.machine_id
        if not mid:
            continue
        prev = latest.get(mid)
        if not prev or (r.oee_date or date.min) > (prev.oee_date or date.min):
            latest[mid] = r
    return sorted(
        latest.values(),
        key=lambda x: float(x.oee_percent or 0),
        reverse=True,
    )


def _estimate_summaries_from_downtime(db: Session) -> List[OEEDailySummaryOut]:
    """When no OEE rows exist, estimate availability from logged downtime."""
    rows = db.query(MachineDowntime).all()
    if not rows:
        return []
    today = datetime.utcnow().date()
    by_machine: Dict[int, Decimal] = {}
    for row in rows:
        if not row.machine_id:
            continue
        by_machine[row.machine_id] = by_machine.get(row.machine_id, Decimal(0)) + Decimal(
            str(row.downtime_minutes or 0)
        )
    estimated: List[OEEDailySummaryOut] = []
    for machine_pk, dt_min in by_machine.items():
        code = resolver.machine_code(db, machine_pk)
        if not code:
            continue
        planned = _DEFAULT_SHIFT_MINUTES
        operating = max(Decimal(0), planned - dt_min)
        avail = (operating / planned * Decimal(100)) if planned else Decimal(0)
        perf = Decimal("90")
        qual = Decimal("95")
        oee = (avail * perf * qual) / Decimal(10000)
        estimated.append(
            OEEDailySummaryOut(
                machine_id=code,
                oee_date=today,
                planned_production_minutes=planned,
                downtime_minutes=dt_min,
                availability_percent=avail,
                performance_percent=perf,
                quality_percent=qual,
                oee_percent=oee,
            )
        )
    return estimated


def get_oee_intelligence(db: Session) -> OEEIntelligenceResponse:
    """Single payload for the OEE Intelligence workflow screen."""
    summaries = list_oee_summaries(db)
    shop_floor = compute_shop_floor_oee_rows(db)
    recorded_trend = build_trend_by_day(summaries)
    shop_trend = build_trend_by_day(shop_floor)
    trend = _merge_trend(recorded_trend, shop_trend)

    if summaries and shop_floor:
        data_source = "mixed"
        seen = {(r.machine_id, str(r.oee_date)) for r in summaries}
        active_rows = list(summaries) + [
            r
            for r in shop_floor
            if (r.machine_id, str(r.oee_date)) not in seen
        ]
    elif summaries:
        data_source = "recorded"
        active_rows = summaries
    elif shop_floor:
        data_source = "shop_floor"
        active_rows = shop_floor
    else:
        estimated = _estimate_summaries_from_downtime(db)
        active_rows = estimated
        data_source = "estimated" if estimated else "none"
        if not trend and estimated:
            trend = build_trend_by_day(estimated)

    downtime_rows = db.query(MachineDowntime).all()
    dt_map: Dict[str, float] = {}
    for row in downtime_rows:
        code = resolver.machine_code(db, row.machine_id) if row.machine_id else "Unassigned"
        dt_map[code] = dt_map.get(code, 0.0) + float(row.downtime_minutes or 0)
    hotspots = [
        OEEDowntimeHotspot(machine_id=k, minutes=v)
        for k, v in sorted(dt_map.items(), key=lambda x: x[1], reverse=True)[:8]
    ]

    return OEEIntelligenceResponse(
        plant=_plant_kpis_from_summaries(active_rows),
        trend=trend,
        machine_ranking=_latest_per_machine(active_rows),
        downtime_hotspots=hotspots,
        data_source=data_source,
        summaries_count=len(summaries),
    )


def list_oee_summaries(db: Session) -> List[OEEDailySummaryOut]:
    rows = (
        db.query(OEEDailySummary)
        .order_by(OEEDailySummary.oee_date.desc(), OEEDailySummary.id)
        .all()
    )
    return [_oee_to_out(db, r) for r in rows]


def create_oee_summary(db: Session, payload: OEEDailySummaryCreate) -> OEEDailySummaryOut:
    machine_pk = resolver.machine_id(db, payload.machine_id)
    row = OEEDailySummary(
        machine_id=machine_pk,
        oee_date=payload.oee_date,
        planned_production_minutes=payload.planned_production_minutes,
        downtime_minutes=payload.downtime_minutes,
        ideal_cycle_time_minutes=payload.ideal_cycle_time_minutes,
        total_quantity=payload.total_quantity,
        good_quantity=payload.good_quantity,
        availability_percent=payload.availability_percent,
        performance_percent=payload.performance_percent,
        quality_percent=payload.quality_percent,
        oee_percent=payload.oee_percent,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"OEE summary could not be committed: {exc.orig}")
    db.refresh(row)
    return _oee_to_out(db, row)


def machine_oee_summary(
    db: Session, machine_code: str, days: int = 30
) -> OEEMachineSummary:
    pk = resolver.machine_id(db, machine_code)
    cutoff = (datetime.utcnow().date() - timedelta(days=days))

    rows = (
        db.query(OEEDailySummary)
        .filter(OEEDailySummary.machine_id == pk)
        .filter(OEEDailySummary.oee_date >= cutoff)
        .order_by(OEEDailySummary.oee_date.desc())
        .all()
    )
    daily = [_oee_to_out(db, r) for r in rows]

    def _avg(attr: str):
        values = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        if not values:
            return None
        total = sum((Decimal(str(v)) for v in values), Decimal(0))
        return total / Decimal(len(values))

    return OEEMachineSummary(
        machine_id=machine_code,
        period_days=days,
        avg_oee_percent=_avg("oee_percent"),
        avg_availability_percent=_avg("availability_percent"),
        avg_performance_percent=_avg("performance_percent"),
        avg_quality_percent=_avg("quality_percent"),
        samples=len(rows),
        daily=daily,
    )


# ---------------------------------------------------------------------------
# Maintenance / downtime (used by /maintenance and /machine-downtime routes)
# ---------------------------------------------------------------------------

def list_maintenance(db: Session) -> List[MaintenanceEventOut]:
    rows = db.query(MaintenanceEvent).order_by(MaintenanceEvent.id).all()
    return [_maint_to_out(db, r) for r in rows]


def create_maintenance(db: Session, payload: MaintenanceEventCreate) -> MaintenanceEventOut:
    machine_pk = resolver.machine_id(db, payload.machine_id)
    row = MaintenanceEvent(
        machine_id=machine_pk,
        event_type=payload.event_type,
        event_status=payload.event_status or "Reported",
        reported_at=payload.reported_at or datetime.utcnow(),
        started_at=payload.started_at,
        completed_at=payload.completed_at,
        reported_by=payload.reported_by,
        issue_description=payload.issue_description,
        action_taken=payload.action_taken,
        downtime_minutes=payload.downtime_minutes,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Maintenance event could not be committed: {exc.orig}")
    db.refresh(row)
    return _maint_to_out(db, row)


def list_downtime(db: Session) -> List[MachineDowntimeOut]:
    rows = db.query(MachineDowntime).order_by(MachineDowntime.id).all()
    return [_downtime_to_out(db, r) for r in rows]


def create_downtime(db: Session, payload: MachineDowntimeCreate) -> MachineDowntimeOut:
    machine_pk = resolver.machine_id(db, payload.machine_id)
    work_order_pk = (
        resolver.work_order_id(db, payload.work_order_id)
        if payload.work_order_id
        else None
    )
    minutes = payload.downtime_minutes
    if minutes is None and payload.downtime_start and payload.downtime_end:
        delta = (payload.downtime_end - payload.downtime_start).total_seconds() / 60
        minutes = Decimal(str(round(delta, 2)))
    row = MachineDowntime(
        machine_id=machine_pk,
        work_order_id=work_order_pk,
        downtime_reason=payload.downtime_reason,
        downtime_start=payload.downtime_start,
        downtime_end=payload.downtime_end,
        downtime_minutes=minutes,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Machine downtime could not be committed: {exc.orig}")
    db.refresh(row)
    return _downtime_to_out(db, row)


_ = date  # keep date import in scope for type checkers
