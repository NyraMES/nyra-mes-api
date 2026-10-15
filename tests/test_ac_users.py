import pytest

from app.core.ac_privileges import (
    assert_can_complete_inbound_step,
    assert_quality_records_lab,
    assert_rms_engineer_records_bags,
    assert_rms_engineer_records_outward,
    assert_supervisor_raises_debit_note,
)
from app.core.auth import (
    MES_ADMIN,
    MES_MANAGER,
    MES_PLANNER,
    MES_QUALITY,
    MES_RMS,
    MES_SUPER_ADMIN,
    UserContext,
)
from app.core.exceptions import ForbiddenError, ValidationError
from app.services.industry.activated_carbon.users import (
    ADMIN_ASSIGNABLE_ROLES,
    assert_actor_may_assign_role,
    assignable_roles_for_actor,
    login_suffix_for_tenant,
    normalize_login_username,
)


def _user(*groups: str) -> UserContext:
    return UserContext(sub="1", username="u", groups=list(groups))


def test_bag_generation_is_the_rms_engineer():
    assert_rms_engineer_records_bags(_user(MES_RMS))
    assert_rms_engineer_records_bags(_user(MES_SUPER_ADMIN))
    with pytest.raises(ForbiddenError):
        assert_rms_engineer_records_bags(_user(MES_MANAGER))
    with pytest.raises(ForbiddenError):
        assert_rms_engineer_records_bags(_user(MES_ADMIN))


def test_raw_material_lab_is_quality_only():
    quality = _user(MES_QUALITY)
    rms = _user(MES_RMS)
    assert_quality_records_lab(quality)
    assert_can_complete_inbound_step(quality, "IN-LAB")
    with pytest.raises(ForbiddenError):
        assert_quality_records_lab(rms)
    with pytest.raises(ForbiddenError):
        assert_can_complete_inbound_step(rms, "IN-LAB")
    with pytest.raises(ForbiddenError):
        assert_can_complete_inbound_step(_user(MES_MANAGER), "IN-LAB")
    with pytest.raises(ForbiddenError):
        assert_can_complete_inbound_step(quality, "IN-RM-OUT")
    assert_can_complete_inbound_step(rms, "IN-RM-OUT")
    assert_rms_engineer_records_outward(rms)
    with pytest.raises(ForbiddenError):
        assert_rms_engineer_records_outward(_user(MES_MANAGER))
    with pytest.raises(ForbiddenError):
        assert_can_complete_inbound_step(_user(MES_MANAGER), "IN-RM-OUT")


def test_debit_note_is_raised_by_the_supervisor():
    assert_supervisor_raises_debit_note(_user(MES_MANAGER))
    assert_supervisor_raises_debit_note(_user(MES_PLANNER))
    assert_supervisor_raises_debit_note(_user(MES_ADMIN))
    with pytest.raises(ForbiddenError):
        assert_supervisor_raises_debit_note(_user(MES_QUALITY))
    with pytest.raises(ForbiddenError):
        assert_supervisor_raises_debit_note(_user(MES_RMS))


def test_admin_cannot_assign_super_admin():
    with pytest.raises(ValidationError):
        assert_actor_may_assign_role(_user(MES_ADMIN), MES_SUPER_ADMIN)


def test_super_admin_cannot_assign_super_admin_from_users_screen():
    with pytest.raises(ValidationError):
        assert_actor_may_assign_role(_user(MES_SUPER_ADMIN), MES_SUPER_ADMIN)


def test_admin_can_assign_plant_roles():
    actor = _user(MES_ADMIN)
    for role in ADMIN_ASSIGNABLE_ROLES:
        assert assert_actor_may_assign_role(actor, role) == role


def test_admin_cannot_assign_demo():
    with pytest.raises(ValidationError):
        assert_actor_may_assign_role(_user(MES_ADMIN), "MES_Demo")


def test_planner_not_in_users_screen_roles():
    admin_codes = {row["role_code"] for row in assignable_roles_for_actor(_user(MES_ADMIN))}
    super_codes = {row["role_code"] for row in assignable_roles_for_actor(_user(MES_SUPER_ADMIN))}
    assert MES_SUPER_ADMIN not in admin_codes
    assert MES_SUPER_ADMIN not in super_codes
    assert MES_PLANNER not in admin_codes
    assert MES_RMS in admin_codes
    assert "MES_Security" in admin_codes
    assert "MES_Demo" not in admin_codes


def test_nyraservices_login_uses_grcarbons_suffix():
    assert normalize_login_username("nyraservices", "GR_CARBONS") == "nyraservices@grcarbons"


def test_normalize_login_appends_suffix():
    assert normalize_login_username("ramesh", "GR_CARBONS") == "ramesh@grcarbons"
    assert normalize_login_username("Ramesh@grcarbons", "GR_CARBONS") == "ramesh@grcarbons"


def test_normalize_login_rejects_email_domain():
    with pytest.raises(ValidationError):
        normalize_login_username("ramesh@grcarbons.com", "GR_CARBONS")
    with pytest.raises(ValidationError):
        normalize_login_username("ramesh@gmail.com", "GR_CARBONS")
    with pytest.raises(ValidationError):
        normalize_login_username("ramesh@grgarbons", "GR_CARBONS")
