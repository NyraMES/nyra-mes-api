from datetime import date

from app.services.industry.activated_carbon.process_rules import (
    DESTONING_REWORK_DESTINATION,
    INSTOCK_DESTINATION,
    SCREENING_DESTINATION,
    INITIAL_SCREENING_OUTPUT_LABEL,
    SAD_DESTINATION,
    assert_destoner_plan_ctc,
    assert_same_ctc,
    destoning_destination_from_stones,
    destoning_stones_present,
    is_destoning_rework_destination,
    is_kiln_feed_bag_qc_step,
    moisture_requires_drying,
    normalize_process_rules,
    normalized_inbound_operations,
    plan_rms_bag_weights,
    round_ctc,
    without_kiln_feed_bag_qc_operations,
    without_kiln_feed_bag_qc_parameters,
)
from app.core.exceptions import ValidationError
from app.services.industry.activated_carbon.codes import kiln_output_id_prefix


def test_post_activation_output_minutes_use_the_500kg_estimate():
    blank = normalize_process_rules({})
    minutes = blank["post_activation_output_minutes"]
    assert minutes["screening"] == 20
    assert minutes["dedusting"] == 10
    assert minutes["destoning"] == 15
    assert minutes["demagnetisation"] == 5
    assert minutes["material_handling"] == 10
    assert minutes["crushing"] is None
    assert minutes["blending"] is None
    saved = normalize_process_rules(
        {"post_activation_output_minutes": {"screening": 45, "crushing": 0, "blending": ""}}
    )
    assert saved["post_activation_output_minutes"]["screening"] == 45
    assert saved["post_activation_output_minutes"]["crushing"] is None
    assert saved["post_activation_output_minutes"]["blending"] is None
    assert saved["post_activation_output_minutes"]["dedusting"] == 10


def test_ctc_round_one_decimal_and_match():
    assert round_ctc("12.34") == round_ctc("12.3")
    assert_same_ctc("12.34", "12.3", decimals=1)
    try:
        assert_same_ctc("12.3", "12.5", decimals=1)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass
    try:
        assert_same_ctc(None, None, decimals=1, missing_blocks=True)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass


def test_destoner_plan_ctc_requires_supervisor_and_match():
    assert_destoner_plan_ctc("12.34", "12.3", decimals=1)
    try:
        assert_destoner_plan_ctc(None, "12.3", decimals=1)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass
    try:
        assert_destoner_plan_ctc("12.3", None, decimals=1)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass
    try:
        assert_destoner_plan_ctc("12.3", "11.0", decimals=1)
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass


def test_mesh_configurations_a_to_e():
    from app.services.industry.activated_carbon.mesh_grade import (
        deston_grade_param_code,
        normalize_mesh_grade_map,
    )

    catalog = normalize_mesh_grade_map({})
    by_code = {row["code"]: row["grades"] for row in catalog["configurations"]}
    assert by_code["A"] == ["+3", "3/4", "-4"]
    assert by_code["B"] == ["+4", "4/8", "-8"]
    assert by_code["C"] == ["+8", "8/12", "-12"]
    assert by_code["D"] == ["+12", "12/30", "-30"]
    assert by_code["E"] == ["+3", "3/4", "4/8", "8/12", "12/30", "-30"]
    assert deston_grade_param_code("\u22124") == "deston_qc_minus_4_kg"
    assert deston_grade_param_code("3/4") == "deston_qc_3_4_kg"
    assert catalog["rows"][0]["station"] == "destoning"


def test_screening_after_destoning_is_not_a_destoner():
    from app.services.industry.activated_carbon.plant_equipment import _is_destoner

    class Dummy:
        def __init__(self, code, name, meta=None):
            self.resource_code = code
            self.resource_name = name
            self.metadata_ = meta or {}

    assert _is_destoner(Dummy("RES-DESTON-01", "De-Stoner", {"role": "destoning"}))
    assert _is_destoner(Dummy("RES-DESTON-02", "Destoner 2"))
    assert not _is_destoner(Dummy("RES-MACH-006", "Screening after Destoning"))
    assert not _is_destoner(
        Dummy("RES-MACH-007", "Screening after Destoning", {"station": "destoning", "role": "destoning"})
    )


def test_destoner_plan_ctc_matches_whole_numbers():
    from app.services.industry.activated_carbon.process_rules import (
        assert_destoner_plan_ctc,
        round_ctc,
    )

    assert str(round_ctc("40")) == "40.0"
    assert str(round_ctc(80)) == "80.0"
    assert assert_destoner_plan_ctc("40.0", "40") == round_ctc(40)
    assert assert_destoner_plan_ctc("80", "80.0") == round_ctc(80)


def test_kiln_feed_accepts_rotary_grades():
    from app.services.industry.activated_carbon.inbound_workflow import _is_kiln_feed_grade

    assert _is_kiln_feed_grade("Grade 1st Stage") is True
    assert _is_kiln_feed_grade("-20 1st Stage") is True
    assert _is_kiln_feed_grade("Unburnt") is False
    assert _is_kiln_feed_grade("Stones") is False


def test_destoner_daily_ctc_is_today_only():
    from app.services.industry.activated_carbon.plant_equipment import destoner_daily_ctc

    class Dummy:
        def __init__(self, meta):
            self.metadata_ = meta

    row = Dummy({"daily_ctc": "12.3", "daily_ctc_date": "2026-10-08", "daily_ctc_by": "plant.mgr"})
    assert destoner_daily_ctc(row, date(2026, 10, 8)) == "12.3"
    assert destoner_daily_ctc(row, date(2026, 10, 9)) is None


def test_destoner_daily_mesh_is_today_only():
    from app.services.industry.activated_carbon.mesh_grade import (
        normalize_mesh_grade_map,
        resolve_mesh_code,
    )
    from app.services.industry.activated_carbon.plant_equipment import (
        destoner_daily_mesh,
        destoner_plan_meta,
    )

    class Dummy:
        def __init__(self, meta, code="RES-DESTON-01"):
            self.resource_code = code
            self.metadata_ = meta

    row = Dummy(
        {
            "daily_ctc": "45.0",
            "daily_ctc_date": "2026-10-08",
            "daily_mesh": "B",
            "daily_mesh_date": "2026-10-08",
        }
    )
    assert destoner_daily_mesh(row, date(2026, 10, 8)) == "B"
    assert destoner_daily_mesh(row, date(2026, 10, 9)) is None
    plan = destoner_plan_meta(
        row, {"RES-DESTON-01": {"ctc": "50.0", "mesh": "C", "by": "mgr"}}, date(2026, 10, 8)
    )
    assert plan["assigned_ctc"] == "50.0"
    assert plan["assigned_mesh"] == "C"
    catalog = normalize_mesh_grade_map({})
    assert resolve_mesh_code(catalog, "mesh configuration a") == "A"
    assert resolve_mesh_code(catalog, None) is None


def test_moisture_gate():
    assert moisture_requires_drying(20) is False
    assert moisture_requires_drying(20.01) is True
    assert moisture_requires_drying(None) is False


def test_empty_catalog_becomes_rms_lab_outward():
    ops = normalized_inbound_operations([])
    assert [row["operation_code"] for row in ops] == ["IN-RMS-BAG", "IN-LAB", "IN-RM-OUT"]
    assert ops[2]["operation_name"] == INITIAL_SCREENING_OUTPUT_LABEL


def test_plan_rms_bags_splits_500_with_remainder():
    weights = [str(w) for w in plan_rms_bag_weights("1200")]
    assert weights == ["500", "500", "200"]
    assert [str(w) for w in plan_rms_bag_weights("1500")] == ["500", "500", "500"]


def test_inbound_flow_is_rms_lab_outward():
    ops = normalized_inbound_operations(
        [
            {
                "operation_code": "IN-LAB",
                "operation_name": "Lab — moisture, dust, AD (approve/deny)",
                "process_step": "SCREENING",
                "operation_sequence": 1,
            },
            {
                "operation_code": "IN-RMS-BAG",
                "operation_name": "RMS inward",
                "process_step": "PACKING",
                "operation_sequence": 2,
            },
            {
                "operation_code": "IN-CRUSHER",
                "operation_name": "Crusher performance",
                "process_step": "CRUSHING",
                "operation_sequence": 3,
            },
            {
                "operation_code": "IN-RM-OUT",
                "operation_name": "RMS Outward — crusher output bags",
                "process_step": "SCREENING",
                "operation_sequence": 4,
            },
        ]
    )
    codes = [row["operation_code"] for row in ops]
    assert codes == ["IN-RMS-BAG", "IN-LAB", "IN-RM-OUT"]
    by_code = {row["operation_code"]: row for row in ops}
    assert by_code["IN-RM-OUT"]["operation_name"] == INITIAL_SCREENING_OUTPUT_LABEL
    assert "IN-REPACK" not in by_code
    assert "IN-CRUSHER" not in by_code


def test_kiln_letters_extend_to_f():
    assert kiln_output_id_prefix("Kiln C", "RES-KILN-03") == "KC"
    assert kiln_output_id_prefix("Kiln F", "RES-KILN-06") == "KF"


def test_kiln_feed_bag_quantity_step_is_retired():
    assert is_kiln_feed_bag_qc_step(
        {"operation_code": "OP-KILN-FEED-QC", "operation_name": "Kiln feed bag quality"}
    )
    assert is_kiln_feed_bag_qc_step(
        {"operation_code": "OP-KILN-FEED", "operation_name": "Kiln Feed Bag Quantity"}
    )
    assert not is_kiln_feed_bag_qc_step(
        {"operation_code": "OP-KILN-FEED", "operation_name": "Kiln feed — load bag & charge weight"}
    )
    kept = without_kiln_feed_bag_qc_operations(
        [
            {"operation_code": "OP-KILN-FEED", "operation_name": "Kiln feed"},
            {"operation_code": "OP-KILN-FEED-QC", "operation_name": "Kiln Feed Bag Quantity"},
        ]
    )
    assert [row["operation_code"] for row in kept] == ["OP-KILN-FEED"]
    params = without_kiln_feed_bag_qc_parameters(
        [
            {"key": "charge_kg", "operation_code": "OP-KILN-FEED"},
            {"key": "kfqc_plus_2_kg", "operation_code": "OP-KILN-FEED-QC"},
        ]
    )
    assert [row["key"] for row in params] == ["charge_kg"]


def test_destoning_quality_stones_routes_back_or_to_screening():
    assert destoning_stones_present("yes") is True
    assert destoning_stones_present("no") is False
    assert destoning_destination_from_stones("yes") == DESTONING_REWORK_DESTINATION
    assert destoning_destination_from_stones("no") == SCREENING_DESTINATION
    assert is_destoning_rework_destination("Destoning")
    assert is_destoning_rework_destination("destone again")
    assert not is_destoning_rework_destination(SCREENING_DESTINATION)
    try:
        destoning_destination_from_stones("")
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass
    dests = normalize_process_rules({"destoning_destinations": [SAD_DESTINATION, INSTOCK_DESTINATION]})[
        "destoning_destinations"
    ]
    assert SAD_DESTINATION not in dests
    assert INSTOCK_DESTINATION not in dests
    assert SCREENING_DESTINATION in dests
    assert DESTONING_REWORK_DESTINATION in dests


def test_post_activation_lists_follow_the_active_work_order():
    from app.services.industry.activated_carbon.post_activation import (
        active_post_work_order,
        rows_for_active_work_order,
    )

    loaded = [{"bag_code": "DS-2", "work_order_code": "WO-AC-2", "created_at": "2026-10-14T02:00:00Z"}]
    waiting = [
        {"bag_code": "DS-1", "work_order_code": "WO-AC-1", "created_at": "2026-10-13T01:00:00Z"},
        {"bag_code": "DS-3", "work_order_code": "WO-AC-2", "created_at": "2026-10-14T03:00:00Z"},
    ]
    outputs = [
        {"bag_code": "SC-1", "work_order_code": "WO-AC-1", "created_at": "2026-10-13T04:00:00Z"},
        {"bag_code": "SC-2", "work_order_code": "WO-AC-2", "created_at": "2026-10-14T05:00:00Z"},
    ]
    assert active_post_work_order(loaded, waiting, outputs) == "WO-AC-2"
    assert [row["bag_code"] for row in rows_for_active_work_order(outputs, "WO-AC-2")] == ["SC-2"]
    assert active_post_work_order([], waiting, outputs) == "WO-AC-1"
    assert active_post_work_order([], [], outputs) == "WO-AC-2"


def test_screening_output_cannot_exceed_current_load():
    from decimal import Decimal

    from app.services.industry.activated_carbon.post_activation import (
        assert_output_within_loaded,
        station_current_output_kg,
        station_loaded_kg,
    )

    station = {
        "loaded_bags": [{"bag_code": "DS-1", "quantity_kg": 500}],
        "output_bags": [
            {"bag_code": "SC-1", "quantity_kg": 200, "input_bag_codes": ["DS-1"]},
        ],
    }
    assert station_loaded_kg(station) == Decimal("500")
    assert station_current_output_kg(station) == Decimal("200")
    from app.services.industry.activated_carbon.post_activation import current_load_output_bags

    station["output_bags"].append(
        {"bag_code": "SC-OLD", "quantity_kg": 900, "input_bag_codes": ["DS-OLD"], "work_order_code": "WO-AC-1"}
    )
    assert [row["bag_code"] for row in current_load_output_bags(station)] == ["SC-1"]
    assert current_load_output_bags({"loaded_bags": [], "output_bags": station["output_bags"]}) == []
    from datetime import date

    from app.services.industry.activated_carbon.post_activation import bags_on_plant_day

    today = date(2026, 10, 14)
    rows = bags_on_plant_day(
        [
            {"bag_code": "DD-1", "created_at": "2026-10-13T01:00:00Z"},
            {"bag_code": "SC-LATE", "created_at": "2026-10-13T20:00:00Z"},
            {"bag_code": "DD-2", "created_at": "2026-10-14T01:00:00Z"},
        ],
        tz_name="Asia/Kolkata",
        today=today,
    )
    assert [row["bag_code"] for row in rows] == ["SC-LATE", "DD-2"]
    assert_output_within_loaded(station, Decimal("300"), "Screening")
    try:
        assert_output_within_loaded(station, Decimal("300.1"), "Screening")
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass
    empty = {"loaded_bags": [], "output_bags": []}
    try:
        assert_output_within_loaded(empty, Decimal("1"), "Screening")
        raise AssertionError("expected ValidationError")
    except ValidationError:
        pass


def test_quality_destination_routes_screening_bag_to_dedusting():
    from app.services.industry.activated_carbon.post_activation import (
        _busy_bag_codes,
        _normalize_destination_label,
        _routed_bags_for_process,
    )

    assert _normalize_destination_label("De-Dusting") == "dedusting"
    assert _normalize_destination_label("De-Magnetize") == "demagnetisation"
    stations = {
        "screening": {
            "loaded_bags": [{"bag_code": "DS_1", "quantity_kg": 500}],
            "output_bags": [
                {
                    "bag_code": "SC_1",
                    "quantity_kg": 200,
                    "input_bag_codes": ["DS_1"],
                    "quality_qc": {
                        "saved_at": "2026-10-10T00:00:00+00:00",
                        "values": {"post_qc_destination": "De-Dusting"},
                    },
                }
            ],
            "load_events": [],
        },
        "dedusting": {"loaded_bags": [], "output_bags": [], "load_events": []},
    }
    busy = _busy_bag_codes(stations, {"DS_1": "screening"})
    assert "SC_1" not in busy
    routed = _routed_bags_for_process(stations, "dedusting", busy)
    assert [row["bag_code"] for row in routed] == ["SC_1"]


def test_screening_mesh_is_required_before_load():
    from app.core.exceptions import ValidationError
    from app.services.industry.activated_carbon.post_activation import screening_mesh_for_load

    assert screening_mesh_for_load({}, "A") == "A"
    assert screening_mesh_for_load({"selected_mesh": "B"}, "b") == "B"
    try:
        screening_mesh_for_load({}, "")
    except ValidationError as exc:
        assert "before loading" in str(exc)
    else:
        raise AssertionError("empty mesh should be rejected")
    try:
        screening_mesh_for_load({"selected_mesh": "A"}, "B")
    except ValidationError as exc:
        assert "already on mesh A" in str(exc)
    else:
        raise AssertionError("a second mesh should be rejected while bags are loaded")


def test_screening_grade_must_match_selected_mesh():
    from app.services.industry.activated_carbon.mesh_grade import normalize_mesh_grade_map
    from app.services.industry.activated_carbon.post_activation import _grade_on_mesh

    catalog = normalize_mesh_grade_map({})
    grades_a = next(row["grades"] for row in catalog["configurations"] if row["code"] == "A")
    assert _grade_on_mesh("+3", grades_a)
    assert _grade_on_mesh("3/4", grades_a)
    assert not _grade_on_mesh("12x30", grades_a)
