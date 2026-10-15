import pytest

from app.core.exceptions import ValidationError
from app.services.industry.activated_carbon.users import (
    nickname_is_taken,
    nickname_key,
    normalize_nickname,
)


def test_nickname_key_ignores_case_and_extra_spaces():
    assert nickname_key("  Ramesh   K ") == nickname_key("ramesh k")


def test_nickname_must_be_present_and_short():
    assert normalize_nickname("  Ramesh K  ") == "Ramesh K"
    with pytest.raises(ValidationError):
        normalize_nickname("   ")
    with pytest.raises(ValidationError):
        normalize_nickname("x" * 65)


def test_repeated_nickname_is_blocked_in_the_plant():
    names = [("a", "Ramesh"), ("b", "Kumar")]
    assert nickname_is_taken(names, "ramesh")
    assert nickname_is_taken(names, "Ramesh")
    assert not nickname_is_taken(names, "Ramesh", except_user_id="a")
    assert not nickname_is_taken(names, "Ramesh K")
