-- =============================================================================
-- Activated Carbon production tenant — master data for local validation
-- =============================================================================
-- Prerequisites: migration 004 applied (tenant SAM_CARBONS + workspace exist)
-- Safe to re-run (ON CONFLICT DO NOTHING).
-- =============================================================================

BEGIN;

-- tenant  : b2000000-0000-4000-8000-000000000010  SAM_CARBONS
-- workspace: e7000000-0000-4000-8000-000000000010 SAM_CARBONS_ACTIVATED_CARBON

INSERT INTO mst.customer (
    customer_id, tenant_id, workspace_id, customer_code, customer_name, metadata
) VALUES (
    'c5000000-0000-4000-8000-000000000010',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'CUST-AC-001',
    'Demo Customer',
    '{"segment": "Internal", "industry": "ACTIVATED_CARBON"}'::jsonb
) ON CONFLICT DO NOTHING;

INSERT INTO mst.product (
    product_id, tenant_id, workspace_id, product_code, product_name, product_type, uom, metadata
) VALUES
(
    'a6000000-0000-4000-8000-000000000311',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'RAW-COCO-SHELL',
    'Coconut Shell (Raw)',
    'RAW_MATERIAL',
    'KG',
    '{"moisture_pct_max": 12, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'a6000000-0000-4000-8000-000000000312',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
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
    '31000000-0000-4000-8000-000000000311',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'RES-KILN-01',
    'Activation Kiln 01',
    'MACHINE',
    '{"capacity_mt": 5, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000312',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'RES-SCREEN-01',
    'Vibrating Screen Line 1',
    'MACHINE',
    '{"mesh": "8x30", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000313',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'RES-LAB-QC',
    'Quality Lab Team',
    'LABOR',
    '{"shift": "A", "operators": 2, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000314',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'RES-LAB-AC-01',
    'Activation Shift Crew',
    'LABOR',
    '{"shift": "A", "operators": 4, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000315',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'RES-TOOL-CHARGER',
    'Kiln Charging Hopper',
    'TOOL',
    '{"process_step": "PYROLYSIS", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000316',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'RES-TOOL-STEAM',
    'Steam Injection Lance',
    'TOOL',
    '{"process_step": "ACTIVATION", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000317',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'RES-TOOL-SIEVE-8x30',
    '8x30 Classification Sieve Set',
    'TOOL',
    '{"mesh": "8x30", "process_step": "SCREENING", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000318',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
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
    '32000000-0000-4000-8000-000000000311',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'EQ-KILN-01',
    'Rotary Activation Kiln 01',
    '31000000-0000-4000-8000-000000000311',
    'KILN',
    '{"max_temp_c": 950, "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '32000000-0000-4000-8000-000000000312',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'EQ-SCREEN-01',
    'Vibrating Screen 01',
    '31000000-0000-4000-8000-000000000312',
    'SCREEN',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
)
ON CONFLICT DO NOTHING;

-- Workspace finished-product routing (distinct from template AC_STANDARD_PROCESS)
INSERT INTO mst.routing (
    routing_id, tenant_id, workspace_id, routing_code, product_id, routing_version, process_family,
    is_active, is_template_route, is_template_copy, metadata
) VALUES (
    '33000000-0000-4000-8000-000000000311',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    'RT-AC-8x30-V1',
    'a6000000-0000-4000-8000-000000000312',
    '1',
    'Activation',
    TRUE,
    FALSE,
    FALSE,
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
) ON CONFLICT (tenant_id, routing_code) DO NOTHING;

INSERT INTO mst.routing_operation (
    routing_operation_id, tenant_id, workspace_id, routing_id, operation_code, operation_sequence,
    operation_seq, operation_name, standard_cycle_min, metadata
) VALUES
(
    '34000000-0000-4000-8000-000000000311',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    '33000000-0000-4000-8000-000000000311',
    'OP-PYROLYSIS',
    10,
    10,
    'Pyrolysis / Carbonization',
    360.0,
    '{"process_step": "PYROLYSIS", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '34000000-0000-4000-8000-000000000312',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    '33000000-0000-4000-8000-000000000311',
    'OP-ACTIVATION',
    20,
    20,
    'Steam Activation',
    480.0,
    '{"process_step": "ACTIVATION", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '34000000-0000-4000-8000-000000000313',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    '33000000-0000-4000-8000-000000000311',
    'OP-SCREENING',
    30,
    30,
    'Screening & Classification',
    120.0,
    '{"process_step": "SCREENING", "industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    '34000000-0000-4000-8000-000000000314',
    'b2000000-0000-4000-8000-000000000010',
    'e7000000-0000-4000-8000-000000000010',
    '33000000-0000-4000-8000-000000000311',
    'OP-QC',
    40,
    40,
    'Quality Testing',
    60.0,
    '{"process_step": "QC", "industry": "ACTIVATED_CARBON"}'::jsonb
)
ON CONFLICT (tenant_id, routing_id, operation_code) DO NOTHING;

-- Per-operation resource requirements (feasibility: machine, tool, workforce)
INSERT INTO mst.operation_resource_requirement (
    requirement_id, tenant_id, routing_operation_id, resource_id,
    requirement_type, quantity, uom, metadata
) VALUES
-- Pyrolysis: kiln + operators + charging tool
(
    '35000000-0000-4000-8000-000000000311',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000311',
    '31000000-0000-4000-8000-000000000311',
    'PRIMARY', 1, 'EA', '{"process_step": "PYROLYSIS"}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000312',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000311',
    '31000000-0000-4000-8000-000000000314',
    'LABOR', 2, 'EA', '{"operators": 2}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000313',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000311',
    '31000000-0000-4000-8000-000000000315',
    'TOOL', 1, 'EA', '{}'::jsonb
),
-- Activation: kiln + operators + steam lance
(
    '35000000-0000-4000-8000-000000000321',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000312',
    '31000000-0000-4000-8000-000000000311',
    'PRIMARY', 1, 'EA', '{"process_step": "ACTIVATION"}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000322',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000312',
    '31000000-0000-4000-8000-000000000314',
    'LABOR', 2, 'EA', '{"operators": 2}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000323',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000312',
    '31000000-0000-4000-8000-000000000316',
    'TOOL', 1, 'EA', '{}'::jsonb
),
-- Screening: screen line + operator + sieve
(
    '35000000-0000-4000-8000-000000000331',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000313',
    '31000000-0000-4000-8000-000000000312',
    'PRIMARY', 1, 'EA', '{"process_step": "SCREENING"}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000332',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000313',
    '31000000-0000-4000-8000-000000000314',
    'LABOR', 1, 'EA', '{"operators": 1}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000333',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000313',
    '31000000-0000-4000-8000-000000000317',
    'TOOL', 1, 'EA', '{}'::jsonb
),
-- QC: lab team + test kit
(
    '35000000-0000-4000-8000-000000000341',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000314',
    '31000000-0000-4000-8000-000000000313',
    'LABOR', 1, 'EA', '{"operators": 1}'::jsonb
),
(
    '35000000-0000-4000-8000-000000000342',
    'b2000000-0000-4000-8000-000000000010',
    '34000000-0000-4000-8000-000000000314',
    '31000000-0000-4000-8000-000000000318',
    'TOOL', 1, 'EA', '{}'::jsonb
)
ON CONFLICT DO NOTHING;

COMMIT;
