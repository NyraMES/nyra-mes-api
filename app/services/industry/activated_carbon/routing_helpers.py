"""Small helpers shared by AC routing workflow."""

from __future__ import annotations

from app.models.mes_core import OperationExecution

_SCHEDULE_META_FLAG = "is_production_schedule"


def _is_schedule_row(row: OperationExecution) -> bool:
    meta = row.metadata_ or {}
    return bool(
        isinstance(meta, dict)
        and (meta.get(_SCHEDULE_META_FLAG) or meta.get("schedule_code"))
    )
