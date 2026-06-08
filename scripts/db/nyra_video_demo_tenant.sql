-- =============================================================================
-- Nyra Video Demo — isolated tenant for client demo / AI video tools
-- =============================================================================
-- Safe to run multiple times (fixed UUIDs + ON CONFLICT DO NOTHING).
-- Does NOT touch AUTO_OEM_DEMO or any other tenant.
--
-- Run in DBeaver (connected to nyra_mes_core) OR:
--   python scripts/seed_video_demo.py --install-tenant
-- =============================================================================

BEGIN;

-- Reuse the Automobile OEM industry template from bootstrap
-- (must exist — run nyra_mes_core_setup.sql first if missing)

INSERT INTO core.tenant (
    tenant_id, tenant_code, tenant_name, industry_template_id, timezone, metadata
) VALUES (
    'b2000000-0000-4000-8000-000000000002',
    'NYRA_VIDEO_DEMO',
    'Nyra Video Demo (Prospect Safe)',
    'a1000000-0000-4000-8000-000000000001',
    'Asia/Kolkata',
    '{"demo": true, "purpose": "client_video", "watermark": "Nyra Demo — Confidential"}'::jsonb
) ON CONFLICT (tenant_code) DO NOTHING;

-- Demo viewer — map cognito_sub after Cognito provisioning (see provision_demo_cognito_user.ps1)
INSERT INTO core.app_user (
    user_id, email, display_name, metadata
) VALUES (
    'c3000000-0000-4000-8000-000000000002',
    'demo-viewer@nyra-demo.local',
    'Nyra Demo Viewer',
    '{"purpose": "video_demo", "note": "Assign cognito_sub when user is created in Cognito"}'::jsonb
) ON CONFLICT (email) DO NOTHING;

INSERT INTO core.user_tenant_access (
    access_id, user_id, tenant_id, role_code, is_default
) VALUES (
    'd4000000-0000-4000-8000-000000000002',
    'c3000000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000002',
    'MES_Planner',
    TRUE
) ON CONFLICT (user_id, tenant_id) DO NOTHING;

-- Customer (matches video script)
INSERT INTO mst.customer (
    customer_id, tenant_id, customer_code, customer_name, metadata
) VALUES (
    'e5000000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000002',
    'CUST-APEX-001',
    'Apex Automotive',
    '{"segment": "OEM", "demo": true}'::jsonb
) ON CONFLICT DO NOTHING;

-- Product — brake pad assembly (video script)
INSERT INTO mst.product (
    product_id, tenant_id, product_code, product_name, product_type, uom, metadata
) VALUES (
    'f6000000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000002',
    'BRK-PAD-450',
    'Brake Pad Assembly',
    'ASSEMBLY',
    'EA',
    '{"demo": true, "weight_kg": 2.1}'::jsonb
) ON CONFLICT DO NOTHING;

-- Resources
INSERT INTO mst.resource (
    resource_id, tenant_id, resource_code, resource_name, resource_type, status, metadata
) VALUES
(
    '21000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000002',
    'RES-MOULD-L01',
    'Moulding Line 1',
    'MACHINE',
    'ACTIVE',
    '{"line": "Moulding"}'::jsonb
),
(
    '21000000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000002',
    'RES-POUR-L01',
    'Pouring Line 1',
    'MACHINE',
    'ACTIVE',
    '{"line": "Pouring"}'::jsonb
),
(
    '21000000-0000-4000-8000-000000000003',
    'b2000000-0000-4000-8000-000000000002',
    'RES-FETT-ST01',
    'Fettling Station 1',
    'WORKCELL',
    'ACTIVE',
    '{"line": "Fettling"}'::jsonb
),
(
    '21000000-0000-4000-8000-000000000004',
    'b2000000-0000-4000-8000-000000000002',
    'RES-OP-CAST-01',
    'Casting Operator Pool',
    'LABOR',
    'ACTIVE',
    '{"shift": "A", "operators": 2, "capacity": 2}'::jsonb
) ON CONFLICT DO NOTHING;

-- Equipment
INSERT INTO mst.equipment (
    equipment_id, tenant_id, equipment_code, equipment_name, resource_id, equipment_type, status, metadata
) VALUES
(
    '21100000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000002',
    'EQ-MOULD-L01',
    'DISA Moulding Machine L1',
    '21000000-0000-4000-8000-000000000001',
    'MOULDING_MACHINE',
    'ACTIVE',
    '{"manufacturer": "DISA", "demo_label": "M-CNC-03"}'::jsonb
),
(
    '21100000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000002',
    'EQ-POUR-L01',
    'Induction Furnace Pour L1',
    '21000000-0000-4000-8000-000000000002',
    'FURNACE',
    'ACTIVE',
    '{"capacity_kg": 500}'::jsonb
) ON CONFLICT DO NOTHING;

-- Routing
INSERT INTO mst.routing (
    routing_id, tenant_id, routing_code, product_id, routing_version, process_family, is_active, metadata
) VALUES (
    '21200000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000002',
    'ROUTE-BRK-PAD-V1',
    'f6000000-0000-4000-8000-000000000002',
    '1',
    'Casting',
    TRUE,
    '{"template": "AUTOMOBILE_OEM", "demo": true}'::jsonb
) ON CONFLICT DO NOTHING;

INSERT INTO mst.routing_operation (
    routing_operation_id, tenant_id, routing_id, operation_code,
    operation_sequence, operation_name, standard_cycle_min, metadata
) VALUES
(
    '21300000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000002',
    '21200000-0000-4000-8000-000000000001',
    'OP-MOULD-001',
    10,
    'Moulding',
    30.0000,
    '{"process_type": "Casting"}'::jsonb
),
(
    '21300000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000002',
    '21200000-0000-4000-8000-000000000001',
    'OP-POUR-001',
    20,
    'Pouring',
    25.0000,
    '{"process_type": "Casting"}'::jsonb
),
(
    '21300000-0000-4000-8000-000000000003',
    'b2000000-0000-4000-8000-000000000002',
    '21200000-0000-4000-8000-000000000001',
    'OP-FETT-001',
    30,
    'Fettling',
    15.0000,
    '{"process_type": "Finishing"}'::jsonb
) ON CONFLICT DO NOTHING;

INSERT INTO mst.operation_resource_requirement (
    requirement_id, tenant_id, routing_operation_id, resource_id,
    requirement_type, quantity, uom, metadata
) VALUES
(
    '21400000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000002',
    '21300000-0000-4000-8000-000000000001',
    '21000000-0000-4000-8000-000000000001',
    'PRIMARY',
    1,
    'EA',
    '{}'::jsonb
),
(
    '21400000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000002',
    '21300000-0000-4000-8000-000000000001',
    '21000000-0000-4000-8000-000000000004',
    'LABOR',
    2,
    'EA',
    '{"operators": 2}'::jsonb
),
(
    '21400000-0000-4000-8000-000000000003',
    'b2000000-0000-4000-8000-000000000002',
    '21300000-0000-4000-8000-000000000002',
    '21000000-0000-4000-8000-000000000002',
    'PRIMARY',
    1,
    'EA',
    '{}'::jsonb
),
(
    '21400000-0000-4000-8000-000000000004',
    'b2000000-0000-4000-8000-000000000002',
    '21300000-0000-4000-8000-000000000003',
    '21000000-0000-4000-8000-000000000003',
    'PRIMARY',
    1,
    'EA',
    '{}'::jsonb
) ON CONFLICT DO NOTHING;

COMMIT;

-- Verify:
-- SELECT tenant_code FROM core.tenant WHERE tenant_code = 'NYRA_VIDEO_DEMO';
-- SELECT customer_code, customer_name FROM mst.customer
--   WHERE tenant_id = 'b2000000-0000-4000-8000-000000000002';
