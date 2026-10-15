from app.services.industry.activated_carbon.plant_equipment import (
    REFERENCE_RESIDENCE_MIN,
    designed_monthly_kg_for_residence,
    residence_minutes_for,
)


def test_designed_kg_scales_with_residence():
    assert REFERENCE_RESIDENCE_MIN == 60
    assert designed_monthly_kg_for_residence(15000, None) == 15000
    assert designed_monthly_kg_for_residence(15000, 60) == 15000
    assert designed_monthly_kg_for_residence(15000, 45) == 20000
    assert designed_monthly_kg_for_residence(15000, 90) == 10000
    assert designed_monthly_kg_for_residence(15000, 0) == 15000
    assert designed_monthly_kg_for_residence(None, None) == 15000


def test_residence_minutes_for_plan():
    plan = {
        "RES-KILN-01": {"parameters": {"residence_time_min": 48, "zone1_temp_c": 800}},
        "RES-KILN-02": {"parameters": {}},
    }
    assert residence_minutes_for(plan, "RES-KILN-01") == 48
    assert residence_minutes_for(plan, "RES-KILN-02") is None
    assert residence_minutes_for(plan, "RES-KILN-03") is None
