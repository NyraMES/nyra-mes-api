from app.services.industry.activated_carbon.inbound_admin import (
    DEFAULT_OUTWARD_SPLITS,
    DEFAULT_ROTARIES,
    default_inbound_admin,
    _normalize_rotaries,
    _normalize_splits,
)
from app.services.industry.activated_carbon.inbound_workflow import (
    _rms_bags,
    all_bags_fed_to_crusher,
    next_rms_bag_to_feed,
)


def test_gr_default_rotaries_and_splits():
    admin = default_inbound_admin()
    assert [row["name"] for row in admin["rotaries"]] == ["Rotary A", "Rotary B"]
    assert [row["label"] for row in admin["outward_splits"]] == [
        "-20 1st Stage - Rotary A",
        "Grade 1st stage - Rotary A",
        "-20 2nd Stage - Rotary B",
        "Grade 2nd stage - Rotary B",
        "Stones",
        "Unburnt",
    ]
    assert DEFAULT_ROTARIES[0]["code"] == "ROTARY_A"
    assert DEFAULT_OUTWARD_SPLITS[4]["key"] == "stones"


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
