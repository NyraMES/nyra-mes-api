from decimal import Decimal

from app.core.exceptions import ValidationError
from app.services.industry.activated_carbon.work_orders import (
    assert_kiln_accepts_work_order,
    assert_kiln_output_within_load,
    kiln_current_work_order_code,
    kiln_open_work_order_code,
    kiln_output_target_work_order,
    kiln_remaining_output_kg,
    pending_dispatch_kg,
    work_order_ctc_matches,
    work_order_kiln_output_done,
)


def _wo(code, grade="Grade 1st stage", ctc="40"):
    return {"work_order_code": code, "grade": grade, "ctc": ctc}


def test_kiln_stays_on_one_work_order_until_output_catches_feed():
    meta = {
        "kiln_feed_events": [
            {"work_order_code": "WO-AC-1", "kg": 500},
        ],
        "kiln_output_bags": [],
    }
    lookup = {"WO-AC-1": _wo("WO-AC-1", "Grade 1st stage", "40"), "WO-AC-2": _wo("WO-AC-2", "-20 1st Stage", "50")}.get
    assert kiln_current_work_order_code(meta) == "WO-AC-1"
    assert kiln_open_work_order_code(meta) == "WO-AC-1"
    try:
        assert_kiln_accepts_work_order(meta, "WO-AC-2", incoming=_wo("WO-AC-2", "-20 1st Stage", "50"), lookup=lookup)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass
    assert_kiln_accepts_work_order(meta, "WO-AC-1", incoming=_wo("WO-AC-1"), lookup=lookup)


def test_kiln_accepts_another_work_order_when_grade_and_ctc_match():
    meta = {
        "kiln_feed_events": [
            {"work_order_code": "WO-AC-1", "kg": 500},
        ],
        "kiln_output_bags": [],
    }
    lookup = {"WO-AC-1": _wo("WO-AC-1"), "WO-AC-2": _wo("WO-AC-2")}.get
    assert_kiln_accepts_work_order(meta, "WO-AC-2", incoming=_wo("WO-AC-2"), lookup=lookup)


def test_work_order_leaves_kiln_list_when_output_covers_quantity():
    assert work_order_kiln_output_done(1000, 1000) is True
    assert work_order_kiln_output_done(1000, Decimal("999.999")) is True
    assert work_order_kiln_output_done(1000, 400) is False
    assert work_order_kiln_output_done(1000, 1000, "IN_PROGRESS") is True
    assert work_order_kiln_output_done(1000, 0, "FULFILLED") is True
    assert work_order_kiln_output_done(0, 0) is False


def test_kiln_frees_after_output_covers_feed():
    meta = {
        "kiln_feed_events": [
            {"work_order_code": "WO-AC-1", "kg": 500},
        ],
        "kiln_output_bags": [
            {"work_order_code": "WO-AC-1", "quantity_kg": 500},
        ],
    }
    assert kiln_open_work_order_code(meta) is None
    assert_kiln_accepts_work_order(meta, "WO-AC-2")


def test_kiln_output_blocked_when_nothing_loaded():
    try:
        assert_kiln_output_within_load({}, 10)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass
    try:
        assert_kiln_output_within_load(
            {"kiln_feed_events": [], "kiln_output_bags": []}, 1
        )
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass


def test_kiln_output_cannot_exceed_loaded():
    meta = {
        "kiln_feed_events": [{"work_order_code": "WO-AC-1", "kg": 100}],
        "kiln_output_bags": [{"work_order_code": "WO-AC-1", "quantity_kg": 80}],
    }
    assert kiln_remaining_output_kg(meta) == Decimal("20")
    assert_kiln_output_within_load(meta, 20)
    try:
        assert_kiln_output_within_load(meta, Decimal("20.1"))
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass


def test_kiln_output_caps_across_all_loads():
    meta = {
        "kiln_feed_events": [
            {"work_order_code": "WO-AC-1", "kg": 200},
            {"work_order_code": "WO-AC-1", "kg": 150},
            {"work_order_code": "WO-AC-1", "quantity_kg": 50},
        ],
        "kiln_output_bags": [
            {"work_order_code": "WO-AC-1", "quantity_kg": 180},
            {"work_order_code": "WO-AC-1", "kg": 170},
        ],
    }
    assert kiln_remaining_output_kg(meta) == Decimal("50")
    assert_kiln_output_within_load(meta, 50)
    try:
        assert_kiln_output_within_load(meta, Decimal("50.1"))
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass


def test_output_bag_uses_open_work_order_that_can_take_the_weight():
    meta = {
        "kiln_feed_events": [
            {"work_order_code": "WO-AC-1", "kg": 100},
            {"work_order_code": "WO-AC-2", "kg": 80},
        ],
        "kiln_output_bags": [
            {"work_order_code": "WO-AC-1", "quantity_kg": 100},
        ],
    }
    assert kiln_output_target_work_order(meta, 40) == "WO-AC-2"
    assert kiln_remaining_output_kg(meta) == Decimal("80")


def test_pending_dispatch_kg_after_partial_shipment():
    assert pending_dispatch_kg(500, 250) == Decimal("250")
    assert pending_dispatch_kg(500, 500) == Decimal("0")
    assert pending_dispatch_kg(500, 0) == Decimal("500")


def test_work_order_ctc_match_uses_one_decimal():
    assert work_order_ctc_matches("40", "40.0")
    assert not work_order_ctc_matches("40", "80")
    assert not work_order_ctc_matches("40", None)
