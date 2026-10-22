"""Guards for GRC-RPT-2026.10.13-R1 defects D1–D6. Codes and triplet URIs stay as they are."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import ValidationError
from app.services.industry.activated_carbon.adapter import (
    _deston_output_kg_against_load,
    _next_kiln_feed_bag,
    assert_destoner_output_within_load,
    assert_dispatch_within_selected,
    assert_rms_outward_before_release,
)
from app.services.industry.activated_carbon.inbound_execution import _apply_step_domain_rules


def test_destoner_remainder_stays_after_a_partial_bag():
    loaded = [{"bag_code": "DS_131026_00001", "quantity_kg": 450}]
    outputs = [{"bag_code": "DS_131026_00002", "quantity_kg": 250, "input_bag_codes": ["DS_131026_00001"]}]
    assert _deston_output_kg_against_load(loaded, outputs) == Decimal("250")
    assert _deston_output_kg_against_load([], outputs) == Decimal("0")


def test_unburnt_bag_is_blocked_from_kiln_feed():
    meta = {
        "crusher_outward_bags": [
            {"bag_code": "RO_BAG_030", "grade": "Unburnt", "quantity_kg": 20},
            {"bag_code": "RO_BAG_029", "grade": "Grade 1st Stage", "quantity_kg": 80},
        ]
    }
    with pytest.raises(ValidationError, match="Unburnt"):
        _next_kiln_feed_bag(meta, "RO_BAG_030")
    bag = _next_kiln_feed_bag(meta, "RO_BAG_029")
    assert bag["bag_code"] == "RO_BAG_029"


def test_lab_rejects_volatility_above_100():
    order = SimpleNamespace(status="OPEN", order_code="ORD-AC-6")
    meta = {}
    with pytest.raises(ValidationError, match="Volatility"):
        _apply_step_domain_rules(
            None,
            None,
            order,
            meta,
            {"operation_code": "IN-LAB"},
            {"volatility": "120", "moisture_pct": "10", "dust_pct": "1", "qc_decision": "APPROVE"},
        )
    assert "initial_qc" not in meta


def test_short_bag_total_is_not_saved_without_confirmation(monkeypatch):
    order = SimpleNamespace(customer_order_id="x", order_code="ORD-AC-7")
    meta = {"inward_bags": [{"bag_code": "RI_BAG_1", "weight_kg": "5"}]}

    def _received(*_args, **_kwargs):
        return order, Decimal("10")

    monkeypatch.setattr(
        "app.services.industry.activated_carbon.inbound_execution.ac_inbound_workflow._require_inward_order",
        _received,
    )
    with pytest.raises(ValidationError, match="confirm"):
        _apply_step_domain_rules(
            None,
            None,
            order,
            meta,
            {"operation_code": "IN-RMS-BAG"},
            {"short_confirmed": False, "variance_comment": "noted"},
        )
    assert "bag_reconciliation" not in meta

    _apply_step_domain_rules(
        None,
        None,
        order,
        meta,
        {"operation_code": "IN-RMS-BAG"},
        {"short_confirmed": True},
    )
    assert meta["bag_reconciliation"]["status"] == "RECONCILED"


def test_dispatch_cannot_exceed_the_selected_bag():
    with pytest.raises(ValidationError, match="SC_111026_00001"):
        assert_dispatch_within_selected(Decimal("101"), Decimal("100"), bag_code="SC_111026_00001")
    assert_dispatch_within_selected(Decimal("100"), Decimal("100"), bag_code="SC_111026_00001")


def test_release_requires_rms_outward_complete():
    with pytest.raises(ValidationError, match="GRN"):
        assert_rms_outward_before_release({}, "ORD-AC-6")
    assert_rms_outward_before_release({"grade_separation": {"status": "COMPLETED"}}, "ORD-AC-6") is None


def test_destoner_output_cannot_exceed_the_loader():
    with pytest.raises(ValidationError, match="cannot exceed loaded"):
        assert_destoner_output_within_load(Decimal("15"), Decimal("0"), Decimal("16"))
    assert_destoner_output_within_load(Decimal("15"), Decimal("0"), Decimal("15")) is None
