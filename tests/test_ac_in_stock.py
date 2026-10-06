from app.services.industry.activated_carbon.post_activation import (
    bag_is_available_in_stock,
    _is_in_stock_destination,
    _normalize_destination_label,
)


def test_in_stock_destination_aliases():
    assert _is_in_stock_destination("In Stock")
    assert _is_in_stock_destination("instock")
    assert _is_in_stock_destination("IN-STOCK")
    assert not _is_in_stock_destination("Screening")
    assert not _is_in_stock_destination("")
    assert _normalize_destination_label("In Stock") is None
    assert _normalize_destination_label("Screening") == "screening"


def test_bag_is_available_in_stock_requires_saved_destination():
    unsaved = {
        "bag_code": "DS_051026_00001",
        "quantity_kg": 100,
        "destoning_qc": {"values": {"deston_qc_destination": "In Stock"}},
    }
    assert bag_is_available_in_stock(unsaved) is False

    saved = {
        "bag_code": "DS_051026_00002",
        "quantity_kg": 80,
        "destoning_qc": {
            "saved_at": "2026-10-05T05:00:00+00:00",
            "values": {"deston_qc_destination": "In Stock"},
        },
    }
    assert bag_is_available_in_stock(saved) is True

    routed = {
        "bag_code": "DS_051026_00003",
        "quantity_kg": 50,
        "destoning_qc": {
            "saved_at": "2026-10-05T05:00:00+00:00",
            "values": {"deston_qc_destination": "Screening"},
        },
    }
    assert bag_is_available_in_stock(routed) is False

    dispatched = {
        **saved,
        "dispatched_kg": 80,
    }
    assert bag_is_available_in_stock(dispatched) is False


def test_post_activation_in_stock_bag():
    bag = {
        "bag_code": "SC_051026_00001",
        "quantity_kg": 40,
        "grade": "Exklin",
        "quality_qc": {
            "saved_at": "2026-10-05T06:00:00+00:00",
            "values": {"post_qc_destination": "In Stock"},
        },
    }
    assert bag_is_available_in_stock(bag) is True
