-- =============================================================================
-- Activated Carbon demo — master data for local validation
-- =============================================================================
-- Prerequisites: migration 003 applied (tenant SAM_CARBONS_DEMO + workspace exist)
-- Safe to re-run (ON CONFLICT DO NOTHING).
-- =============================================================================

BEGIN;

-- Tenant / workspace IDs from migration 003
-- tenant  : b2000000-0000-4000-8000-000000000003  SAM_CARBONS_DEMO
-- workspace: e7000000-0000-4000-8000-000000000001 SAM_CARBONS_DEMO_WS

INSERT INTO mst.customer (
    customer_id, tenant_id, workspace_id, customer_code, customer_name, metadata
) VALUES (
    'c5000000-0000-4000-8000-000000000003',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'CUST-AC-001',
    'Demo Customer',
    '{"segment": "Internal", "industry": "ACTIVATED_CARBON"}'::jsonb
) ON CONFLICT DO NOTHING;

INSERT INTO mst.product (
    product_id, tenant_id, workspace_id, product_code, product_name, product_type, uom, metadata
) VALUES
(
    'a6000000-0000-4000-8000-000000000301',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RAW-COCO-SHELL',
    'Coconut Shell (Raw)',
    'RAW_MATERIAL',
    'KG',
    '{"moisture_pct_max": 12, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'a6000000-0000-4000-8000-000000000302',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'AC-GRAN-8x30',
    'Granular Activated Carbon 8x30',
    'FINISHED',
    'KG',
    '{"mesh": "8x30", "iodine_target_mg_g": 950, "industry": "ACTIVATED_CARBON"}'::jsonb
)
ON CONFLICT DO NOTHING;

INSERT INTO mst.resource (
    resource_id, tenant_id, workspace_id, resource_code, resource_name, resource_type, metadata
) VALUES
(
    '31000000-0000-4000-8000-000000000301',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RES-KILN-01',
    'Activation Kiln 01',
    'MACHINE',
    '{"capacity_mt": 5, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000302',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RES-SCREEN-01',
    'Vibrating Screen Line 1',
    'MACHINE',
    '{"mesh": "8x30", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000303',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RES-LAB-QC',
    'Quality Lab Team',
    'LABOR',
    '{"shift": "A", "operators": 2, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000304',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RES-LAB-AC-01',
    'Activation Shift Crew',
    'LABOR',
    '{"shift": "A", "operators": 4, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000305',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RES-TOOL-CHARGER',
    'Kiln Charging Hopper',
    'TOOL',
    '{"process_step": "PYROLYSIS", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000306',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RES-TOOL-STEAM',
    'Steam Injection Lance',
    'TOOL',
    '{"process_step": "ACTIVATION", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000307',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RES-TOOL-SIEVE-8x30',
    '8x30 Classification Sieve Set',
    'TOOL',
    '{"mesh": "8x30", "process_step": "SCREENING", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000308',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RES-TOOL-LAB-KIT',
    'Iodine & Moisture Test Kit',
    'TOOL',
    '{"process_step": "QC", "industry": "ACTIVATED_CARBON"}'::jsonb
)
ON CONFLICT DO NOTHING;

INSERT INTO mst.equipment (
    equipment_id, tenant_id, workspace_id, equipment_code, equipment_name, resource_id, equipment_type, metadata
) VALUES
(
    '32000000-0000-4000-8000-000000000301',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'EQ-KILN-01',
    'Rotary Activation Kiln 01',
    '31000000-0000-4000-8000-000000000301',
    'KILN',
    '{"max_temp_c": 950, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '32000000-0000-4000-8000-000000000302',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'EQ-SCREEN-01',
    'Vibrating Screen 01',
    '31000000-0000-4000-8000-000000000302',
    'SCREEN',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
)
ON CONFLICT DO NOTHING;

INSERT INTO mst.routing (
    routing_id, tenant_id, workspace_id, routing_code, product_id, routing_version, process_family, metadata
) VALUES (
    '33000000-0000-4000-8000-000000000301',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    'RT-AC-8x30-V1',
    'a6000000-0000-4000-8000-000000000302',
    '1',
    'Activation',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
) ON CONFLICT DO NOTHING;

INSERT INTO mst.routing_operation (
    routing_operation_id, tenant_id, workspace_id, routing_id, operation_code, operation_sequence, operation_name, standard_cycle_min, metadata
) VALUES
(
    '34000000-0000-4000-8000-000000000301',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    '33000000-0000-4000-8000-000000000301',
    'OP-PYROLYSIS',
    1,
    'Pyrolysis / Carbonization',
    360.0,
    '{"process_step": "PYROLYSIS", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '34000000-0000-4000-8000-000000000302',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    '33000000-0000-4000-8000-000000000301',
    'OP-ACTIVATION',
    2,
    'Steam Activation',
    480.0,
    '{"process_step": "ACTIVATION", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '34000000-0000-4000-8000-000000000303',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    '33000000-0000-4000-8000-000000000301',
    'OP-SCREENING',
    3,
    'Screening & Classification',
    120.0,
    '{"process_step": "SCREENING", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '34000000-0000-4000-8000-000000000304',
    'b2000000-0000-4000-8000-000000000003',
    'e7000000-0000-4000-8000-000000000001',
    '33000000-0000-4000-8000-000000000301',
    'OP-QC',
    4,
    'Quality Testing',
    60.0,
    '{"process_step": "QC", "industry": "ACTIVATED_CARBON"}'::jsonb
)
ON CONFLICT DO NOTHING;

INSERT INTO mst.operation_resource_requirement (
    requirement_id, tenant_id, routing_operation_id, resource_id,
    requirement_type, quantity, uom, metadata
) VALUES
(
    '35000000-0000-4000-8000-000000000301',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000301',
    '31000000-0000-4000-8000-000000000301',
    'PRIMARY', 1, 'EA', '{"process_step": "PYROLYSIS"}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000302',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000301',
    '31000000-0000-4000-8000-000000000304',
    'LABOR', 2, 'EA', '{"operators": 2}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000303',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000301',
    '31000000-0000-4000-8000-000000000305',
    'TOOL', 1, 'EA', '{}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000311',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000302',
    '31000000-0000-4000-8000-000000000301',
    'PRIMARY', 1, 'EA', '{"process_step": "ACTIVATION"}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000312',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000302',
    '31000000-0000-4000-8000-000000000304',
    'LABOR', 2, 'EA', '{"operators": 2}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000313',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000302',
    '31000000-0000-4000-8000-000000000306',
    'TOOL', 1, 'EA', '{}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000321',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000303',
    '31000000-0000-4000-8000-000000000302',
    'PRIMARY', 1, 'EA', '{"process_step": "SCREENING"}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000322',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000303',
    '31000000-0000-4000-8000-000000000304',
    'LABOR', 1, 'EA', '{"operators": 1}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000323',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000303',
    '31000000-0000-4000-8000-000000000307',
    'TOOL', 1, 'EA', '{}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000331',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000304',
    '31000000-0000-4000-8000-000000000303',
    'LABOR', 1, 'EA', '{"operators": 1}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000332',
    'b2000000-0000-4000-8000-000000000003',
    '34000000-0000-4000-8000-000000000304',
    '31000000-0000-4000-8000-000000000308',
    'TOOL', 1, 'EA', '{}'::jsonb
)
ON CONFLICT DO NOTHING;

COMMIT;
