-- =============================================================================
-- Chemical Processing demo — master data for local validation
-- =============================================================================
-- Prerequisites: migration 008 applied (tenant CHEM_DEMO + workspace exist)
-- Safe to re-run (ON CONFLICT DO NOTHING).
-- =============================================================================

BEGIN;

-- tenant  : b2000000-0000-4000-8000-000000000004  CHEM_DEMO
-- workspace: e7000000-0000-4000-8000-000000000002  CHEM_DEMO_WS

INSERT INTO mst.customer (
    customer_id, tenant_id, workspace_id, customer_code, customer_name, metadata
) VALUES (
    'c5000000-0000-4000-8000-000000000004',
    'b2000000-0000-4000-8000-000000000004',
    'e7000000-0000-4000-8000-000000000002',
    'CUST-CHEM-001',
    'Demo Chemical Buyer',
    '{"segment": "Internal", "industry": "CHEMICAL"}'::jsonb
) ON CONFLICT DO NOTHING;

INSERT INTO mst.product (
    product_id, tenant_id, workspace_id, product_code, product_name, product_type, uom, metadata
) VALUES
(
    'a6000000-0000-4000-8000-000000000401',
    'b2000000-0000-4000-8000-000000000004',
    'e7000000-0000-4000-8000-000000000002',
    'RAW-ETHANOL',
    'Industrial Ethanol (Feedstock)',
    'RAW_MATERIAL',
    'KG',
    '{"purity_pct_min": 95, "industry": "CHEMICAL"}'::jsonb
),
(
    'a6000000-0000-4000-8000-000000000402',
    'b2000000-0000-4000-8000-000000000004',
    'e7000000-0000-4000-8000-000000000002',
    'CHEM-SOLVENT-A',
    'Specialty Solvent Grade A',
    'FINISHED',
    'KG',
    '{"viscosity_cp_target": 12, "industry": "CHEMICAL"}'::jsonb
)
ON CONFLICT DO NOTHING;

INSERT INTO mst.resource (
    resource_id, tenant_id, workspace_id, resource_code, resource_name, resource_type, metadata
) VALUES
(
    '31000000-0000-4000-8000-000000000401',
    'b2000000-0000-4000-8000-000000000004',
    'e7000000-0000-4000-8000-000000000002',
    'RES-REACTOR-01',
    'Batch Reactor 01',
    'MACHINE',
    '{"capacity_kl": 5, "resource_role": "REACTOR", "industry": "CHEMICAL"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000402',
    'b2000000-0000-4000-8000-000000000004',
    'e7000000-0000-4000-8000-000000000002',
    'RES-BLEND-01',
    'Blending Tank 01',
    'MACHINE',
    '{"capacity_kl": 10, "resource_role": "BLENDER", "industry": "CHEMICAL"}'::jsonb
),
(
    '31000000-0000-4000-8000-000000000403',
    'b2000000-0000-4000-8000-000000000004',
    'e7000000-0000-4000-8000-000000000002',
    'RES-LAB-QC',
    'Chemical QC Lab',
    'LABOR',
    '{"shift": "A", "operators": 2, "industry": "CHEMICAL"}'::jsonb
)
ON CONFLICT DO NOTHING;

INSERT INTO mst.routing (
    routing_id,
    tenant_id,
    workspace_id,
    routing_code,
    product_id,
    routing_version,
    process_family,
    is_active,
    industry_template_code,
    source_template_code,
    is_template_route,
    is_template_copy,
    is_customized,
    metadata
)
SELECT
    '33000000-0000-4000-8000-000000000321',
    'b2000000-0000-4000-8000-000000000004',
    'e7000000-0000-4000-8000-000000000002',
    'RT-CHEM-SOLVENT-A-V1',
    p.product_id,
    '1',
    'Batch Reaction',
    TRUE,
    'CHEMICAL',
    'CHEM_STANDARD_PROCESS',
    FALSE,
    TRUE,
    FALSE,
    '{"product_code": "CHEM-SOLVENT-A", "industry": "CHEMICAL"}'::jsonb
FROM mst.product p
WHERE p.product_code = 'CHEM-SOLVENT-A'
  AND p.tenant_id = 'b2000000-0000-4000-8000-000000000004'
ON CONFLICT DO NOTHING;

COMMIT;
