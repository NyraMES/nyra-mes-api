"""OEE intelligence and recorded summaries for nyra_mes_core."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.core.tenant_context import TenantContext
from app.models.mes_core import Equipment, OperationExecution
from app.schemas.oee import (
    OEEDailySummaryCreate,
    OEEDailySummaryOut,
    OEEDowntimeHotspot,
    OEEIntelligenceResponse,
    OEEPlantKpis,
)
from app.services.mes_core.base import TenantRepository
from app.services.mes_core.execution_workflow import _is_schedule_row, _meta

_DEFAULT_SHIFT_MINUTES = 480.0
_OEE_SUMMARY_KEY = "oee_daily_summaries"


def _repo(db: Session, tenant: TenantContext) -> TenantRepository:
    return TenantRepository(db, tenant)


def _tenant_row(repo: TenantRepository):
    from app.models.mes_core import Tenant

    row = repo.query(Tenant).filter(Tenant.tenant_id == repo.tenant_id).first()
    if not row:
        raise NotFoundError("Tenant not found")
    return row


def _load_recorded_summaries(repo: TenantRepository) -> list[dict[str, Any]]:
    tenant = _tenant_row(repo)
    meta = tenant.metadata_ if isinstance(tenant.metadata_, dict) else {}
    rows = meta.get(_OEE_SUMMARY_KEY) or []
    return [row for row in rows if isinstance(row, dict)]


def _save_recorded_summaries(repo: TenantRepository, rows: list[dict[str, Any]]) -> None:
    from app.models.mes_core import Tenant

    tenant = _tenant_row(repo)
    meta = dict(tenant.metadata_ or {})
    meta[_OEE_SUMMARY_KEY] = rows
    tenant.metadata_ = meta
    repo.db.flush()


def _summary_to_out(row: dict[str, Any]) -> OEEDailySummaryOut:
    return OEEDailySummaryOut(
        id=row.get("id"),
        machine_id=row.get("machine_id"),
        oee_date=date.fromisoformat(str(row["oee_date"])) if row.get("oee_date") else None,
        planned_production_minutes=row.get("planned_production_minutes"),
        downtime_minutes=row.get("downtime_minutes"),
        ideal_cycle_time_minutes=row.get("ideal_cycle_time_minutes"),
        total_quantity=row.get("total_quantity"),
        good_quantity=row.get("good_quantity"),
        availability_percent=row.get("availability_percent"),
        performance_percent=row.get("performance_percent"),
        quality_percent=row.get("quality_percent"),
        oee_percent=row.get("oee_percent"),
        created_at=row.get("created_at"),
    )


def _validate_oee_payload(payload: OEEDailySummaryCreate) -> None:
    if not (payload.machine_id or "").strip():
        raise ValidationError("machine_id is required")
    if not payload.oee_date:
        raise ValidationError("oee_date is required")
    if payload.oee_date > date.today():
        raise ValidationError("oee_date cannot be in the future")

    planned = float(payload.planned_production_minutes or 0)
    downtime = float(payload.downtime_minutes or 0)
    ideal = float(payload.ideal_cycle_time_minutes or 0)
    total = float(payload.total_quantity or 0)
    good = float(payload.good_quantity or 0)

    if planned <= 0:
        raise ValidationError("planned_production_minutes must be greater than 0")
    if downtime < 0:
        raise ValidationError("downtime_minutes cannot be negative")
    if downtime > planned:
        raise ValidationError("downtime_minutes cannot exceed planned_production_minutes")
    if ideal <= 0:
        raise ValidationError("ideal_cycle_time_minutes must be greater than 0")
    if total < 0 or good < 0:
        raise ValidationError("total_quantity and good_quantity cannot be negative")
    if good > total:
        raise ValidationError("good_quantity cannot exceed total_quantity")


def _resolve_equipment(repo: TenantRepository, machine_code: str) -> Equipment:
    code = machine_code.strip()
    row = (
        repo.query(Equipment)
        .filter(Equipment.equipment_code == code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Equipment / machine '{code}' not found")
    return row


def compute_shop_floor_summaries(
    db: Session, tenant: TenantContext
) -> list[dict[str, Any]]:
    """Derive OEE summaries from completed shop-floor schedule executions."""
    repo = _repo(db, tenant)
    rows = [
        row
        for row in repo.query(OperationExecution).all()
        if _is_schedule_row(row)
        and (row.status or "").upper() == "COMPLETED"
        and row.completed_at is not None
    ]

    buckets: dict[tuple[str, str], dict[str, float]] = {}
    for row in rows:
        meta = _meta(row)
        machine = (
            meta.get("actual_machine_code")
            or meta.get("assigned_machine_code")
            or ""
        ).strip()
        if not machine:
            continue

        day = row.completed_at.date().isoformat()
        key = (machine, day)
        if key not in buckets:
            buckets[key] = {
                "planned": 0.0,
                "downtime": 0.0,
                "total_qty": 0.0,
                "good_qty": 0.0,
            }

        bucket = buckets[key]
        planned = float(meta.get("planned_minutes") or _DEFAULT_SHIFT_MINUTES)
        bucket["planned"] += planned
        bucket["downtime"] += float(meta.get("downtime_minutes") or 0)

        total_qty = float(meta.get("actual_output_quantity") or 0)
        scrap_qty = float(meta.get("scrap_quantity") or 0)
        bucket["total_qty"] += total_qty
        bucket["good_qty"] += max(0.0, total_qty - scrap_qty)

        if row.started_at and row.completed_at:
            run_minutes = max(
                (row.completed_at - row.started_at).total_seconds() / 60.0, 0.0
            )
            if run_minutes > planned:
                bucket["downtime"] += run_minutes - planned

    summaries: list[dict[str, Any]] = []
    for (machine, day), bucket in buckets.items():
        planned = bucket["planned"] or _DEFAULT_SHIFT_MINUTES
        operating = max(0.0, planned - bucket["downtime"])
        availability = (operating / planned * 100.0) if planned > 0 else 0.0
        performance = 100.0
        quality = (
            (bucket["good_qty"] / bucket["total_qty"] * 100.0)
            if bucket["total_qty"] > 0
            else 100.0
        )
        oee = availability * performance * quality / 10000.0
        summaries.append(
            {
                "machine_id": machine,
                "oee_date": day,
                "oee_percent": round(oee, 2),
                "availability_percent": round(availability, 2),
                "performance_percent": round(performance, 2),
                "quality_percent": round(quality, 2),
                "source": "shop_floor",
            }
        )
    return summaries


def _merge_summaries(
    recorded: list[dict[str, Any]], shop_floor: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in shop_floor:
        key = (str(row["machine_id"]), str(row["oee_date"]))
        merged[key] = dict(row)
    for row in recorded:
        key = (str(row["machine_id"]), str(row["oee_date"]))
        merged[key] = {**merged.get(key, {}), **row, "source": "recorded"}
    return list(merged.values())


def _build_trend(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[str, list[float]] = {}
    for summary in summaries:
        by_day.setdefault(str(summary["oee_date"]), []).append(
            float(summary.get("oee_percent") or 0)
        )
    return [
        {"day": day, "oee": round(sum(values) / len(values), 2)}
        for day, values in sorted(by_day.items())
    ]


def _plant_kpis(summaries: list[dict[str, Any]]) -> OEEPlantKpis:
    if not summaries:
        return OEEPlantKpis()
    return OEEPlantKpis(
        availability=round(
            sum(float(s.get("availability_percent") or 0) for s in summaries)
            / len(summaries),
            2,
        ),
        performance=round(
            sum(float(s.get("performance_percent") or 0) for s in summaries)
            / len(summaries),
            2,
        ),
        quality=round(
            sum(float(s.get("quality_percent") or 0) for s in summaries)
            / len(summaries),
            2,
        ),
        oee=round(
            sum(float(s.get("oee_percent") or 0) for s in summaries) / len(summaries),
            2,
        ),
    )


def _downtime_hotspots(
    db: Session, tenant: TenantContext, summaries: list[dict[str, Any]]
) -> list[OEEDowntimeHotspot]:
    repo = _repo(db, tenant)
    by_machine: dict[str, float] = {}
    for summary in summaries:
        machine = str(summary.get("machine_id") or "")
        if not machine:
            continue
        by_machine[machine] = by_machine.get(machine, 0.0) + float(
            summary.get("downtime_minutes") or 0
        )

    if not by_machine:
        rows = [
            row
            for row in repo.query(OperationExecution).all()
            if _is_schedule_row(row)
        ]
        for row in rows:
            meta = _meta(row)
            machine = (
                meta.get("actual_machine_code")
                or meta.get("assigned_machine_code")
                or ""
            ).strip()
            if machine:
                by_machine[machine] = by_machine.get(machine, 0.0) + float(
                    meta.get("downtime_minutes") or 0
                )

    return [
        OEEDowntimeHotspot(machine_id=machine, minutes=round(minutes, 2))
        for machine, minutes in sorted(
            by_machine.items(), key=lambda item: item[1], reverse=True
        )
        if minutes > 0
    ]


def get_oee_intelligence(
    db: Session, tenant: TenantContext
) -> OEEIntelligenceResponse:
    repo = _repo(db, tenant)
    recorded = _load_recorded_summaries(repo)
    shop_floor = compute_shop_floor_summaries(db, tenant)
    merged = _merge_summaries(recorded, shop_floor)

    recorded_count = len(recorded)
    shop_count = len(shop_floor)
    if recorded_count and shop_count:
        data_source = "mixed"
    elif recorded_count:
        data_source = "recorded"
    elif shop_count:
        data_source = "shop_floor"
    else:
        data_source = "none"

    machine_ranking = [
        _summary_to_out(row)
        for row in sorted(
            merged,
            key=lambda item: (
                str(item.get("oee_date") or ""),
                str(item.get("machine_id") or ""),
            ),
            reverse=True,
        )
    ]

    return OEEIntelligenceResponse(
        plant=_plant_kpis(merged),
        trend=_build_trend(merged),
        machine_ranking=machine_ranking,
        downtime_hotspots=_downtime_hotspots(db, tenant, recorded),
        data_source=data_source,
        summaries_count=len(merged),
    )


def record_oee_daily_summary(
    db: Session, tenant: TenantContext, payload: OEEDailySummaryCreate
) -> OEEDailySummaryOut:
    _validate_oee_payload(payload)
    repo = _repo(db, tenant)
    _resolve_equipment(repo, payload.machine_id)

    planned = Decimal(str(payload.planned_production_minutes or 0))
    downtime = Decimal(str(payload.downtime_minutes or 0))
    ideal = Decimal(str(payload.ideal_cycle_time_minutes or 0))
    total = Decimal(str(payload.total_quantity or 0))
    good = Decimal(str(payload.good_quantity or 0))
    operating = max(Decimal(0), planned - downtime)

    availability = (
        payload.availability_percent
        if payload.availability_percent is not None
        else (operating / planned * Decimal(100) if planned > 0 else Decimal(0))
    )
    performance = (
        payload.performance_percent
        if payload.performance_percent is not None
        else (
            (ideal * total / operating * Decimal(100))
            if operating > 0
            else Decimal(0)
        )
    )
    quality = (
        payload.quality_percent
        if payload.quality_percent is not None
        else (good / total * Decimal(100) if total > 0 else Decimal(0))
    )
    oee = (
        payload.oee_percent
        if payload.oee_percent is not None
        else availability * performance * quality / Decimal(10000)
    )

    for label, value in (
        ("availability_percent", availability),
        ("performance_percent", performance),
        ("quality_percent", quality),
        ("oee_percent", oee),
    ):
        if float(value) < 0 or float(value) > 100:
            raise ValidationError(f"{label} must be between 0 and 100")

    summary_id = f"{payload.machine_id.strip()}:{payload.oee_date.isoformat()}"
    row = {
        "id": summary_id,
        "machine_id": payload.machine_id.strip(),
        "oee_date": payload.oee_date.isoformat(),
        "planned_production_minutes": float(planned),
        "downtime_minutes": float(downtime),
        "ideal_cycle_time_minutes": float(ideal),
        "total_quantity": float(total),
        "good_quantity": float(good),
        "availability_percent": round(float(availability), 2),
        "performance_percent": round(float(performance), 2),
        "quality_percent": round(float(quality), 2),
        "oee_percent": round(float(oee), 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "recorded",
    }

    summaries = _load_recorded_summaries(repo)
    summaries = [s for s in summaries if s.get("id") != summary_id]
    summaries.append(row)
    _save_recorded_summaries(repo, summaries)
    tenant = _tenant_row(repo)
    repo.commit_refresh(tenant)

    return _summary_to_out(row)


def hub_oee_bundle(
    db: Session, tenant: TenantContext
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
    """Return trend, summaries, average OEE for the intelligence hub."""
    intel = get_oee_intelligence(db, tenant)
    summaries = [
        {
            "machine_id": row.machine_id,
            "oee_date": row.oee_date.isoformat() if row.oee_date else None,
            "oee_percent": float(row.oee_percent or 0),
            "availability_percent": float(row.availability_percent or 0),
            "performance_percent": float(row.performance_percent or 0),
            "quality_percent": float(row.quality_percent or 0),
        }
        for row in intel.machine_ranking
    ]
    return intel.trend, summaries, float(intel.plant.oee or 0)
