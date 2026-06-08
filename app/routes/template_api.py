"""Industry template catalog routes — metadata-driven module loading."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_mes_core_db
from app.core.openapi_tags import Tags
from app.schemas.mes_core.schemas import (
    CapabilityOut,
    IndustryTemplateMetadataOut,
    IndustryTemplateOut,
)
from app.services.mes_core import template_service

router = APIRouter(prefix="/api/templates", tags=[Tags.TEMPLATE])


@router.get("", response_model=List[IndustryTemplateOut], summary="List industry templates")
def list_industry_templates(db: Session = Depends(get_mes_core_db)):
    return template_service.list_templates(db)


@router.get(
    "/{template_code}",
    response_model=IndustryTemplateOut,
    summary="Get industry template by code",
)
def get_industry_template(template_code: str, db: Session = Depends(get_mes_core_db)):
    return template_service.get_template_by_code(db, template_code)


@router.get(
    "/{template_code}/capabilities",
    response_model=List[CapabilityOut],
    summary="List capabilities enabled for a template",
)
def get_template_capabilities(
    template_code: str, db: Session = Depends(get_mes_core_db)
):
    return template_service.list_template_capabilities(db, template_code)


@router.get(
    "/{template_code}/metadata",
    response_model=IndustryTemplateMetadataOut,
    summary="UI/API metadata for an industry template",
)
def get_template_metadata(template_code: str, db: Session = Depends(get_mes_core_db)):
    return template_service.get_template_metadata(db, template_code)
