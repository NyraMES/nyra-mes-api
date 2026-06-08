"""Integration tests for nyra_mes_core /api/* routes (live RDS).

Skipped when nyra_mes_core is disabled or unreachable.
Set MES_CORE_DB_PASSWORD in .env before running.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

# Must be set before app import (conftest already sets AUTH_ENABLED=false).
os.environ.setdefault("MES_CORE_ENABLED", "true")

from app.core.config import settings
from app.db.mes_core_database import get_mes_core_engine


def mes_core_db_reachable() -> bool:
    if not settings.mes_core_enabled or not settings.mes_core_db_password:
        return False
    try:
        engine = get_mes_core_engine()
        if engine is None:
            return False
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
    except Exception:
        return False


requires_mes_core = pytest.mark.skipif(
    not mes_core_db_reachable(),
    reason=(
        "nyra_mes_core unreachable — set MES_CORE_ENABLED=true and "
        "MES_CORE_DB_PASSWORD in .env"
    ),
)


@requires_mes_core
def test_api_context(client):
    resp = client.get("/api/context")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_code"] == settings.default_tenant_code
    assert body["tenant_name"]
    assert body["industry_template_code"]
    assert body["industry_template_name"]
    assert body["tenant_id"]
    assert "enabled_capabilities" in body
    assert isinstance(body["enabled_capabilities"], list)


@requires_mes_core
def test_api_context_with_sam_carbons_headers(client):
    resp = client.get(
        "/api/context",
        headers={
            "X-Tenant-Code": "SAM_CARBONS_DEMO",
            "X-Workspace-Code": "SAM_CARBONS_DEMO_WS",
        },
    )
    if resp.status_code == 404:
        pytest.skip("SAM_CARBONS_DEMO tenant not seeded — run migration 003")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_code"] == "SAM_CARBONS_DEMO"
    assert body["workspace_code"] == "SAM_CARBONS_DEMO_WS"
    assert body["industry_template_code"] == "ACTIVATED_CARBON"


@requires_mes_core
def test_api_products_list(client):
    resp = client.get("/api/products")
    assert resp.status_code == 200
    products = resp.json()
    assert isinstance(products, list)
    assert len(products) >= 1
    codes = {p["product_code"] for p in products}
    assert "PART-BRK-DISC-001" in codes


@requires_mes_core
def test_api_customers_list(client):
    resp = client.get("/api/customers")
    assert resp.status_code == 200
    customers = resp.json()
    assert any(c["customer_code"] == "CUST-OEM-001" for c in customers)


@requires_mes_core
def test_api_routings_include_operations(client):
    resp = client.get("/api/routings")
    assert resp.status_code == 200
    routings = resp.json()
    assert len(routings) >= 1
    route = next(r for r in routings if r["routing_code"] == "ROUTE-BRK-DISC-V1")
    assert len(route["operations"]) == 3
    op_names = {o["operation_name"] for o in route["operations"]}
    assert op_names == {"Moulding", "Pouring", "Fettling"}


@requires_mes_core
def test_ac_dashboard_summary(client):
    headers = {
        "X-Tenant-Code": "SAM_CARBONS_DEMO",
        "X-Workspace-Code": "SAM_CARBONS_DEMO_WS",
    }
    resp = client.get("/api/activated-carbon/dashboard", headers=headers)
    if resp.status_code == 404:
        pytest.skip("SAM_CARBONS_DEMO not seeded — run seed_sam_carbons_demo.py")
    assert resp.status_code == 200
    body = resp.json()
    assert "raw_material" in body
    assert "kilns" in body
    assert len(body["process_steps"]) >= 1
    paths = {step["path"] for step in body["process_steps"]}
    assert "routing" in paths
    assert "feasibility" in paths
    assert "execution" in paths
    assert isinstance(body.get("lot_lines"), list)
    assert "yield_summary" in body


@requires_mes_core
def test_ac_masters_dropdowns(client):
    headers = {
        "X-Tenant-Code": "SAM_CARBONS_DEMO",
        "X-Workspace-Code": "SAM_CARBONS_DEMO_WS",
    }
    resp = client.get("/api/activated-carbon/masters", headers=headers)
    if resp.status_code == 404:
        pytest.skip("SAM_CARBONS_DEMO not seeded — run seed_sam_carbons_demo.py")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["customers"]) >= 1
    assert len(body["raw_products"]) >= 1
    assert len(body["production_orders"]) >= 1
    assert len(body["production_lots"]) >= 1
    assert len(body["kilns"]) >= 1


@requires_mes_core
def test_ac_routing_plan(client):
    headers = {
        "X-Tenant-Code": "SAM_CARBONS_DEMO",
        "X-Workspace-Code": "SAM_CARBONS_DEMO_WS",
    }
    resp = client.get(
        "/api/activated-carbon/lots/LOT-AC-001/routing-plan", headers=headers
    )
    if resp.status_code == 404:
        pytest.skip("SAM_CARBONS_DEMO not seeded — run seed_sam_carbons_demo.py")
    assert resp.status_code == 200
    body = resp.json()
    assert body["routing_id"] == "RT-AC-8x30-V1"
    assert len(body["operations"]) >= 4


@requires_mes_core
def test_api_context_auto_oem_demo(client):
    resp = client.get(
        "/api/context",
        headers={"X-Tenant-Code": "AUTO_OEM_DEMO"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_code"] == "AUTO_OEM_DEMO"
    assert body["industry_template_code"] == "AUTOMOBILE_OEM"
    assert body["module_code"]
    assert body["landing_page"]
    assert isinstance(body["enabled_capabilities"], list)


@requires_mes_core
def test_api_context_sam_carbons_workspace(client):
    resp = client.get(
        "/api/context",
        headers={
            "X-Tenant-Code": "SAM_CARBONS",
            "X-Workspace-Code": "SAM_CARBONS_ACTIVATED_CARBON",
        },
    )
    if resp.status_code == 404:
        pytest.skip("SAM_CARBONS tenant not seeded — run migration 004")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_code"] == "SAM_CARBONS"
    assert body["workspace_code"] == "SAM_CARBONS_ACTIVATED_CARBON"
    assert body["industry_template_code"] == "ACTIVATED_CARBON"
    assert body["module_code"]
    assert body["landing_page"]
    assert isinstance(body["enabled_capabilities"], list)


@requires_mes_core
def test_routing_copy_from_template_and_customize(client):
    headers = {
        "X-Tenant-Code": "SAM_CARBONS",
        "X-Workspace-Code": "SAM_CARBONS_ACTIVATED_CARBON",
    }
    ctx = client.get("/api/context", headers=headers)
    if ctx.status_code == 404:
        pytest.skip("SAM_CARBONS tenant not seeded — run migration 004")

    copy_resp = client.post(
        "/api/routings/copy-from-template",
        headers=headers,
        json={"template_routing_code": "AC_STANDARD_PROCESS"},
    )
    if copy_resp.status_code == 404:
        pytest.skip("AC_STANDARD_PROCESS template not seeded — run migration 004")
    assert copy_resp.status_code in (200, 201)
    copied = copy_resp.json()
    assert copied["is_template_copy"] is True
    assert copied["is_template_route"] is False
    assert copied["source_template_code"] == "AC_STANDARD_PROCESS"
    assert len(copied["operations"]) >= 1

    active_resp = client.get("/api/routings/active", headers=headers)
    assert active_resp.status_code == 200
    assert active_resp.json()["routing_id"] == copied["routing_id"]

    add_resp = client.post(
        "/api/routing-operations",
        headers=headers,
        json={
            "operation_code": "POST_SCREENING_INSPECTION",
            "operation_name": "Post Screening Inspection",
            "operation_seq": 75,
            "operation_type": "INSPECTION",
            "is_quality_gate": True,
        },
    )
    assert add_resp.status_code == 201
    op = add_resp.json()
    assert op["operation_code"] == "POST_SCREENING_INSPECTION"
    assert op["operation_seq"] == 75
    assert op["is_quality_gate"] is True

    param_resp = client.post(
        f"/api/routing-operations/{op['routing_operation_id']}/parameters",
        headers=headers,
        json={
            "parameter_code": "VISUAL_DUST_PCT",
            "parameter_name": "Visual Dust %",
            "data_type": "DECIMAL",
            "unit": "%",
            "is_mandatory": True,
            "display_order": 10,
        },
    )
    assert param_resp.status_code == 201

    params_resp = client.get(
        f"/api/routing-operations/{op['routing_operation_id']}/parameters",
        headers=headers,
    )
    assert params_resp.status_code == 200
    assert len(params_resp.json()) >= 1


@requires_mes_core
def test_ac_dispatch_records(client):
    headers = {
        "X-Tenant-Code": "SAM_CARBONS",
        "X-Workspace-Code": "SAM_CARBONS_ACTIVATED_CARBON",
    }
    ctx = client.get("/api/context", headers=headers)
    if ctx.status_code == 404:
        pytest.skip("SAM_CARBONS tenant not seeded — run migration 004")

    list_resp = client.get("/api/activated-carbon/dispatch", headers=headers)
    assert list_resp.status_code == 200
    assert isinstance(list_resp.json(), list)

    create_resp = client.post(
        "/api/activated-carbon/dispatch",
        headers=headers,
        json={
            "finished_goods_lot_no": "FG-TEST-001",
            "grade": "8x30",
            "bag_count": 10,
            "total_weight": 500,
            "status": "PLANNED",
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    dispatch_id = created["id"]

    update_resp = client.put(
        f"/api/activated-carbon/dispatch/{dispatch_id}",
        headers=headers,
        json={"status": "DISPATCHED", "vehicle_no": "TN-01-TEST"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "DISPATCHED"
    assert update_resp.json()["vehicle_no"] == "TN-01-TEST"


@requires_mes_core
def test_api_kg_triples(client):
    resp = client.get("/api/kg/triples")
    assert resp.status_code == 200
    triples = resp.json()
    assert len(triples) >= 1
