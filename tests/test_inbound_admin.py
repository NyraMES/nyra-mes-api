from types import SimpleNamespace

from app.services.industry.activated_carbon.codes import kiln_output_id_prefix
from app.services.industry.activated_carbon.inbound_execution import (
    mandatory_inbound_prep_complete,
    next_inbound_operation,
)
from app.core.exceptions import ValidationError
from app.services.industry.activated_carbon.inbound_admin import (
    DEFAULT_OUTWARD_SPLITS,
    DEFAULT_ROTARIES,
    default_inbound_admin,
    validate_outward_kg_within_inward,
    validate_rm_outward_splits,
    _normalize_rotaries,
    _normalize_splits,
)
from app.services.industry.activated_carbon.inbound_workflow import (
    _is_kiln_feed_bag,
    _kiln_feed_outward_bags,
    _rms_bags,
    all_bags_fed_to_crusher,
    lab_denied,
    next_rms_bag_to_feed,
)


def test_gr_default_rotaries_and_splits():
    admin = default_inbound_admin()
    assert [row["name"] for row in admin["rotaries"]] == ["Rotary A", "Rotary B"]
    assert [row["label"] for row in admin["outward_splits"]] == [
        "-20 1st Stage",
        "Grade 1st Stage",
        "Unburnt",
        "Stones",
    ]
    assert DEFAULT_ROTARIES[0]["code"] == "ROTARY_A"
    assert DEFAULT_OUTWARD_SPLITS[3]["key"] == "stones"


def test_kiln_output_prefix_ka_kb():
    assert kiln_output_id_prefix("Kiln A", "RES-KILN-01") == "KA"
    assert kiln_output_id_prefix("Activation Kiln 01", "RES-KILN-01") == "KA"
    assert kiln_output_id_prefix("Klin 02", "RES-KILN-0002") == "KB"
    assert kiln_output_id_prefix("Kiln B", "RES-KILN-02") == "KB"


def test_normalize_fills_code_from_name():
    rows = _normalize_rotaries([{"name": "Rotary C"}])
    assert rows[-1]["code"] == "ROTARY_C"
    splits = _normalize_splits([{"label": "Grade 3rd stage"}])
    assert any(row["label"] == "Grade 3rd stage" for row in splits)


def test_rms_bags_ignore_outward_grades():
    meta = {
        "inward_bags": [
            {"bag_id": "1", "bag_code": "BAG-AC-1001", "weight_kg": "600", "status": "REGISTERED"},
            {"bag_id": "2", "bag_code": "BAG-AC-1002", "weight_kg": "400", "status": "REGISTERED"},
            {
                "bag_id": "3",
                "bag_code": "BAG-AC-1003",
                "weight_kg": "120",
                "grade": "Stones",
                "status": "REGISTERED",
            },
        ]
    }
    rms = _rms_bags(meta)
    assert [row["bag_id"] for row in rms] == ["1", "2"]
    assert next_rms_bag_to_feed(meta)["bag_id"] == "1"
    assert all_bags_fed_to_crusher(meta) is False


def test_feed_order_is_one_by_one():
    meta = {
        "inward_bags": [
            {"bag_id": "1", "weight_kg": "500", "status": "FED_TO_CRUSHER"},
            {"bag_id": "2", "weight_kg": "500", "status": "REGISTERED"},
            {"bag_id": "3", "weight_kg": "80", "grade": "Unburnt", "status": "REGISTERED"},
        ]
    }
    assert next_rms_bag_to_feed(meta)["bag_id"] == "2"
    meta["inward_bags"][1]["status"] = "FED_TO_CRUSHER"
    assert next_rms_bag_to_feed(meta) is None
    assert all_bags_fed_to_crusher(meta) is True


def _prep_type():
    return SimpleNamespace(
        inbound_operations=[
            {
                "operation_code": "IN-LAB",
                "process_step": "SCREENING",
                "operation_name": "Lab",
                "operation_sequence": 1,
                "is_mandatory": True,
            },
            {
                "operation_code": "IN-RMS-BAG",
                "process_step": "PACKING",
                "operation_name": "RMS inward",
                "operation_sequence": 2,
                "is_mandatory": True,
            },
        ]
    )


def test_lab_deny_does_not_advance_to_rms():
    meta = {
        "inbound_lab_denied": True,
        "initial_qc": {"qc_status": "FAIL", "remarks": "stones"},
        "inbound_execution": {
            "IN-LAB": {"status": "DENIED", "qc_decision": "deny"},
        },
    }
    material = _prep_type()
    assert lab_denied(meta) is True
    assert next_inbound_operation(material, meta) is None
    assert mandatory_inbound_prep_complete(material, meta) is False


def test_rm_outward_kg_cannot_exceed_inward():
    validate_outward_kg_within_inward(100, 100)
    validate_outward_kg_within_inward(99.999, 100)
    try:
        validate_outward_kg_within_inward(100.01, 100)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass


def test_rm_outward_one_rotary_with_value_stones_unburnt():
    validate_rm_outward_splits(
        [
            {"grade_label": "-20 1st Stage", "rotary": "Rotary A"},
            {"grade_label": "Unburnt", "rotary": "Rotary A"},
            {"grade_label": "Stones", "rotary": "Rotary A"},
        ]
    )


def test_rm_outward_rejects_missing_stones_or_value():
    try:
        validate_rm_outward_splits(
            [
                {"grade_label": "-20 1st Stage", "rotary": "Rotary B"},
                {"grade_label": "Unburnt", "rotary": "Rotary B"},
            ]
        )
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass
    try:
        validate_rm_outward_splits(
            [
                {"grade_label": "Unburnt", "rotary": "Rotary A"},
                {"grade_label": "Stones", "rotary": "Rotary A"},
            ]
        )
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass


def test_kiln_feed_bags_exclude_unburnt_and_stones():
    meta = {
        "inward_bags": [
            {"bag_code": "RO_BAG_001", "grade": "-20 1st Stage", "rotary": "Rotary A", "weight_kg": "100"},
            {"bag_code": "RO_BAG_002", "grade": "Unburnt", "rotary": "Rotary A", "weight_kg": "10"},
            {"bag_code": "RO_BAG_003", "grade": "Stones", "rotary": "Rotary A", "weight_kg": "8"},
            {"bag_code": "RO_BAG_004", "grade": "Grade 1st Stage", "rotary": "Rotary A", "weight_kg": "80"},
        ]
    }
    bags = _kiln_feed_outward_bags(meta)
    assert [row["bag_code"] for row in bags] == ["RO_BAG_001", "RO_BAG_004"]
    assert _is_kiln_feed_bag({"grade_label": "Stones"}) is False
