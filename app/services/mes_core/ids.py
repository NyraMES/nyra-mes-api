"""Business code generation for nyra_mes_core — database sequences only.

Numeric suffixes come exclusively from PostgreSQL ``nextval('core.*_code_seq')``.
There is no MAX(column) or in-code counter fallback (unlike legacy ``app.utils.ids``).

Run ``scripts/db/nyra_mes_core_setup.sql`` or ``scripts/apply_mes_core_sequences.py``
before creating records without an explicit business code.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import InternalError

# entity key -> (fully-qualified sequence name, code prefix)
MES_CORE_CODE_SPECS: dict[str, tuple[str, str]] = {
    "customer": ("core.customer_code_seq", settings.id_prefix_customer),
    "supplier": ("core.supplier_code_seq", "SUP"),
    "product": ("core.product_code_seq", settings.id_prefix_part),
    "resource": ("core.resource_code_seq", "RES"),
    "equipment": ("core.equipment_code_seq", "EQ"),
    "routing": ("core.routing_code_seq", settings.id_prefix_routing),
    "routing_operation": (
        "core.routing_operation_code_seq",
        settings.id_prefix_operation,
    ),
    "customer_order": ("core.customer_order_code_seq", settings.id_prefix_order),
    "customer_order_line": (
        "core.customer_order_line_code_seq",
        settings.id_prefix_order_line,
    ),
    "production_order": (
        "core.production_order_code_seq",
        settings.id_prefix_production_order,
    ),
    "production_lot": ("core.lot_code_seq", settings.id_prefix_lot),
    "feasibility_check": ("core.feasibility_check_code_seq", "FEAS"),
    "operation_execution": ("core.execution_code_seq", settings.id_prefix_work_order),
    "schedule": ("core.schedule_code_seq", settings.id_prefix_schedule),
    "quality_check": ("core.quality_check_code_seq", "QC"),
    "inspection_result": (
        "core.quality_check_code_seq",
        settings.id_prefix_inspection_result,
    ),
    "ncr": ("core.ncr_code_seq", settings.id_prefix_ncr),
    "dispatch": ("core.dispatch_code_seq", settings.id_prefix_dispatch),
}


def _nextval(db: Session, sequence: str) -> int:
    """Return the next integer from a PostgreSQL sequence (sole ID source)."""
    try:
        value = db.execute(text(f"SELECT nextval('{sequence}')")).scalar()
    except SQLAlchemyError as exc:
        db.rollback()
        raise InternalError(
            f"Database sequence '{sequence}' is required for auto-generated codes. "
            "Apply scripts/db/nyra_mes_core_add_sequences.sql to nyra_mes_core."
        ) from exc
    if value is None:
        raise InternalError(f"nextval('{sequence}') returned no value")
    return int(value)


def generate_mes_core_business_id(db: Session, entity: str) -> str:
    """Format ``{prefix}{nextval:05d}`` e.g. CUST00001 from ``core.customer_code_seq``."""
    if entity not in MES_CORE_CODE_SPECS:
        raise ValueError(f"Unknown mes_core entity for ID generation: {entity}")

    sequence, prefix = MES_CORE_CODE_SPECS[entity]
    n = _nextval(db, sequence)
    return f"{prefix}{n:0{settings.id_pad_width}d}"


def resolve_business_code(
    db: Session,
    *,
    provided: Optional[str],
    entity: str,
) -> str:
    """Use client-supplied code, otherwise ``nextval`` from the entity sequence."""
    code = (provided or "").strip()
    if code:
        return code
    return generate_mes_core_business_id(db, entity)
