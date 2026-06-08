"""OEE DTOs."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, List, Optional, Union

from pydantic import BaseModel

from app.schemas.common import ORMModel


class OEEDailySummaryCreate(BaseModel):
    machine_id: str
    oee_date: date
    planned_production_minutes: Optional[Decimal] = None
    downtime_minutes: Optional[Decimal] = None
    ideal_cycle_time_minutes: Optional[Decimal] = None
    total_quantity: Optional[Decimal] = None
    good_quantity: Optional[Decimal] = None
    availability_percent: Optional[Decimal] = None
    performance_percent: Optional[Decimal] = None
    quality_percent: Optional[Decimal] = None
    oee_percent: Optional[Decimal] = None


class OEEDailySummaryOut(ORMModel):
    id: Optional[Union[int, str]] = None
    machine_id: Optional[str] = None
    oee_date: Optional[date] = None
    planned_production_minutes: Optional[Decimal] = None
    downtime_minutes: Optional[Decimal] = None
    ideal_cycle_time_minutes: Optional[Decimal] = None
    total_quantity: Optional[Decimal] = None
    good_quantity: Optional[Decimal] = None
    availability_percent: Optional[Decimal] = None
    performance_percent: Optional[Decimal] = None
    quality_percent: Optional[Decimal] = None
    oee_percent: Optional[Decimal] = None
    created_at: Optional[datetime] = None


class OEEPlantKpis(BaseModel):
    availability: float = 0.0
    performance: float = 0.0
    quality: float = 0.0
    oee: float = 0.0


class OEEDowntimeHotspot(BaseModel):
    machine_id: str
    minutes: float


class OEEIntelligenceResponse(BaseModel):
    """Payload for the workflow OEE Intelligence dashboard."""

    plant: OEEPlantKpis
    trend: List[dict]
    machine_ranking: List[OEEDailySummaryOut]
    downtime_hotspots: List[OEEDowntimeHotspot]
    data_source: str  # recorded | shop_floor | mixed | estimated | none
    summaries_count: int = 0


class OEEMachineSummary(BaseModel):
    """``/machine/oee/{machine_id}`` rollup payload."""

    machine_id: str
    period_days: int
    avg_oee_percent: Optional[Decimal] = None
    avg_availability_percent: Optional[Decimal] = None
    avg_performance_percent: Optional[Decimal] = None
    avg_quality_percent: Optional[Decimal] = None
    samples: int = 0
    daily: List[OEEDailySummaryOut] = []
    notes: Optional[List[Any]] = None
