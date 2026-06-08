"""Template catalog services — metadata-driven industry module loading."""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.mes_core.platform import Capability, IndustryCapability, IndustryTemplate
from app.schemas.mes_core.schemas import (
    CapabilityOut,
    IndustryTemplateMetadataOut,
    IndustryTemplateOut,
)


def list_templates(db: Session) -> List[IndustryTemplateOut]:
    rows = (
        db.query(IndustryTemplate)
        .filter(IndustryTemplate.is_active.is_(True))
        .order_by(IndustryTemplate.display_order, IndustryTemplate.template_code)
        .all()
    )
    return [IndustryTemplateOut.model_validate(r) for r in rows]


def get_template_by_code(db: Session, template_code: str) -> IndustryTemplateOut:
    row = (
        db.query(IndustryTemplate)
        .filter(IndustryTemplate.template_code == template_code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Industry template '{template_code}' not found")
    return IndustryTemplateOut.model_validate(row)


def get_template_metadata(db: Session, template_code: str) -> IndustryTemplateMetadataOut:
    row = (
        db.query(IndustryTemplate)
        .filter(IndustryTemplate.template_code == template_code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Industry template '{template_code}' not found")
    meta = row.metadata_ if isinstance(row.metadata_, dict) else {}
    return IndustryTemplateMetadataOut(
        template_code=row.template_code,
        template_name=row.template_name,
        module_code=row.module_code,
        landing_page=row.landing_page,
        ui_module_name=row.ui_module_name,
        api_module_name=row.api_module_name,
        icon_name=row.icon_name,
        dashboard_component=row.dashboard_component,
        display_order=row.display_order or 100,
        metadata=meta,
    )


def list_template_capabilities(db: Session, template_code: str) -> List[CapabilityOut]:
    template = (
        db.query(IndustryTemplate)
        .filter(IndustryTemplate.template_code == template_code)
        .first()
    )
    if not template:
        raise NotFoundError(f"Industry template '{template_code}' not found")

    rows = (
        db.query(Capability, IndustryCapability)
        .join(IndustryCapability, IndustryCapability.capability_id == Capability.capability_id)
        .filter(
            IndustryCapability.industry_template_id == template.industry_template_id,
            Capability.is_active.is_(True),
        )
        .order_by(IndustryCapability.display_order, Capability.capability_code)
        .all()
    )
    out: List[CapabilityOut] = []
    for cap, link in rows:
        out.append(
            CapabilityOut(
                capability_id=cap.capability_id,
                capability_code=cap.capability_code,
                capability_name=cap.capability_name,
                description=cap.description,
                category=cap.category,
                is_active=cap.is_active,
                display_order=link.display_order,
                is_required=link.is_required,
            )
        )
    return out
