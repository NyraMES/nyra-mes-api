"""Tests for Activated Carbon sequence-based business codes."""

from app.services.industry.activated_carbon.codes import (
    AC_CODE_SPECS,
    generate_ac_business_code,
    resolve_ac_business_code,
)


def test_ac_code_specs_use_core_sequences():
    assert AC_CODE_SPECS["ac_customer_order"][0] == "core.customer_order_code_seq"
    assert AC_CODE_SPECS["ac_production_lot"][1] == "LOT-AC-"


def test_resolve_ac_uses_provided_code():
    code = resolve_ac_business_code(
        None,
        provided="ORD-AC-9999",
        entity="ac_customer_order",
    )
    assert code == "ORD-AC-9999"


def test_generate_ac_business_code_format(monkeypatch):
    monkeypatch.setattr(
        "app.services.industry.activated_carbon.codes._nextval",
        lambda db, seq: 1002,
    )
    code = generate_ac_business_code(None, "ac_customer_order")
    assert code == "ORD-AC-1002"
