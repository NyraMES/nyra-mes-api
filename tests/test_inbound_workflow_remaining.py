"""Remaining-after-scrap calculation for inbound crusher workflow."""

from decimal import Decimal

from app.services.industry.activated_carbon.inbound_workflow import (
    MESH_PCT_FIELDS,
    _bags_total_kg,
    _remaining_kg,
    _scrap_total_kg,
    workflow_status_from_meta,
)


def _sample_meta(*, bags_total: str = "1500", scrap: dict | None = None) -> dict:
    scrap = scrap or {
        "status": "COMPLETED",
        "mesh_plus_2_kg": "1",
        "mesh_2_3_kg": "2",
        "mesh_3_4_kg": "3",
        "mesh_4_6_kg": "4",
        "mesh_6_10_kg": "6",
        "mesh_10_12_kg": "10",
        "mesh_12_14_kg": "12",
        "mesh_minus_14_kg": "14",
    }
    return {
        "bag_reconciliation": {"status": "RECONCILED", "total_kg": bags_total},
        "crusher_output": scrap,
    }


def test_scrap_total_sums_mesh_fields():
    crusher = _sample_meta()["crusher_output"]
    assert _scrap_total_kg(crusher) == Decimal("52")


def test_remaining_kg_is_bags_minus_scrap():
    meta = _sample_meta()
    assert _remaining_kg(meta) == Decimal("1448")


def test_bags_total_falls_back_to_weight_to_crusher():
    meta = {
        "weight_to_crusher": {
            "status": "RECONCILED",
            "weight_to_crusher_kg": "1497",
        },
        "crusher_output": _sample_meta()["crusher_output"],
    }
    assert _bags_total_kg(meta) == Decimal("1497")
    assert _remaining_kg(meta) == Decimal("1445")


def test_workflow_status_exposes_remaining_and_scrap_totals():
    status = workflow_status_from_meta(_sample_meta(), Decimal("1497"))
    assert status["crusher_complete"] is True
    assert status["scrap_total_kg"] == Decimal("52")
    assert status["remaining_kg"] == Decimal("1448")


def test_mesh_pct_fields_do_not_change_scrap_kg():
    meta = _sample_meta()
    for field, _label, _code in MESH_PCT_FIELDS:
        meta["crusher_output"][field] = "10"
    assert _scrap_total_kg(meta["crusher_output"]) == Decimal("52")
    assert _remaining_kg(meta) == Decimal("1448")
    assert [code for _f, _l, code in MESH_PCT_FIELDS] == [
        "MESH_PLUS_2_PCT",
        "MESH_2_3_PCT",
        "MESH_3_4_PCT",
        "MESH_4_6_PCT",
        "MESH_6_10_PCT",
        "MESH_10_12_PCT",
        "MESH_12_14_PCT",
        "MESH_MINUS_14_PCT",
    ]
