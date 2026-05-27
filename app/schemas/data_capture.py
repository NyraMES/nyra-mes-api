"""Data capture template, field, and submission DTOs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class DataCaptureTemplateCreate(BaseModel):
    template_id: Optional[str] = None
    template_name: str
    template_sequence: Optional[int] = None
    capture_stage: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True


class DataCaptureTemplateLegacyCreate(DataCaptureTemplateCreate):
    """Legacy POST body that includes ``process_id`` (route entry UI)."""

    process_id: str


class DataCaptureTemplateUpdate(BaseModel):
    template_name: Optional[str] = None
    template_sequence: Optional[int] = None
    capture_stage: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class DataCaptureTemplateResponse(ORMModel):
    template_id: str
    process_id: str
    template_name: str
    template_sequence: Optional[int] = None
    capture_stage: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = True
    created_at: Optional[datetime] = None
    suggested_next_field_sequence: Optional[int] = Field(
        default=None,
        description="Suggested field_sequence for the next field (max + 10).",
    )


class DataCaptureFieldCreate(BaseModel):
    field_id: Optional[str] = None
    field_sequence: Optional[int] = None
    field_name: str
    field_label: str
    field_type: str = "text"
    unit_of_measure: Optional[str] = None
    is_mandatory: bool = False
    min_value: Optional[Decimal] = None
    max_value: Optional[Decimal] = None
    dropdown_values: Optional[str] = None
    ontology_property: Optional[str] = None


class DataCaptureFieldUpdate(BaseModel):
    field_sequence: Optional[int] = None
    field_name: Optional[str] = None
    field_label: Optional[str] = None
    field_type: Optional[str] = None
    unit_of_measure: Optional[str] = None
    is_mandatory: Optional[bool] = None
    min_value: Optional[Decimal] = None
    max_value: Optional[Decimal] = None
    dropdown_values: Optional[str] = None
    ontology_property: Optional[str] = None


class DataCaptureFieldResponse(ORMModel):
    field_id: str
    template_id: str
    field_sequence: int
    field_name: str
    field_label: str
    field_type: Optional[str] = None
    unit_of_measure: Optional[str] = None
    is_mandatory: Optional[bool] = False
    min_value: Optional[Decimal] = None
    max_value: Optional[Decimal] = None
    dropdown_values: Optional[str] = None
    ontology_property: Optional[str] = None
    created_at: Optional[datetime] = None


class DataCaptureSubmitValue(BaseModel):
    field_id: str
    field_value: Optional[str] = None


class DataCaptureSubmit(BaseModel):
    template_id: str
    captured_by: Optional[str] = None
    values: List[DataCaptureSubmitValue]


class DataCaptureValueResult(BaseModel):
    field_id: str
    value_sequence: int
    field_value: Optional[str] = None
    validation_status: str


class DataCaptureSubmitResponse(BaseModel):
    capture_id: str
    work_order_id: str
    routing_operation_id: str
    template_id: str
    captured_by: Optional[str] = None
    captured_at: Optional[datetime] = None
    values: List[DataCaptureValueResult]


class DataCaptureFormField(BaseModel):
    field_id: str
    field_sequence: int
    field_name: str
    field_label: str
    field_type: Optional[str] = None
    unit_of_measure: Optional[str] = None
    is_mandatory: Optional[bool] = False
    min_value: Optional[Decimal] = None
    max_value: Optional[Decimal] = None
    dropdown_values: Optional[str] = None
    ontology_property: Optional[str] = None


class DataCaptureFormTemplate(BaseModel):
    template_id: str
    template_name: str
    template_sequence: Optional[int] = None
    capture_stage: Optional[str] = None
    description: Optional[str] = None
    fields: List[DataCaptureFormField]


class WorkOrderDataCaptureFormResponse(BaseModel):
    work_order_id: str
    routing_operation_id: str
    operation_name: Optional[str] = None
    process_id: Optional[str] = None
    process_code: Optional[str] = None
    process_name: Optional[str] = None
    templates: List[DataCaptureFormTemplate]
