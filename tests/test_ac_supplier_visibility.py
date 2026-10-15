"""Supplier name and code stay with the supervisor, plant admin, and security."""

from decimal import Decimal
from uuid import uuid4

from app.core.ac_privileges import user_can_see_supplier, without_supplier_identity
from app.core.auth import (
    MES_ACTIVATION,
    MES_ADMIN,
    MES_MANAGER,
    MES_OPERATOR,
    MES_PLANNER,
    MES_POST_ACTIVATION,
    MES_QUALITY,
    MES_RMS,
    MES_SECURITY,
    MES_VIEWER,
    UserContext,
)
from app.schemas.mes_core.schemas import (
    AcDebitNoteOut,
    AcInboundExecutionOut,
    AcMaterialTraceOut,
    AcTraceSupplierShareOut,
    CustomerOrderOut,
)


def _user(groups, username="eng@grcarbons"):
    return UserContext(sub="sub", username=username, groups=list(groups))


def test_only_manager_planner_and_admin_see_supplier():
    assert user_can_see_supplier(_user([MES_MANAGER]))
    assert user_can_see_supplier(_user([MES_PLANNER]))
    assert user_can_see_supplier(_user([MES_ADMIN]))
    assert user_can_see_supplier(_user([MES_SECURITY]))
    assert user_can_see_supplier(_user([], username="nyraservices@grcarbons"))
    for role in (
        MES_RMS,
        MES_ACTIVATION,
        MES_POST_ACTIVATION,
        MES_QUALITY,
        MES_OPERATOR,
        MES_VIEWER,
    ):
        assert user_can_see_supplier(_user([role])) is False


def test_without_supplier_identity_keeps_weights():
    row = AcInboundExecutionOut(
        customer_order_id=uuid4(),
        order_code="ORD-AC-1",
        supplier_id=uuid4(),
        supplier_code="SUP-AC-1",
        supplier_name="Secret Mills",
        debit_note=AcDebitNoteOut(
            supplier_name="Secret Mills",
            supplier_code="SUP-AC-1",
            supplier_weight_kg=Decimal("12"),
            our_weight_kg=Decimal("10"),
        ),
    )
    hidden = without_supplier_identity(row)
    assert hidden.supplier_name is None
    assert hidden.supplier_code is None
    assert hidden.supplier_id is None
    assert hidden.debit_note.supplier_name is None
    assert hidden.debit_note.supplier_code is None
    assert hidden.debit_note.supplier_weight_kg == Decimal("12")
    assert hidden.debit_note.our_weight_kg == Decimal("10")
    order = without_supplier_identity(
        CustomerOrderOut(
            customer_order_id=uuid4(),
            tenant_id=uuid4(),
            order_code="ORD-AC-1",
            status="OPEN",
            supplier_name="Secret Mills",
            supplier_weight_kg=Decimal("12"),
            supplier_value_inr=Decimal("100"),
        )
    )
    assert order.supplier_name is None
    assert order.supplier_value_inr is None
    assert order.supplier_weight_kg == Decimal("12")


def test_material_trace_drops_supplier_list_and_blend_message():
    row = AcMaterialTraceOut(
        query="WO-AC-1",
        query_kind="work_order",
        suppliers=[
            AcTraceSupplierShareOut(supplier_name="Secret Mills", supplier_code="SUP-AC-1", feed_kg=Decimal("1"))
        ],
        message="More than one supplier fed this work order (kiln blend).",
    )
    hidden = without_supplier_identity(row)
    assert hidden.suppliers == []
    assert hidden.message is None
