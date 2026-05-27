"""Process library and dynamic data capture services."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.data_capture import (
    DataCaptureField,
    DataCaptureTemplate,
    OperationDataCapture,
    OperationDataCaptureValue,
)
from app.models.process import ProcessLibrary
from app.models.routing import RoutingOperation
from app.models.work_order import WorkOrder
from app.schemas.data_capture import (
    DataCaptureFieldCreate,
    DataCaptureFieldResponse,
    DataCaptureFieldUpdate,
    DataCaptureFormField,
    DataCaptureFormTemplate,
    DataCaptureSubmit,
    DataCaptureSubmitResponse,
    DataCaptureTemplateCreate,
    DataCaptureTemplateResponse,
    DataCaptureTemplateUpdate,
    DataCaptureValueResult,
    WorkOrderDataCaptureFormResponse,
)
from app.services import process_service
from app.utils.ids import generate_business_id

SEQUENCE_STEP = 10

# Resolve process when routing_operation.process_id is null (legacy routings).
_PROCESS_NAME_HINTS: list[tuple[str, str]] = [
    ("mould", "PROC_MOULDING"),
    ("mold", "PROC_MOULDING"),
    ("melting", "PROC_MELTING"),
    ("melt", "PROC_MELTING"),
    ("pour", "PROC_POURING"),
    ("fettling", "PROC_FETTLING"),
    ("fettle", "PROC_FETTLING"),
    ("raw material", "PROC_FINAL_QC"),
    ("final", "PROC_FINAL_QC"),
    ("inspect", "PROC_FINAL_QC"),
    ("qc", "PROC_FINAL_QC"),
]


def _suggest_process_id(operation_name: Optional[str]) -> Optional[str]:
    name = (operation_name or "").lower()
    for hint, process_id in _PROCESS_NAME_HINTS:
        if hint in name:
            return process_id
    return None


def _resolve_operation_process_id(
    db: Session, op: RoutingOperation
) -> Optional[str]:
    if op.process_id:
        return op.process_id
    suggested = _suggest_process_id(op.operation_name)
    if not suggested:
        return None
    exists = (
        db.query(ProcessLibrary.process_id)
        .filter(ProcessLibrary.process_id == suggested)
        .first()
    )
    return suggested if exists else None


# ---------------------------------------------------------------------------
# Sequence helpers
# ---------------------------------------------------------------------------

def next_operation_sequence(db: Session, routing_pk: int) -> int:
    current = (
        db.query(func.max(RoutingOperation.operation_sequence))
        .filter(RoutingOperation.routing_id == routing_pk)
        .scalar()
    )
    return (current or 0) + SEQUENCE_STEP


def next_field_sequence(db: Session, template_id: str) -> int:
    current = (
        db.query(func.max(DataCaptureField.field_sequence))
        .filter(DataCaptureField.template_id == template_id)
        .scalar()
    )
    return (current or 0) + SEQUENCE_STEP


def next_template_sequence(db: Session, process_id: str) -> int:
    current = (
        db.query(func.max(DataCaptureTemplate.template_sequence))
        .filter(DataCaptureTemplate.process_id == process_id)
        .scalar()
    )
    return (current or 0) + SEQUENCE_STEP


def _ensure_unique_operation_sequence(
    db: Session, routing_pk: int, operation_sequence: int, *, exclude_id: Optional[int] = None
) -> None:
    q = db.query(RoutingOperation).filter(
        RoutingOperation.routing_id == routing_pk,
        RoutingOperation.operation_sequence == operation_sequence,
    )
    if exclude_id is not None:
        q = q.filter(RoutingOperation.id != exclude_id)
    if q.first():
        raise ConflictError(
            f"operation_sequence {operation_sequence} already exists for this routing"
        )


def _ensure_unique_field_sequence(
    db: Session, template_id: str, field_sequence: int, *, exclude_field_id: Optional[str] = None
) -> None:
    q = db.query(DataCaptureField).filter(
        DataCaptureField.template_id == template_id,
        DataCaptureField.field_sequence == field_sequence,
    )
    if exclude_field_id is not None:
        q = q.filter(DataCaptureField.field_id != exclude_field_id)
    if q.first():
        raise ConflictError(
            f"field_sequence {field_sequence} already exists for template '{template_id}'"
        )


def _ensure_unique_template_sequence(
    db: Session,
    process_id: str,
    template_sequence: int,
    *,
    exclude_template_id: Optional[str] = None,
) -> None:
    q = db.query(DataCaptureTemplate).filter(
        DataCaptureTemplate.process_id == process_id,
        DataCaptureTemplate.template_sequence == template_sequence,
    )
    if exclude_template_id is not None:
        q = q.filter(DataCaptureTemplate.template_id != exclude_template_id)
    if q.first():
        raise ConflictError(
            f"template_sequence {template_sequence} already exists for process '{process_id}'"
        )


# ---------------------------------------------------------------------------
# Templates + fields (master)
# ---------------------------------------------------------------------------

def _template_to_out(db: Session, row: DataCaptureTemplate) -> DataCaptureTemplateResponse:
    return DataCaptureTemplateResponse(
        template_id=row.template_id,
        process_id=row.process_id,
        template_name=row.template_name,
        template_sequence=row.template_sequence,
        capture_stage=row.capture_stage,
        description=row.description,
        is_active=row.is_active,
        created_at=row.created_at,
        suggested_next_field_sequence=next_field_sequence(db, row.template_id),
    )


def _field_to_out(row: DataCaptureField) -> DataCaptureFieldResponse:
    return DataCaptureFieldResponse(
        field_id=row.field_id,
        template_id=row.template_id,
        field_sequence=row.field_sequence,
        field_name=row.field_name,
        field_label=row.field_label,
        field_type=row.field_type,
        unit_of_measure=row.unit_of_measure,
        is_mandatory=row.is_mandatory,
        min_value=row.min_value,
        max_value=row.max_value,
        dropdown_values=row.dropdown_values,
        ontology_property=row.ontology_property,
        created_at=row.created_at,
    )


def _field_to_form(row: DataCaptureField) -> DataCaptureFormField:
    return DataCaptureFormField(
        field_id=row.field_id,
        field_sequence=row.field_sequence,
        field_name=row.field_name,
        field_label=row.field_label,
        field_type=row.field_type,
        unit_of_measure=row.unit_of_measure,
        is_mandatory=row.is_mandatory,
        min_value=row.min_value,
        max_value=row.max_value,
        dropdown_values=row.dropdown_values,
        ontology_property=row.ontology_property,
    )


def get_process_templates(db: Session, process_id: str) -> List[DataCaptureTemplateResponse]:
    process_service.get_process_row(db, process_id)
    rows = (
        db.query(DataCaptureTemplate)
        .filter(DataCaptureTemplate.process_id == process_id)
        .order_by(DataCaptureTemplate.template_sequence.asc().nullslast(), DataCaptureTemplate.template_id)
        .all()
    )
    return [_template_to_out(db, r) for r in rows]


def get_template_fields(db: Session, template_id: str) -> List[DataCaptureFieldResponse]:
    template = (
        db.query(DataCaptureTemplate)
        .filter(DataCaptureTemplate.template_id == template_id)
        .first()
    )
    if not template:
        raise NotFoundError(f"Data capture template '{template_id}' not found")
    rows = (
        db.query(DataCaptureField)
        .filter(DataCaptureField.template_id == template_id)
        .order_by(DataCaptureField.field_sequence, DataCaptureField.field_id)
        .all()
    )
    return [_field_to_out(r) for r in rows]


def create_template(
    db: Session, process_id: str, payload: DataCaptureTemplateCreate
) -> DataCaptureTemplateResponse:
    process_service.get_process_row(db, process_id)
    template_id = (payload.template_id or "").strip() or generate_business_id(
        db,
        prefix="DCT",
        fallback_table="mst.data_capture_template",
        fallback_column="template_id",
    )
    if (
        db.query(DataCaptureTemplate)
        .filter(DataCaptureTemplate.template_id == template_id)
        .first()
    ):
        raise ConflictError(f"Template '{template_id}' already exists")

    template_sequence = (
        payload.template_sequence
        if payload.template_sequence is not None
        else next_template_sequence(db, process_id)
    )
    _ensure_unique_template_sequence(db, process_id, template_sequence)

    row = DataCaptureTemplate(
        template_id=template_id,
        process_id=process_id,
        template_name=payload.template_name.strip(),
        template_sequence=template_sequence,
        capture_stage=payload.capture_stage,
        description=payload.description,
        is_active=payload.is_active,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Template could not be created: {exc.orig}") from exc
    db.refresh(row)
    return _template_to_out(db, row)


def update_template(
    db: Session, template_id: str, payload: DataCaptureTemplateUpdate
) -> DataCaptureTemplateResponse:
    row = (
        db.query(DataCaptureTemplate)
        .filter(DataCaptureTemplate.template_id == template_id)
        .first()
    )
    if not row:
        raise NotFoundError(f"Data capture template '{template_id}' not found")

    if payload.template_name is not None:
        row.template_name = payload.template_name.strip()
    if payload.template_sequence is not None:
        _ensure_unique_template_sequence(
            db,
            row.process_id,
            payload.template_sequence,
            exclude_template_id=template_id,
        )
        row.template_sequence = payload.template_sequence
    if payload.capture_stage is not None:
        row.capture_stage = payload.capture_stage
    if payload.description is not None:
        row.description = payload.description
    if payload.is_active is not None:
        row.is_active = payload.is_active

    db.commit()
    db.refresh(row)
    return _template_to_out(db, row)


def add_field_to_template(
    db: Session, template_id: str, payload: DataCaptureFieldCreate
) -> DataCaptureFieldResponse:
    template = (
        db.query(DataCaptureTemplate)
        .filter(DataCaptureTemplate.template_id == template_id)
        .first()
    )
    if not template:
        raise NotFoundError(f"Data capture template '{template_id}' not found")

    field_id = (payload.field_id or "").strip() or generate_business_id(
        db,
        prefix="DCF",
        fallback_table="mst.data_capture_field",
        fallback_column="field_id",
    )
    if db.query(DataCaptureField).filter(DataCaptureField.field_id == field_id).first():
        raise ConflictError(f"Field '{field_id}' already exists")

    field_sequence = (
        payload.field_sequence
        if payload.field_sequence is not None
        else next_field_sequence(db, template_id)
    )
    _ensure_unique_field_sequence(db, template_id, field_sequence)

    row = DataCaptureField(
        field_id=field_id,
        template_id=template_id,
        field_sequence=field_sequence,
        field_name=payload.field_name.strip(),
        field_label=payload.field_label.strip(),
        field_type=payload.field_type,
        unit_of_measure=payload.unit_of_measure,
        is_mandatory=payload.is_mandatory,
        min_value=payload.min_value,
        max_value=payload.max_value,
        dropdown_values=payload.dropdown_values,
        ontology_property=payload.ontology_property,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Field could not be created: {exc.orig}") from exc
    db.refresh(row)
    return _field_to_out(row)


def update_field(
    db: Session, field_id: str, payload: DataCaptureFieldUpdate
) -> DataCaptureFieldResponse:
    row = (
        db.query(DataCaptureField)
        .filter(DataCaptureField.field_id == field_id)
        .first()
    )
    if not row:
        raise NotFoundError(f"Data capture field '{field_id}' not found")

    if payload.field_sequence is not None:
        _ensure_unique_field_sequence(
            db,
            row.template_id,
            payload.field_sequence,
            exclude_field_id=field_id,
        )
        row.field_sequence = payload.field_sequence
    if payload.field_name is not None:
        row.field_name = payload.field_name.strip()
    if payload.field_label is not None:
        row.field_label = payload.field_label.strip()
    if payload.field_type is not None:
        row.field_type = payload.field_type
    if payload.unit_of_measure is not None:
        row.unit_of_measure = payload.unit_of_measure
    if payload.is_mandatory is not None:
        row.is_mandatory = payload.is_mandatory
    if payload.min_value is not None:
        row.min_value = payload.min_value
    if payload.max_value is not None:
        row.max_value = payload.max_value
    if payload.dropdown_values is not None:
        row.dropdown_values = payload.dropdown_values
    if payload.ontology_property is not None:
        row.ontology_property = payload.ontology_property

    db.commit()
    db.refresh(row)
    return _field_to_out(row)


def delete_field(db: Session, field_id: str) -> None:
    row = (
        db.query(DataCaptureField)
        .filter(DataCaptureField.field_id == field_id)
        .first()
    )
    if not row:
        raise NotFoundError(f"Data capture field '{field_id}' not found")
    db.delete(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"Field '{field_id}' cannot be deleted: capture data may reference it"
        ) from exc


# ---------------------------------------------------------------------------
# Dynamic work-order form + submission
# ---------------------------------------------------------------------------

def _get_work_order_row(db: Session, work_order_code: str) -> WorkOrder:
    row = (
        db.query(WorkOrder)
        .filter(WorkOrder.work_order_code == work_order_code)
        .first()
    )
    if not row:
        raise NotFoundError(f"Work order '{work_order_code}' not found")
    return row


def get_process_form_templates(
    db: Session, process_id: str
) -> List[DataCaptureFormTemplate]:
    """Active templates and ordered fields for a process (shared by routing + WO forms)."""
    template_rows = (
        db.query(DataCaptureTemplate)
        .filter(
            DataCaptureTemplate.process_id == process_id,
            DataCaptureTemplate.is_active.is_(True),
        )
        .order_by(
            DataCaptureTemplate.template_sequence.asc().nullslast(),
            DataCaptureTemplate.template_id,
        )
        .all()
    )
    templates: List[DataCaptureFormTemplate] = []
    for tmpl in template_rows:
        field_rows = (
            db.query(DataCaptureField)
            .filter(DataCaptureField.template_id == tmpl.template_id)
            .order_by(DataCaptureField.field_sequence, DataCaptureField.field_id)
            .all()
        )
        templates.append(
            DataCaptureFormTemplate(
                template_id=tmpl.template_id,
                template_name=tmpl.template_name,
                template_sequence=tmpl.template_sequence,
                capture_stage=tmpl.capture_stage,
                description=tmpl.description,
                fields=[_field_to_form(f) for f in field_rows],
            )
        )
    return templates


def _build_form_for_process(
    db: Session,
    *,
    work_order_code: str,
    operation_code: str,
    operation_name: Optional[str],
    process_id: Optional[str],
) -> WorkOrderDataCaptureFormResponse:
    process_row: Optional[ProcessLibrary] = None
    if process_id:
        process_row = (
            db.query(ProcessLibrary)
            .filter(ProcessLibrary.process_id == process_id)
            .first()
        )

    templates = get_process_form_templates(db, process_id) if process_id else []

    return WorkOrderDataCaptureFormResponse(
        work_order_id=work_order_code,
        routing_operation_id=operation_code,
        operation_name=operation_name,
        process_id=process_id,
        process_code=process_row.process_code if process_row else None,
        process_name=process_row.process_name if process_row else None,
        templates=templates,
    )


def get_work_order_data_capture_form(
    db: Session, work_order_code: str
) -> WorkOrderDataCaptureFormResponse:
    wo = _get_work_order_row(db, work_order_code)
    if not wo.routing_operation_id:
        raise ValidationError(
            f"Work order '{work_order_code}' is not linked to a routing operation"
        )

    op = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.id == wo.routing_operation_id)
        .first()
    )
    if not op:
        raise NotFoundError(
            f"Routing operation for work order '{work_order_code}' not found"
        )

    return _build_form_for_process(
        db,
        work_order_code=work_order_code,
        operation_code=op.operation_code,
        operation_name=op.operation_name,
        process_id=_resolve_operation_process_id(db, op),
    )


def get_process_data_capture_form(
    db: Session, process_id: str
) -> WorkOrderDataCaptureFormResponse:
    """Preview form layout for a process (no work order context)."""
    process_service.get_process_row(db, process_id)
    return _build_form_for_process(
        db,
        work_order_code="",
        operation_code="",
        operation_name=None,
        process_id=process_id,
    )


def _validate_field_value(
    field: DataCaptureField, raw_value: Optional[str]
) -> str:
    value = (raw_value or "").strip()
    if field.is_mandatory and not value:
        raise ValidationError(
            f"Mandatory field '{field.field_label}' ({field.field_id}) is required"
        )
    if not value:
        return "OK"

    field_type = (field.field_type or "text").lower()
    if field_type == "number":
        try:
            numeric = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(
                f"Field '{field.field_label}' must be a number"
            ) from exc
        if field.min_value is not None and numeric < field.min_value:
            return "NOT_OK"
        if field.max_value is not None and numeric > field.max_value:
            return "NOT_OK"
    return "OK"


def submit_work_order_data_capture(
    db: Session, work_order_code: str, payload: DataCaptureSubmit
) -> DataCaptureSubmitResponse:
    wo = _get_work_order_row(db, work_order_code)
    if not wo.routing_operation_id:
        raise ValidationError(
            f"Work order '{work_order_code}' is not linked to a routing operation"
        )

    op = (
        db.query(RoutingOperation)
        .filter(RoutingOperation.id == wo.routing_operation_id)
        .first()
    )
    if not op:
        raise NotFoundError(
            f"Routing operation for work order '{work_order_code}' not found"
        )

    template = (
        db.query(DataCaptureTemplate)
        .filter(DataCaptureTemplate.template_id == payload.template_id)
        .first()
    )
    if not template:
        raise NotFoundError(f"Template '{payload.template_id}' not found")
    if not template.is_active:
        raise ValidationError(f"Template '{payload.template_id}' is not active")
    if op.process_id and template.process_id != op.process_id:
        raise ValidationError(
            "Template does not belong to the process linked to this work order"
        )
    resolved_process = _resolve_operation_process_id(db, op)
    if resolved_process and template.process_id != resolved_process:
        raise ValidationError(
            "Template does not belong to the process linked to this work order"
        )

    fields = (
        db.query(DataCaptureField)
        .filter(DataCaptureField.template_id == payload.template_id)
        .order_by(DataCaptureField.field_sequence, DataCaptureField.field_id)
        .all()
    )
    if not fields:
        raise ValidationError(f"Template '{payload.template_id}' has no fields defined")

    field_by_id = {f.field_id: f for f in fields}
    submitted = {v.field_id: v.field_value for v in payload.values}

    for field in fields:
        if field.is_mandatory and not (submitted.get(field.field_id) or "").strip():
            raise ValidationError(
                f"Mandatory field '{field.field_label}' ({field.field_id}) is required"
            )

    capture_id = generate_business_id(
        db,
        prefix="CAP",
        fallback_table="trn.operation_data_capture",
        fallback_column="capture_id",
    )
    capture = OperationDataCapture(
        capture_id=capture_id,
        work_order_id=work_order_code,
        routing_operation_id=op.operation_code,
        template_id=payload.template_id,
        captured_by=payload.captured_by,
    )
    db.add(capture)
    db.flush()

    value_results: List[DataCaptureValueResult] = []
    for field in fields:
        raw = submitted.get(field.field_id)
        status = _validate_field_value(field, raw)
        value_id = generate_business_id(
            db,
            prefix="CV",
            fallback_table="trn.operation_data_capture_value",
            fallback_column="capture_value_id",
        )
        value_row = OperationDataCaptureValue(
            capture_value_id=value_id,
            capture_id=capture_id,
            field_id=field.field_id,
            value_sequence=field.field_sequence,
            field_value=(raw or "").strip() or None,
            validation_status=status,
        )
        db.add(value_row)
        value_results.append(
            DataCaptureValueResult(
                field_id=field.field_id,
                value_sequence=field.field_sequence,
                field_value=value_row.field_value,
                validation_status=status,
            )
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"Data capture could not be saved: {exc.orig}") from exc
    db.refresh(capture)

    return DataCaptureSubmitResponse(
        capture_id=capture.capture_id,
        work_order_id=capture.work_order_id,
        routing_operation_id=capture.routing_operation_id,
        template_id=capture.template_id,
        captured_by=capture.captured_by,
        captured_at=capture.captured_at,
        values=value_results,
    )


__all__ = [
    "add_field_to_template",
    "create_template",
    "delete_field",
    "get_process_data_capture_form",
    "get_process_templates",
    "get_template_fields",
    "get_work_order_data_capture_form",
    "next_field_sequence",
    "next_operation_sequence",
    "next_template_sequence",
    "submit_work_order_data_capture",
    "update_field",
    "update_template",
    "_ensure_unique_operation_sequence",
    "_ensure_unique_field_sequence",
    "_ensure_unique_template_sequence",
]
