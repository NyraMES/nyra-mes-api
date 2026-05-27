"""Dynamic data capture routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.core.openapi_tags import Tags
from app.schemas.common import MessageResponse
from app.schemas.data_capture import (
    DataCaptureFieldCreate,
    DataCaptureFieldResponse,
    DataCaptureFieldUpdate,
    DataCaptureSubmit,
    DataCaptureSubmitResponse,
    DataCaptureTemplateCreate,
    DataCaptureTemplateLegacyCreate,
    DataCaptureTemplateResponse,
    DataCaptureTemplateUpdate,
    WorkOrderDataCaptureFormResponse,
)
from app.services import data_capture_service

router = APIRouter(tags=[Tags.DATA_CAPTURE])


@router.get(
    "/processes/{process_id}/data-capture-template",
    response_model=WorkOrderDataCaptureFormResponse,
    summary="Preview capture parameters for a process (templates + fields)",
)
def get_process_data_capture_template(
    process_id: str, db: Session = Depends(get_db)
):
    return data_capture_service.get_process_data_capture_form(db, process_id)


@router.get(
    "/processes/{process_id}/data-capture-templates",
    response_model=List[DataCaptureTemplateResponse],
    summary="List templates for a process (ordered by template_sequence)",
)
def list_process_data_capture_templates(
    process_id: str, db: Session = Depends(get_db)
):
    return data_capture_service.get_process_templates(db, process_id)


@router.post(
    "/processes/{process_id}/data-capture-templates",
    response_model=DataCaptureTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a data capture template for a process",
)
def create_process_data_capture_template(
    process_id: str,
    payload: DataCaptureTemplateCreate,
    db: Session = Depends(get_db),
):
    return data_capture_service.create_template(db, process_id, payload)


@router.post(
    "/data-capture/templates",
    response_model=DataCaptureTemplateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a data capture template (legacy path with process_id in body)",
    include_in_schema=False,
)
def create_data_capture_template_legacy(
    payload: DataCaptureTemplateLegacyCreate,
    db: Session = Depends(get_db),
):
    return data_capture_service.create_template(db, payload.process_id, payload)


@router.put(
    "/data-capture-templates/{template_id}",
    response_model=DataCaptureTemplateResponse,
    summary="Update a data capture template",
)
def update_data_capture_template(
    template_id: str,
    payload: DataCaptureTemplateUpdate,
    db: Session = Depends(get_db),
):
    return data_capture_service.update_template(db, template_id, payload)


@router.get(
    "/data-capture/templates/{template_id}/fields",
    response_model=List[DataCaptureFieldResponse],
    summary="List fields for a template (ordered by field_sequence)",
)
def list_template_fields(template_id: str, db: Session = Depends(get_db)):
    return data_capture_service.get_template_fields(db, template_id)


@router.post(
    "/data-capture-templates/{template_id}/fields",
    response_model=DataCaptureFieldResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a field to a data capture template",
)
def add_template_field(
    template_id: str,
    payload: DataCaptureFieldCreate,
    db: Session = Depends(get_db),
):
    return data_capture_service.add_field_to_template(db, template_id, payload)


@router.post(
    "/data-capture/templates/{template_id}/fields",
    response_model=DataCaptureFieldResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a field to a data capture template (legacy path)",
    include_in_schema=False,
)
def add_template_field_legacy(
    template_id: str,
    payload: DataCaptureFieldCreate,
    db: Session = Depends(get_db),
):
    return data_capture_service.add_field_to_template(db, template_id, payload)


@router.put(
    "/data-capture-fields/{field_id}",
    response_model=DataCaptureFieldResponse,
    summary="Update a data capture field",
)
def update_data_capture_field(
    field_id: str,
    payload: DataCaptureFieldUpdate,
    db: Session = Depends(get_db),
):
    return data_capture_service.update_field(db, field_id, payload)


@router.delete(
    "/data-capture-fields/{field_id}",
    response_model=MessageResponse,
    summary="Delete a data capture field",
)
def delete_data_capture_field(field_id: str, db: Session = Depends(get_db)):
    data_capture_service.delete_field(db, field_id)
    return MessageResponse(message=f"Field '{field_id}' deleted")


@router.get(
    "/work-orders/{work_order_id}/data-capture-template",
    response_model=WorkOrderDataCaptureFormResponse,
    summary="Get dynamic data capture form for a work order",
)
def get_work_order_data_capture_template(
    work_order_id: str, db: Session = Depends(get_db)
):
    return data_capture_service.get_work_order_data_capture_form(db, work_order_id)


@router.post(
    "/work-orders/{work_order_id}/data-capture",
    response_model=DataCaptureSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit captured operation data for a work order",
)
def submit_work_order_data_capture(
    work_order_id: str,
    payload: DataCaptureSubmit,
    db: Session = Depends(get_db),
):
    return data_capture_service.submit_work_order_data_capture(
        db, work_order_id, payload
    )
