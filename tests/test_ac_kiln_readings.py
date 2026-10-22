from datetime import datetime, timedelta, timezone

import pytest

from app.core.auth import MES_ACTIVATION, MES_POST_ACTIVATION, UserContext
from app.core.exceptions import ValidationError
from app.services.industry.activated_carbon.kiln_readings import (
    approved_slot_keys,
    assert_slot_needs_approval,
    floor_slot,
    missed_slots,
    required_readings,
    resolve_slot,
    slot_key,
)
from app.services.industry.activated_carbon.users import normalize_assigned_roles

KOLKATA = timezone(timedelta(hours=5, minutes=30))


def _at(hour, minute):
    return datetime(2026, 10, 16, hour, minute, tzinfo=KOLKATA)


def test_floor_slot_uses_the_plant_half_hour():
    assert floor_slot(_at(10, 7)) == _at(10, 0)
    assert floor_slot(_at(10, 30)) == _at(10, 30)
    assert floor_slot(_at(10, 59)) == _at(10, 30)


def test_current_window_is_open_and_a_missed_window_is_locked():
    now = _at(11, 10)
    saved = {slot_key(_at(10, 0))}
    assert missed_slots(now, saved) == [_at(10, 30)]
    assert resolve_slot(now, saved, set(), None) == _at(11, 0)
    with pytest.raises(ValueError, match="locked"):
        resolve_slot(now, saved, set(), _at(10, 30))


def test_manager_approval_opens_the_missed_window():
    now = _at(10, 40)
    saved = {slot_key(_at(10, 0))}
    approved = {slot_key(_at(9, 30))}
    assert resolve_slot(now, saved, approved, _at(9, 30)) == _at(9, 30)
    assert slot_key(_at(9, 30)) in approved_slot_keys(
        [{"slot_start": _at(9, 30).astimezone(timezone.utc).isoformat(), "used": False}]
    )


def test_current_window_does_not_need_approval():
    with pytest.raises(ValueError, match="still open"):
        assert_slot_needs_approval(_at(10, 10), set(), _at(10, 5))


def test_reading_requires_every_interval_value():
    with pytest.raises(ValueError, match="T1"):
        required_readings(
            {
                "t2": 1,
                "t3": 1,
                "main_damper": 1,
                "boiler_damper": 1,
                "induced_draft": 1,
                "boiler_pressure": 1,
            }
        )
    values = required_readings(
        {
            "t1": 800,
            "t2": 810,
            "t3": 790,
            "main_damper": 40,
            "boiler_damper": 12,
            "induced_draft": 18,
            "boiler_pressure": 3.5,
        }
    )
    assert values["induced_draft"] == 18


def test_damper_and_induced_draft_are_percentages():
    with pytest.raises(ValueError, match="percentage"):
        required_readings(
            {
                "t1": 800,
                "t2": 810,
                "t3": 790,
                "main_damper": 140,
                "boiler_damper": 12,
                "induced_draft": 18,
                "boiler_pressure": 3.5,
            }
        )


def test_a_person_can_hold_activation_and_post_activation():
    actor = UserContext(sub="1", username="admin@grcarbons", groups=["MES_Admin"])
    roles = normalize_assigned_roles(actor, None, [MES_ACTIVATION, MES_POST_ACTIVATION])
    assert roles == [MES_ACTIVATION, MES_POST_ACTIVATION]
    with pytest.raises(ValidationError):
        normalize_assigned_roles(actor, None, [])


def test_a_first_reading_has_no_locked_history():
    assert missed_slots(_at(10, 10), set()) == []


def test_a_gap_between_saved_readings_stays_locked():
    now = _at(10, 40)
    saved = {slot_key(_at(9, 0)), slot_key(_at(10, 0))}
    assert missed_slots(now, saved) == [_at(9, 30)]
