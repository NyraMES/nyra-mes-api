from decimal import Decimal

from app.services.industry.activated_carbon.material_trace import (
    BagRef,
    DispatchRef,
    FeedEvent,
    InwardRef,
    TraceIndex,
    classify_query,
    list_trace_options,
    resolve_trace,
    _add_bag,
)


def _index() -> TraceIndex:
    index = TraceIndex()
    index.inwards["ORD-AC-1"] = InwardRef(
        order_code="ORD-AC-1",
        supplier_code="SUP-AC-1",
        supplier_name="Coastal Charcoal",
        dc_number="DC-1",
        kg=Decimal("1000"),
        at="2026-10-04T08:00:00+00:00",
        rms_bags=["RI_BAG_1"],
        ro_bags=["RO_1"],
    )
    index.inwards["ORD-AC-2"] = InwardRef(
        order_code="ORD-AC-2",
        supplier_code="SUP-AC-2",
        supplier_name="Hillside Shell",
        dc_number="DC-2",
        kg=Decimal("800"),
        at="2026-10-05T08:00:00+00:00",
        rms_bags=["RI_BAG_2"],
        ro_bags=["RO_2"],
    )
    _add_bag(index, BagRef(bag_code="RI_BAG_1", stage="rms_bag", kg=Decimal("500"), inward_code="ORD-AC-1"))
    _add_bag(index, BagRef(bag_code="RO_1", stage="ro_bag", kg=Decimal("480"), inward_code="ORD-AC-1"))
    _add_bag(index, BagRef(bag_code="RI_BAG_2", stage="rms_bag", kg=Decimal("500"), inward_code="ORD-AC-2"))
    _add_bag(index, BagRef(bag_code="RO_2", stage="ro_bag", kg=Decimal("400"), inward_code="ORD-AC-2"))
    index.feeds.append(
        FeedEvent(
            bag_code="RO_1",
            kg=Decimal("480"),
            work_order_code="WO-AC-9",
            kiln_code="RES-KILN-01",
            inward_code="ORD-AC-1",
            at="2026-10-06T08:00:00+00:00",
        )
    )
    index.feeds.append(
        FeedEvent(
            bag_code="RO_2",
            kg=Decimal("320"),
            work_order_code="WO-AC-9",
            kiln_code="RES-KILN-01",
            inward_code="ORD-AC-2",
            at="2026-10-06T09:00:00+00:00",
        )
    )
    _add_bag(
        index,
        BagRef(
            bag_code="KA_1",
            stage="kiln_output",
            kg=Decimal("700"),
            work_order_code="WO-AC-9",
            input_bag_codes=["RO_1", "RO_2"],
            machine="RES-KILN-01",
        ),
    )
    _add_bag(
        index,
        BagRef(
            bag_code="DS_1",
            stage="destoning",
            kg=Decimal("680"),
            work_order_code="WO-AC-9",
            input_bag_codes=["KA_1"],
            stones="No",
            destination="Screening",
        ),
    )
    _add_bag(
        index,
        BagRef(
            bag_code="SC_1",
            stage="screening",
            kg=Decimal("650"),
            work_order_code="WO-AC-9",
            input_bag_codes=["DS_1"],
            mesh="A",
            grade="+3",
            destination="In Stock",
            prior_work_order_codes=["WO-AC-1"],
        ),
    )
    index.work_orders.add("WO-AC-1")
    index.dispatches["DISP-AC-1"] = DispatchRef(
        dispatch_code="DISP-AC-1",
        work_order_code="WO-AC-9",
        bag_codes=["SC_1"],
        kg=Decimal("650"),
    )
    index.work_orders.add("WO-AC-9")
    index.work_orders.add("WO-AC-EMPTY")
    index.work_orders.add("WO-AC-OLD")
    index.work_order_at["WO-AC-9"] = "2026-10-03T08:00:00+00:00"
    index.work_order_at["WO-AC-EMPTY"] = "2026-10-02T08:00:00+00:00"
    index.work_order_at["WO-AC-OLD"] = "2026-09-12T08:00:00+00:00"
    index.inwards["ORD-AC-OLD"] = InwardRef(
        order_code="ORD-AC-OLD",
        supplier_code="SUP-AC-9",
        supplier_name="Last month",
        at="2026-09-10T08:00:00+00:00",
    )
    return index


def test_classify_query_uses_plant_prefixes():
    assert classify_query("WO-AC-9") == "work_order"
    assert classify_query("ord-ac-1") == "inward"
    assert classify_query("DISP-AC-1") == "dispatch"
    assert classify_query("SC_1") == "bag"


def test_work_order_blend_lists_both_suppliers():
    result = resolve_trace(_index(), "WO-AC-9")
    assert result.found is True
    assert result.blend is True
    names = [row.supplier_name for row in result.suppliers]
    assert names == ["Coastal Charcoal", "Hillside Shell"]
    by_name = {row.supplier_name: row.feed_kg for row in result.suppliers}
    assert by_name["Coastal Charcoal"] == Decimal("480")
    assert by_name["Hillside Shell"] == Decimal("320")
    assert "ORD-AC-1" in result.inward_codes
    assert "ORD-AC-2" in result.inward_codes
    stages = [step.stage for step in result.steps]
    assert "gate" in stages
    assert "kiln_feed" in stages
    assert "dispatch" in stages


def test_bag_walks_back_to_suppliers():
    result = resolve_trace(_index(), "SC_1")
    assert result.found is True
    assert result.bag_code == "SC_1"
    assert result.work_order_code == "WO-AC-9"
    assert {row.supplier_code for row in result.suppliers} == {"SUP-AC-1", "SUP-AC-2"}
    assert any(step.bag_code == "RO_1" for step in result.steps)


def test_inward_lists_every_work_order_used():
    result = resolve_trace(_index(), "ORD-AC-1")
    assert result.found is True
    assert "WO-AC-9" in result.work_order_codes
    assert "WO-AC-1" in result.work_order_codes


def test_inward_maps_one_supplier():
    result = resolve_trace(_index(), "ORD-AC-1")
    assert result.found is True
    assert result.blend is False
    assert result.suppliers[0].supplier_code == "SUP-AC-1"
    assert result.suppliers[0].inward_codes == ["ORD-AC-1"]


def test_dispatch_uses_work_order_supplier_walk():
    result = resolve_trace(_index(), "DISP-AC-1")
    assert result.found is True
    assert result.dispatch_codes == ["DISP-AC-1"]
    assert result.work_order_code == "WO-AC-9"
    assert len(result.suppliers) == 2


def test_empty_work_order_has_no_supplier_yet():
    result = resolve_trace(_index(), "WO-AC-EMPTY")
    assert result.found is True
    assert result.suppliers == []
    assert "No kiln feed yet" in (result.message or "")


def test_unknown_code_is_not_found():
    result = resolve_trace(_index(), "WO-AC-MISSING")
    assert result.found is False
    assert result.suppliers == []


def test_options_are_current_month_only():
    index = _index()
    work_orders = list_trace_options(index, "work_order", "2026-10")
    assert [row.code for row in work_orders.options] == ["WO-AC-9", "WO-AC-EMPTY"]
    assert work_orders.month_label == "Oct 2026"
    inwards = list_trace_options(index, "inward", "2026-10")
    assert [row.code for row in inwards.options] == ["ORD-AC-1", "ORD-AC-2"]
    old = list_trace_options(index, "work_order", "2026-09")
    assert [row.code for row in old.options] == ["WO-AC-OLD"]
