"""Unit tests for AC raw material obsolete / usage locking."""

from app.services.industry.activated_carbon.raw_material_types import _product_is_obsolete
from app.services.industry.activated_carbon.raw_material_usage import (
    KILN_PROCESS_STEPS,
    _execution_started,
)


class _ProductStub:
    def __init__(self, *, status="ACTIVE", metadata=None):
        self.status = status
        self.metadata_ = metadata or {}


class _ExecutionStub:
    def __init__(self, *, status="NOT_STARTED", started_at=None, completed_at=None):
        self.status = status
        self.started_at = started_at
        self.completed_at = completed_at


def test_kiln_process_steps_include_feed_and_activation():
    assert "KILN_FEED" in KILN_PROCESS_STEPS
    assert "ACTIVATION" in KILN_PROCESS_STEPS


def test_product_is_obsolete_from_status():
    assert _product_is_obsolete(_ProductStub(status="OBSOLETE")) is True


def test_product_is_obsolete_from_metadata_flag():
    assert _product_is_obsolete(_ProductStub(metadata={"obsolete": True})) is True


def test_product_is_active_by_default():
    assert _product_is_obsolete(_ProductStub()) is False


def test_execution_started_when_started_at_set():
    assert _execution_started(_ExecutionStub(started_at="2026-01-01")) is True


def test_execution_not_started_when_not_started_status():
    assert _execution_started(_ExecutionStub(status="NOT_STARTED")) is False


def test_execution_started_when_in_progress():
    assert _execution_started(_ExecutionStub(status="IN_PROGRESS")) is True
