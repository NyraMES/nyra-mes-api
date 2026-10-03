"""Unit tests for AC triplet capture helpers (no DB)."""

from app.services.industry.activated_carbon.triplet_capture import (
    filter_param_defs,
    parameter_object_uri,
    resolve_subject_uri,
)


def test_parameter_object_uri_normalizes_key():
    assert parameter_object_uri("feed_moisture_pct") == "urn:nyra:ac:parameter:FEED_MOISTURE_PCT"
    assert parameter_object_uri("mesh_plus_2_pct") == "urn:nyra:ac:parameter:MESH_PLUS_2_PCT"
    assert parameter_object_uri("mesh_minus_14_pct") == "urn:nyra:ac:parameter:MESH_MINUS_14_PCT"


def test_resolve_subject_uri_inward_and_lot():
    assert (
        resolve_subject_uri(
            "urn:nyra:ac:inward:{order_code}",
            order_code="ORD-AC-1",
        )
        == "urn:nyra:ac:inward:ORD-AC-1"
    )
    assert (
        resolve_subject_uri("urn:nyra:ac:lot:{lot_code}", lot_code="LOT-AC-9")
        == "urn:nyra:ac:lot:LOT-AC-9"
    )


def test_filter_param_defs_by_operation_code():
    defs = [
        {"key": "a", "process_step": "KILN_FEED", "used_at": "execution", "operation_code": "OP-KILN-FEED"},
        {"key": "b", "process_step": "KILN_FEED", "used_at": "execution", "operation_code": "OP-KILN-FEED-QC"},
    ]
    out = filter_param_defs(
        defs,
        process_step="KILN_FEED",
        used_at="execution",
        operation_code="OP-KILN-FEED-QC",
    )
    assert [d["key"] for d in out] == ["b"]


def test_filter_param_defs_inward_used_at_aliases():
    defs = [
        {"key": "our_value_inr", "process_step": "RAW_MATERIAL_INWARD", "used_at": "inward"},
    ]
    out = filter_param_defs(defs, process_step="RAW_MATERIAL_INWARD", used_at="inbound")
    assert len(out) == 1
