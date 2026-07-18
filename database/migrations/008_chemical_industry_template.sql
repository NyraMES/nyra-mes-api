-- =============================================================================
-- Migration 008: Chemical Processing industry template
-- =============================================================================
-- Database : nyra_mes_core
-- Purpose  : Additive CHEMICAL industry template, capabilities, demo tenant,
--            workspace, and canonical batch process route.
--
-- Safe to re-run (IF NOT EXISTS / ON CONFLICT / ADD COLUMN IF NOT EXISTS)
--
-- Run manually:
--   psql -d nyra_mes_core -f database/migrations/008_chemical_industry_template.sql
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. CHEMICAL industry template
-- ---------------------------------------------------------------------------
INSERT INTO template.industry_template (
    industry_template_id,
    template_code,
    template_name,
    description,
    template_version,
    module_code,
    landing_page,
    ui_module_name,
    api_module_name,
    icon_name,
    dashboard_component,
    display_order,
    metadata
) VALUES (
    'a1000000-0000-4000-8000-000000000003',
    'CHEMICAL',
    'Chemical Batch Processing',
    'Batch reactor operations, formulation, quality testing, and traceability for chemical plants.',
    '1.0.0',
    'chemical',
    '/chemical/dashboard',
    'ChemicalModule',
    'chemicalApi',
    'flask',
    'ChemicalDashboard',
    25,
    '{"process_families": ["Receipt", "Reaction", "Blending", "QC"], "default_uom": "KG"}'::jsonb
)
ON CONFLICT (template_code) DO NOTHING;

UPDATE template.industry_template
SET
    template_name       = COALESCE(template_name, 'Chemical Batch Processing'),
    module_code         = COALESCE(module_code, 'chemical'),
    landing_page        = COALESCE(landing_page, '/chemical/dashboard'),
    ui_module_name      = COALESCE(ui_module_name, 'ChemicalModule'),
    api_module_name     = COALESCE(api_module_name, 'chemicalApi'),
    icon_name           = COALESCE(icon_name, 'flask'),
    dashboard_component = COALESCE(dashboard_component, 'ChemicalDashboard'),
    display_order       = CASE
                              WHEN display_order IS NULL OR display_order = 100 THEN 25
                              ELSE display_order
                          END,
    updated_at          = NOW()
WHERE template_code = 'CHEMICAL';

-- ---------------------------------------------------------------------------
-- 2. CHEM_DEMO tenant + workspace
-- ---------------------------------------------------------------------------
INSERT INTO core.tenant (
    tenant_id,
    tenant_code,
    tenant_name,
    industry_template_id,
    timezone,
    metadata
)
SELECT
    'b2000000-0000-4000-8000-000000000004',
    'CHEM_DEMO',
    'Chemical Processing Demo Plant',
    it.industry_template_id,
    'Asia/Kolkata',
    '{"demo": true, "industry": "CHEMICAL"}'::jsonb
FROM template.industry_template it
WHERE it.template_code = 'CHEMICAL'
ON CONFLICT (tenant_code) DO NOTHING;

INSERT INTO core.project_workspace (
    workspace_id,
    tenant_id,
    workspace_code,
    workspace_name,
    status,
    metadata
)
SELECT
    'e7000000-0000-4000-8000-000000000002',
    t.tenant_id,
    'CHEM_DEMO_WS',
    'Chemical Demo Workspace',
    'ACTIVE',
    '{"demo": true, "plant": "Chemical Processing Demo Plant"}'::jsonb
FROM core.tenant t
WHERE t.tenant_code = 'CHEM_DEMO'
ON CONFLICT (tenant_id, workspace_code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Chemical capabilities
-- ---------------------------------------------------------------------------
INSERT INTO core.capability (
    capability_id, capability_code, capability_name, description, category, metadata
) VALUES
(
    'f8000000-0000-4000-8000-00000000000b',
    'CHEM_RAW_MATERIAL_RECEIPT',
    'Raw Material Receipt',
    'Log inbound chemical raw material and feedstock receipts.',
    'INBOUND',
    '{"industry": "CHEMICAL"}'::jsonb
),
(
    'f8000000-0000-4000-8000-00000000000c',
    'CHEM_RAW_MATERIAL_QC',
    'Raw Material QC',
    'Incoming inspection of chemical feedstock.',
    'QUALITY',
    '{"industry": "CHEMICAL"}'::jsonb
),
(
    'f8000000-0000-4000-8000-00000000000d',
    'CHEM_REACTOR_CHARGE',
    'Reactor Charge',
    'Charge reactor batches from prepared feedstock.',
    'PRODUCTION',
    '{"industry": "CHEMICAL"}'::jsonb
),
(
    'f8000000-0000-4000-8000-00000000000e',
    'CHEM_REACTOR_PARAMETERS',
    'Reactor Parameters',
    'Capture temperature, pressure, agitation, and batch readings.',
    'EXECUTION',
    '{"industry": "CHEMICAL"}'::jsonb
),
(
    'f8000000-0000-4000-8000-00000000000f',
    'CHEM_BLEND_FORMULATION',
    'Blend & Formulation',
    'Blending, formulation, and intermediate handling.',
    'PRODUCTION',
    '{"industry": "CHEMICAL"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000010',
    'CHEM_BATCH_QC',
    'Batch QC',
    'Batch quality tests — purity, moisture, viscosity, and release.',
    'QUALITY',
    '{"industry": "CHEMICAL"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000011',
    'CHEM_BATCH_ANALYTICS',
    'Batch Analytics',
    'Mass-balance and batch yield analytics.',
    'ANALYTICS',
    '{"industry": "CHEMICAL"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000012',
    'CHEM_TRACEABILITY',
    'Traceability',
    'Batch genealogy from feedstock to finished chemical.',
    'TRACEABILITY',
    '{"industry": "CHEMICAL"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000013',
    'CHEM_KNOWLEDGE_GRAPH',
    'Knowledge Graph',
    'Ontology and knowledge-graph views for chemical workflows.',
    'INTELLIGENCE',
    '{"industry": "CHEMICAL"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000014',
    'CHEM_ROUTING_BUILDER',
    'Routing Builder',
    'Customize batch process routes for chemical products.',
    'CONFIGURATION',
    '{"industry": "CHEMICAL"}'::jsonb
)
ON CONFLICT (capability_code) DO NOTHING;

INSERT INTO template.industry_capability (
    industry_capability_id,
    industry_template_id,
    capability_id,
    display_order,
    is_required,
    metadata
)
SELECT
    v.industry_capability_id,
    it.industry_template_id,
    c.capability_id,
    v.display_order,
    v.is_required,
    '{"industry": "CHEMICAL"}'::jsonb
FROM template.industry_template it
CROSS JOIN (VALUES
    ('f9000000-0000-4000-8000-00000000000b'::uuid, 'CHEM_RAW_MATERIAL_RECEIPT',  10, TRUE),
    ('f9000000-0000-4000-8000-00000000000c'::uuid, 'CHEM_RAW_MATERIAL_QC',       20, TRUE),
    ('f9000000-0000-4000-8000-00000000000d'::uuid, 'CHEM_REACTOR_CHARGE',        30, TRUE),
    ('f9000000-0000-4000-8000-00000000000e'::uuid, 'CHEM_REACTOR_PARAMETERS',    40, FALSE),
    ('f9000000-0000-4000-8000-00000000000f'::uuid, 'CHEM_BLEND_FORMULATION',     50, TRUE),
    ('f9000000-0000-4000-8000-000000000010'::uuid, 'CHEM_BATCH_QC',              60, TRUE),
    ('f9000000-0000-4000-8000-000000000011'::uuid, 'CHEM_BATCH_ANALYTICS',       70, FALSE),
    ('f9000000-0000-4000-8000-000000000012'::uuid, 'CHEM_TRACEABILITY',          80, TRUE),
    ('f9000000-0000-4000-8000-000000000013'::uuid, 'CHEM_KNOWLEDGE_GRAPH',       90, FALSE),
    ('f9000000-0000-4000-8000-000000000014'::uuid, 'CHEM_ROUTING_BUILDER',      100, FALSE)
) AS v(industry_capability_id, capability_code, display_order, is_required)
JOIN core.capability c ON c.capability_code = v.capability_code
WHERE it.template_code = 'CHEMICAL'
ON CONFLICT (industry_template_id, capability_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. Canonical CHEM_STANDARD_PROCESS template route (CHEM_DEMO tenant)
-- ---------------------------------------------------------------------------
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
    '33000000-0000-4000-8000-000000000320',
    t.tenant_id,
    NULL,
    'CHEM_STANDARD_PROCESS',
    NULL,
    '1',
    'Batch Reaction',
    TRUE,
    'CHEMICAL',
    'CHEM_STANDARD_PROCESS',
    TRUE,
    FALSE,
    FALSE,
    '{"description": "Canonical chemical batch manufacturing process route"}'::jsonb
FROM core.tenant t
WHERE t.tenant_code = 'CHEM_DEMO'
ON CONFLICT (tenant_id, routing_code) DO NOTHING;

INSERT INTO mst.routing_operation (
    routing_operation_id,
    tenant_id,
    workspace_id,
    routing_id,
    operation_code,
    operation_sequence,
    operation_seq,
    operation_name,
    operation_type,
    is_quality_gate,
    is_feasibility_gate,
    is_active,
    industry_template_code,
    source_template_operation_code,
    is_customized,
    metadata
)
SELECT
    v.routing_operation_id,
    r.tenant_id,
    NULL,
    r.routing_id,
    v.operation_code,
    v.operation_seq,
    v.operation_seq,
    v.operation_name,
    v.operation_type,
    v.is_quality_gate,
    v.is_feasibility_gate,
    TRUE,
    'CHEMICAL',
    v.operation_code,
    FALSE,
    v.metadata
FROM mst.routing r
CROSS JOIN (VALUES
    (
        '34000000-0000-4000-8000-000000000321'::uuid,
        'OP-RAW-RECEIPT',
        10,
        'Raw Material Receipt',
        'MATERIAL',
        FALSE,
        FALSE,
        '{"process_step": "RAW_RECEIPT"}'::jsonb
    ),
    (
        '34000000-0000-4000-8000-000000000322'::uuid,
        'OP-RAW-QC',
        20,
        'Raw Material QC',
        'QUALITY',
        TRUE,
        FALSE,
        '{"process_step": "RAW_QC"}'::jsonb
    ),
    (
        '34000000-0000-4000-8000-000000000323'::uuid,
        'OP-REACTOR-CHARGE',
        30,
        'Reactor Charge',
        'PRODUCTION',
        FALSE,
        FALSE,
        '{"process_step": "REACTOR_CHARGE"}'::jsonb
    ),
    (
        '34000000-0000-4000-8000-000000000324'::uuid,
        'OP-REACTOR-RUN',
        40,
        'Reactor Run',
        'PRODUCTION',
        FALSE,
        FALSE,
        '{"process_step": "REACTOR_RUN"}'::jsonb
    ),
    (
        '34000000-0000-4000-8000-000000000325'::uuid,
        'OP-BLEND',
        50,
        'Blend & Formulation',
        'PRODUCTION',
        FALSE,
        FALSE,
        '{"process_step": "BLEND"}'::jsonb
    ),
    (
        '34000000-0000-4000-8000-000000000326'::uuid,
        'OP-BATCH-QC',
        60,
        'Batch QC',
        'QUALITY',
        TRUE,
        FALSE,
        '{"process_step": "BATCH_QC"}'::jsonb
    ),
    (
        '34000000-0000-4000-8000-000000000327'::uuid,
        'OP-PACK-DISPATCH',
        70,
        'Pack & Dispatch',
        'LOGISTICS',
        FALSE,
        FALSE,
        '{"process_step": "DISPATCH"}'::jsonb
    )
) AS v(
    routing_operation_id,
    operation_code,
    operation_seq,
    operation_name,
    operation_type,
    is_quality_gate,
    is_feasibility_gate,
    metadata
)
WHERE r.routing_code = 'CHEM_STANDARD_PROCESS'
  AND r.tenant_id = (SELECT tenant_id FROM core.tenant WHERE tenant_code = 'CHEM_DEMO')
ON CONFLICT DO NOTHING;

COMMIT;
