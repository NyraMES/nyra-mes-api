"""Tests for Activated Carbon resource claim / release."""

from types import SimpleNamespace

from app.services.industry.activated_carbon.resource_pool import (
    _RUNNING_EXEC_STATUSES,
    _labor_available_for_lot,
    _machine_available_for_lot,
    kiln_release_step,
    lot_has_running_execution,
)


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class _FakeRepo:
    def __init__(self, rows):
        self.rows = rows

    def query(self, _model):
        return _FakeQuery(self.rows)


def test_lot_without_started_work_is_not_running():
    lot = SimpleNamespace(production_lot_id="lot-1")
    repo = _FakeRepo([SimpleNamespace(status="NOT_STARTED"), SimpleNamespace(status="COMPLETED")])
    assert lot_has_running_execution(repo, lot) is False


def test_lot_with_in_progress_work_is_running():
    lot = SimpleNamespace(production_lot_id="lot-1")
    repo = _FakeRepo([SimpleNamespace(status="IN_PROGRESS")])
    assert lot_has_running_execution(repo, lot) is True
    assert "IN_PROGRESS" in _RUNNING_EXEC_STATUSES


def test_kiln_release_step():
    assert kiln_release_step("ACTIVATION")
    assert kiln_release_step("pyrolysis")
    assert not kiln_release_step("KILN_FEED")
    assert not kiln_release_step("SCREENING")


def test_machine_available_when_idle():
    resource = SimpleNamespace(
        status="AVAILABLE",
        metadata_={},
    )
    ok, owner = _machine_available_for_lot(None, resource, lot_code="LOT-1")
    assert ok
    assert owner == ""


def test_machine_blocked_by_other_lot():
    resource = SimpleNamespace(
        status="IN_USE",
        metadata_={"active_lot_code": "LOT-OTHER"},
    )
    ok, owner = _machine_available_for_lot(None, resource, lot_code="LOT-1")
    assert not ok
    assert owner == "LOT-OTHER"


def test_machine_reclaim_same_lot():
    resource = SimpleNamespace(
        status="IN_USE",
        metadata_={"active_lot_code": "LOT-1"},
    )
    ok, owner = _machine_available_for_lot(None, resource, lot_code="LOT-1")
    assert ok


def test_labor_blocked_at_capacity():
    resource = SimpleNamespace(
        status="IN_USE",
        metadata_={"in_use_count": 2, "operators": 2, "active_lot_code": "LOT-2"},
        resource_type="LABOR",
    )
    ok, owner = _labor_available_for_lot(resource, lot_code="LOT-1")
    assert not ok
    assert owner == "LOT-2"
