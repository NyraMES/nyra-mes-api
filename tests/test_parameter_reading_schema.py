"""Unit tests for execution parameter reading DTOs."""

from decimal import Decimal

from app.schemas.schedule import ParameterReadingInput, WorkOrderCompleteRequest


def test_work_order_complete_accepts_parameter_readings():
    payload = WorkOrderCompleteRequest(
        actual_output_quantity=Decimal("100"),
        parameter_readings=[
            ParameterReadingInput(
                parameter_code="MOISTURE_PCT",
                reading_value=Decimal("8.5"),
            ),
            ParameterReadingInput(
                parameter_code="VISUAL_OK",
                reading_text="true",
            ),
        ],
    )
    assert len(payload.parameter_readings) == 2
    assert payload.parameter_readings[0].parameter_code == "MOISTURE_PCT"
    assert payload.parameter_readings[1].reading_text == "true"
