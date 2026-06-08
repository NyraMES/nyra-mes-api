-- =============================================================================
-- Migration 004: Route customization + Activated Carbon stabilization
-- =============================================================================
-- Database : nyra_mes_core
-- Purpose  : Workspace-scoped route customization metadata, AC industry template
--            route (AC_STANDARD_PROCESS), raw-material parameter profiles, and
--            transactional dispatch — without altering Automotive OEM behaviour.
--
-- Rules:
--   - No DROP / DELETE of existing tables or rows
--   - Does not modify migration 003 or prior scripts in place
--   - Safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / ON CONFLICT)
--   - AUTO_OEM_DEMO / AUTOMOBILE_OEM master data unchanged (additive only)
--
-- Run manually (NOT executed automatically):
--   psql -d nyra_mes_core -f database/migrations/004_route_customization_and_ac_stabilization.sql
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Extend mst.routing — workspace / template route customization columns
-- ---------------------------------------------------------------------------
ALTER TABLE mst.routing
    ADD COLUMN IF NOT EXISTS industry_template_code  VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_template_code    VARCHAR(64),
    ADD COLUMN IF NOT EXISTS is_template_route       BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_template_copy        BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_customized           BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN mst.routing.industry_template_code IS
    'Industry template code (e.g. ACTIVATED_CARBON, AUTOMOBILE_OEM) for template or workspace routes';
COMMENT ON COLUMN mst.routing.source_template_code IS
    'Origin template routing_code when copied/customized from an industry template route';
COMMENT ON COLUMN mst.routing.is_template_route IS
    'TRUE for canonical industry template routes (not tenant product-specific copies)';
COMMENT ON COLUMN mst.routing.is_template_copy IS
    'TRUE when this routing was instantiated from an industry template route';
COMMENT ON COLUMN mst.routing.is_customized IS
    'TRUE when workspace-specific edits diverge from the source template route';

-- Template routes may omit product_id (generic process route + parameter profiles)
ALTER TABLE mst.routing
    ALTER COLUMN product_id DROP NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_routing_product_or_template'
          AND conrelid = 'mst.routing'::regclass
    ) THEN
        ALTER TABLE mst.routing
            ADD CONSTRAINT chk_routing_product_or_template CHECK (
                product_id IS NOT NULL
                OR is_template_route = TRUE
            );
    END IF;
END $$;

-- Backfill industry_template_code for existing tenant routings (OEM-safe, NULL-only)
UPDATE mst.routing r
SET industry_template_code = it.template_code,
    updated_at             = NOW()
FROM core.tenant t
JOIN template.industry_template it
    ON it.industry_template_id = t.industry_template_id
WHERE r.tenant_id = t.tenant_id
  AND r.industry_template_code IS NULL;

-- ---------------------------------------------------------------------------
-- 2. Extend mst.routing_operation — template copy / gate metadata
-- ---------------------------------------------------------------------------
ALTER TABLE mst.routing_operation
    ADD COLUMN IF NOT EXISTS industry_template_code           VARCHAR(64),
    ADD COLUMN IF NOT EXISTS source_template_operation_code   VARCHAR(64),
    ADD COLUMN IF NOT EXISTS operation_seq                    INTEGER,
    ADD COLUMN IF NOT EXISTS operation_type                   VARCHAR(64),
    ADD COLUMN IF NOT EXISTS is_quality_gate                  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_feasibility_gate              BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS is_active                          BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS is_customized                      BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN mst.routing_operation.operation_seq IS
    'Display/process sequence; mirrors operation_sequence for template-aware UIs';
COMMENT ON COLUMN mst.routing_operation.source_template_operation_code IS
    'Origin operation_code from industry template route when copied/customized';

UPDATE mst.routing_operation
SET operation_seq = operation_sequence
WHERE operation_seq IS NULL;

UPDATE mst.routing_operation ro
SET industry_template_code = r.industry_template_code,
    updated_at             = NOW()
FROM mst.routing r
WHERE ro.routing_id = r.routing_id
  AND ro.industry_template_code IS NULL
  AND r.industry_template_code IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 3. mst.routing_operation_parameter — per-operation capture parameters
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mst.routing_operation_parameter (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id             UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    workspace_id          UUID         REFERENCES core.project_workspace (workspace_id),
    routing_operation_id  UUID         NOT NULL
        REFERENCES mst.routing_operation (routing_operation_id) ON DELETE CASCADE,
    parameter_code        VARCHAR(64),
    parameter_name        VARCHAR(256),
    data_type             VARCHAR(32),
    unit                  VARCHAR(32),
    min_value             NUMERIC(18, 6),
    max_value             NUMERIC(18, 6),
    is_mandatory          BOOLEAN      NOT NULL DEFAULT FALSE,
    reading_frequency     VARCHAR(64),
    display_order         INTEGER,
    is_active             BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_routing_operation_parameter_tenant
    ON mst.routing_operation_parameter (tenant_id);

CREATE INDEX IF NOT EXISTS idx_routing_operation_parameter_workspace
    ON mst.routing_operation_parameter (workspace_id);

CREATE INDEX IF NOT EXISTS idx_routing_operation_parameter_routing_operation
    ON mst.routing_operation_parameter (routing_operation_id);

CREATE INDEX IF NOT EXISTS idx_routing_operation_parameter_tenant_workspace
    ON mst.routing_operation_parameter (tenant_id, workspace_id);

DROP TRIGGER IF EXISTS trg_routing_operation_parameter_updated_at
    ON mst.routing_operation_parameter;
CREATE TRIGGER trg_routing_operation_parameter_updated_at
    BEFORE UPDATE ON mst.routing_operation_parameter
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

COMMENT ON TABLE mst.routing_operation_parameter IS
    'Workspace-scoped operation parameters (limits, UOM, capture frequency).';

-- ---------------------------------------------------------------------------
-- 4. template.raw_material_parameter_profile — one base route + material profiles
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS template.raw_material_parameter_profile (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    industry_template_code   VARCHAR(64)   NOT NULL,
    raw_material_type        VARCHAR(128)  NOT NULL,
    profile_code             VARCHAR(128)  NOT NULL,
    profile_name             VARCHAR(256),
    parameter_code           VARCHAR(64)   NOT NULL,
    parameter_name           VARCHAR(256),
    min_value                NUMERIC(18, 6),
    max_value                NUMERIC(18, 6),
    unit                     VARCHAR(32),
    expected_yield_percent   NUMERIC(8, 4),
    expected_ctc_min         NUMERIC(18, 6),
    expected_ctc_max         NUMERIC(18, 6),
    expected_density_min     NUMERIC(18, 6),
    expected_density_max     NUMERIC(18, 6),
    is_active                BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at               TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_raw_material_parameter_profile UNIQUE (
        industry_template_code,
        raw_material_type,
        profile_code,
        parameter_code
    )
);

CREATE INDEX IF NOT EXISTS idx_raw_material_profile_industry
    ON template.raw_material_parameter_profile (industry_template_code);

CREATE INDEX IF NOT EXISTS idx_raw_material_profile_material_type
    ON template.raw_material_parameter_profile (raw_material_type);

CREATE INDEX IF NOT EXISTS idx_raw_material_profile_profile_code
    ON template.raw_material_parameter_profile (profile_code);

DROP TRIGGER IF EXISTS trg_raw_material_parameter_profile_updated_at
    ON template.raw_material_parameter_profile;
CREATE TRIGGER trg_raw_material_parameter_profile_updated_at
    BEFORE UPDATE ON template.raw_material_parameter_profile
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

COMMENT ON TABLE template.raw_material_parameter_profile IS
    'Activated Carbon raw-material parameter bands — shared across AC_STANDARD_PROCESS (no per-material routes).';

-- ---------------------------------------------------------------------------
-- 5. trn.dispatch — AC / mes_core dispatch document (additive; legacy dispatch unchanged)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trn.dispatch (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    workspace_id         UUID         REFERENCES core.project_workspace (workspace_id),
    customer_order_id    UUID         REFERENCES trn.customer_order (customer_order_id),
    production_lot_id    UUID         REFERENCES trn.production_lot (production_lot_id),
    finished_goods_lot_no VARCHAR(128),
    grade                VARCHAR(64),
    bag_count            NUMERIC(18, 4),
    total_weight         NUMERIC(18, 4),
    vehicle_no           VARCHAR(64),
    dispatch_date        DATE,
    invoice_ref          VARCHAR(128),
    destination          TEXT,
    status               VARCHAR(32)  NOT NULL DEFAULT 'PLANNED',
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_dispatch_status CHECK (
        status IN ('PLANNED', 'READY', 'IN_TRANSIT', 'DELIVERED', 'CANCELLED')
    )
);

CREATE INDEX IF NOT EXISTS idx_dispatch_tenant
    ON trn.dispatch (tenant_id);

CREATE INDEX IF NOT EXISTS idx_dispatch_workspace
    ON trn.dispatch (workspace_id);

CREATE INDEX IF NOT EXISTS idx_dispatch_tenant_workspace
    ON trn.dispatch (tenant_id, workspace_id);

CREATE INDEX IF NOT EXISTS idx_dispatch_customer_order
    ON trn.dispatch (customer_order_id);

CREATE INDEX IF NOT EXISTS idx_dispatch_production_lot
    ON trn.dispatch (production_lot_id);

CREATE INDEX IF NOT EXISTS idx_dispatch_dispatch_date
    ON trn.dispatch (dispatch_date);

DROP TRIGGER IF EXISTS trg_dispatch_updated_at ON trn.dispatch;
CREATE TRIGGER trg_dispatch_updated_at
    BEFORE UPDATE ON trn.dispatch
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

COMMENT ON TABLE trn.dispatch IS
    'Shipment dispatch records (Activated Carbon and future industries). Distinct from legacy oemauto dispatch.';

-- ---------------------------------------------------------------------------
-- 6. SAM_CARBONS tenant + SAM_CARBONS_ACTIVATED_CARBON workspace (separate from DEMO)
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
    'b2000000-0000-4000-8000-000000000010',
    'SAM_CARBONS',
    'Activated Carbon Plant',
    it.industry_template_id,
    'Asia/Kolkata',
    '{"industry": "ACTIVATED_CARBON", "production": true}'::jsonb
FROM template.industry_template it
WHERE it.template_code = 'ACTIVATED_CARBON'
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
    'e7000000-0000-4000-8000-000000000010',
    t.tenant_id,
    'SAM_CARBONS_ACTIVATED_CARBON',
    'Activated Carbon',
    'ACTIVE',
    '{"industry": "ACTIVATED_CARBON", "module": "activated-carbon"}'::jsonb
FROM core.tenant t
WHERE t.tenant_code = 'SAM_CARBONS'
ON CONFLICT (tenant_id, workspace_code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 7. Activated Carbon industry template route: AC_STANDARD_PROCESS
--    One canonical route — raw material variation via parameter profiles only.
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
    '33000000-0000-4000-8000-000000000310',
    t.tenant_id,
    NULL,
    'AC_STANDARD_PROCESS',
    NULL,
    '1',
    'Activation',
    TRUE,
    'ACTIVATED_CARBON',
    'AC_STANDARD_PROCESS',
    TRUE,
    FALSE,
    FALSE,
    '{"description": "Canonical Activated Carbon manufacturing process route"}'::jsonb
FROM core.tenant t
WHERE t.tenant_code = 'SAM_CARBONS'
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
    'ACTIVATED_CARBON',
    v.operation_code,
    FALSE,
    jsonb_build_object(
        'process_step', v.process_step,
        'industry_template_code', 'ACTIVATED_CARBON'
    )
FROM mst.routing r
JOIN core.tenant t ON t.tenant_id = r.tenant_id
CROSS JOIN (VALUES
    (
        '34000000-0000-4000-8000-000000000401'::uuid,
        'AC-OP-RAW-INWARD',
        10,
        'Raw Material Inward',
        'INBOUND',
        FALSE,
        FALSE,
        'RAW_MATERIAL_INWARD'
    ),
    (
        '34000000-0000-4000-8000-000000000402'::uuid,
        'AC-OP-RAW-QC',
        20,
        'Raw Material QC',
        'QUALITY',
        TRUE,
        FALSE,
        'RAW_MATERIAL_QC'
    ),
    (
        '34000000-0000-4000-8000-000000000403'::uuid,
        'AC-OP-FEASIBILITY',
        30,
        'Feasibility Gate',
        'PLANNING',
        FALSE,
        TRUE,
        'FEASIBILITY'
    ),
    (
        '34000000-0000-4000-8000-000000000404'::uuid,
        'AC-OP-KILN-FEED',
        40,
        'Kiln Feed',
        'PRODUCTION',
        FALSE,
        FALSE,
        'KILN_FEED'
    ),
    (
        '34000000-0000-4000-8000-000000000405'::uuid,
        'AC-OP-KILN-ACTIVATION',
        50,
        'Kiln Activation',
        'PRODUCTION',
        FALSE,
        FALSE,
        'KILN_ACTIVATION'
    ),
    (
        '34000000-0000-4000-8000-000000000406'::uuid,
        'AC-OP-COOLING',
        60,
        'Cooling',
        'PRODUCTION',
        FALSE,
        FALSE,
        'COOLING'
    ),
    (
        '34000000-0000-4000-8000-000000000407'::uuid,
        'AC-OP-SCREENING',
        70,
        'Screening',
        'PRODUCTION',
        FALSE,
        FALSE,
        'SCREENING'
    ),
    (
        '34000000-0000-4000-8000-000000000408'::uuid,
        'AC-OP-GRADE-SEP',
        80,
        'Grade Separation',
        'PRODUCTION',
        FALSE,
        FALSE,
        'GRADE_SEPARATION'
    ),
    (
        '34000000-0000-4000-8000-000000000409'::uuid,
        'AC-OP-QUALITY-TEST',
        90,
        'Quality Testing',
        'QUALITY',
        TRUE,
        FALSE,
        'QUALITY_TESTING'
    ),
    (
        '34000000-0000-4000-8000-00000000040a'::uuid,
        'AC-OP-FG-PACK',
        100,
        'Finished Goods Packing',
        'PACKING',
        FALSE,
        FALSE,
        'FG_PACKING'
    ),
    (
        '34000000-0000-4000-8000-00000000040b'::uuid,
        'AC-OP-DISPATCH',
        110,
        'Dispatch',
        'LOGISTICS',
        FALSE,
        FALSE,
        'DISPATCH'
    )
) AS v(
    routing_operation_id,
    operation_code,
    operation_seq,
    operation_name,
    operation_type,
    is_quality_gate,
    is_feasibility_gate,
    process_step
)
WHERE t.tenant_code = 'SAM_CARBONS'
  AND r.routing_code = 'AC_STANDARD_PROCESS'
  AND r.is_template_route = TRUE
ON CONFLICT (tenant_id, routing_id, operation_code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 8. Raw material parameter profiles (3 materials × 7 kiln/process parameters)
-- ---------------------------------------------------------------------------
INSERT INTO template.raw_material_parameter_profile (
    id,
    industry_template_code,
    raw_material_type,
    profile_code,
    profile_name,
    parameter_code,
    parameter_name,
    min_value,
    max_value,
    unit,
    expected_yield_percent,
    expected_ctc_min,
    expected_ctc_max,
    expected_density_min,
    expected_density_max,
    is_active
)
SELECT
    v.id,
    'ACTIVATED_CARBON',
    v.raw_material_type,
    v.profile_code,
    v.profile_name,
    v.parameter_code,
    v.parameter_name,
    v.min_value,
    v.max_value,
    v.unit,
    v.expected_yield_percent,
    v.expected_ctc_min,
    v.expected_ctc_max,
    v.expected_density_min,
    v.expected_density_max,
    TRUE
FROM (VALUES
    -- Granulated Charcoal
    ('a4000000-0000-4000-8000-000000000001'::uuid, 'GRANULATED_CHARCOAL', 'AC-RMP-GRANULATED', 'Granulated Charcoal', 'T1_TEMPERATURE', 'T1 Temperature', 450, 550, 'C', 22.0, 800, 950, 0.45, 0.55),
    ('a4000000-0000-4000-8000-000000000002'::uuid, 'GRANULATED_CHARCOAL', 'AC-RMP-GRANULATED', 'Granulated Charcoal', 'T2_TEMPERATURE', 'T2 Temperature', 550, 650, 'C', 22.0, 800, 950, 0.45, 0.55),
    ('a4000000-0000-4000-8000-000000000003'::uuid, 'GRANULATED_CHARCOAL', 'AC-RMP-GRANULATED', 'Granulated Charcoal', 'T3_TEMPERATURE', 'T3 Temperature', 650, 750, 'C', 22.0, 800, 950, 0.45, 0.55),
    ('a4000000-0000-4000-8000-000000000004'::uuid, 'GRANULATED_CHARCOAL', 'AC-RMP-GRANULATED', 'Granulated Charcoal', 'T4_TEMPERATURE', 'T4 Temperature', 750, 850, 'C', 22.0, 800, 950, 0.45, 0.55),
    ('a4000000-0000-4000-8000-000000000005'::uuid, 'GRANULATED_CHARCOAL', 'AC-RMP-GRANULATED', 'Granulated Charcoal', 'PRESSURE', 'Pressure', 0.5, 2.5, 'bar', 22.0, 800, 950, 0.45, 0.55),
    ('a4000000-0000-4000-8000-000000000006'::uuid, 'GRANULATED_CHARCOAL', 'AC-RMP-GRANULATED', 'Granulated Charcoal', 'STEAM_FLOW', 'Steam Flow', 200, 600, 'kg/h', 22.0, 800, 950, 0.45, 0.55),
    ('a4000000-0000-4000-8000-000000000007'::uuid, 'GRANULATED_CHARCOAL', 'AC-RMP-GRANULATED', 'Granulated Charcoal', 'RESIDENCE_TIME', 'Residence Time', 45, 120, 'min', 22.0, 800, 950, 0.45, 0.55),
    -- Coconut Shell Charcoal
    ('a4000000-0000-4000-8000-000000000011'::uuid, 'COCONUT_SHELL_CHARCOAL', 'AC-RMP-COCO-SHELL', 'Coconut Shell Charcoal', 'T1_TEMPERATURE', 'T1 Temperature', 500, 600, 'C', 25.0, 900, 1050, 0.48, 0.58),
    ('a4000000-0000-4000-8000-000000000012'::uuid, 'COCONUT_SHELL_CHARCOAL', 'AC-RMP-COCO-SHELL', 'Coconut Shell Charcoal', 'T2_TEMPERATURE', 'T2 Temperature', 600, 700, 'C', 25.0, 900, 1050, 0.48, 0.58),
    ('a4000000-0000-4000-8000-000000000013'::uuid, 'COCONUT_SHELL_CHARCOAL', 'AC-RMP-COCO-SHELL', 'Coconut Shell Charcoal', 'T3_TEMPERATURE', 'T3 Temperature', 700, 800, 'C', 25.0, 900, 1050, 0.48, 0.58),
    ('a4000000-0000-4000-8000-000000000014'::uuid, 'COCONUT_SHELL_CHARCOAL', 'AC-RMP-COCO-SHELL', 'Coconut Shell Charcoal', 'T4_TEMPERATURE', 'T4 Temperature', 800, 900, 'C', 25.0, 900, 1050, 0.48, 0.58),
    ('a4000000-0000-4000-8000-000000000015'::uuid, 'COCONUT_SHELL_CHARCOAL', 'AC-RMP-COCO-SHELL', 'Coconut Shell Charcoal', 'PRESSURE', 'Pressure', 0.8, 3.0, 'bar', 25.0, 900, 1050, 0.48, 0.58),
    ('a4000000-0000-4000-8000-000000000016'::uuid, 'COCONUT_SHELL_CHARCOAL', 'AC-RMP-COCO-SHELL', 'Coconut Shell Charcoal', 'STEAM_FLOW', 'Steam Flow', 300, 800, 'kg/h', 25.0, 900, 1050, 0.48, 0.58),
    ('a4000000-0000-4000-8000-000000000017'::uuid, 'COCONUT_SHELL_CHARCOAL', 'AC-RMP-COCO-SHELL', 'Coconut Shell Charcoal', 'RESIDENCE_TIME', 'Residence Time', 60, 150, 'min', 25.0, 900, 1050, 0.48, 0.58),
    -- Wood Charcoal
    ('a4000000-0000-4000-8000-000000000021'::uuid, 'WOOD_CHARCOAL', 'AC-RMP-WOOD', 'Wood Charcoal', 'T1_TEMPERATURE', 'T1 Temperature', 400, 500, 'C', 18.0, 700, 850, 0.40, 0.50),
    ('a4000000-0000-4000-8000-000000000022'::uuid, 'WOOD_CHARCOAL', 'AC-RMP-WOOD', 'Wood Charcoal', 'T2_TEMPERATURE', 'T2 Temperature', 500, 600, 'C', 18.0, 700, 850, 0.40, 0.50),
    ('a4000000-0000-4000-8000-000000000023'::uuid, 'WOOD_CHARCOAL', 'AC-RMP-WOOD', 'Wood Charcoal', 'T3_TEMPERATURE', 'T3 Temperature', 600, 700, 'C', 18.0, 700, 850, 0.40, 0.50),
    ('a4000000-0000-4000-8000-000000000024'::uuid, 'WOOD_CHARCOAL', 'AC-RMP-WOOD', 'Wood Charcoal', 'T4_TEMPERATURE', 'T4 Temperature', 700, 800, 'C', 18.0, 700, 850, 0.40, 0.50),
    ('a4000000-0000-4000-8000-000000000025'::uuid, 'WOOD_CHARCOAL', 'AC-RMP-WOOD', 'Wood Charcoal', 'PRESSURE', 'Pressure', 0.4, 2.0, 'bar', 18.0, 700, 850, 0.40, 0.50),
    ('a4000000-0000-4000-8000-000000000026'::uuid, 'WOOD_CHARCOAL', 'AC-RMP-WOOD', 'Wood Charcoal', 'STEAM_FLOW', 'Steam Flow', 150, 500, 'kg/h', 18.0, 700, 850, 0.40, 0.50),
    ('a4000000-0000-4000-8000-000000000027'::uuid, 'WOOD_CHARCOAL', 'AC-RMP-WOOD', 'Wood Charcoal', 'RESIDENCE_TIME', 'Residence Time', 40, 100, 'min', 18.0, 700, 850, 0.40, 0.50)
) AS v(
    id,
    raw_material_type,
    profile_code,
    profile_name,
    parameter_code,
    parameter_name,
    min_value,
    max_value,
    unit,
    expected_yield_percent,
    expected_ctc_min,
    expected_ctc_max,
    expected_density_min,
    expected_density_max
)
ON CONFLICT (industry_template_code, raw_material_type, profile_code, parameter_code)
DO NOTHING;

-- ---------------------------------------------------------------------------
-- 9. Indexes — routing customization + industry template scoping
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_routing_industry_template_code
    ON mst.routing (industry_template_code);

CREATE INDEX IF NOT EXISTS idx_routing_tenant_workspace
    ON mst.routing (tenant_id, workspace_id);

CREATE INDEX IF NOT EXISTS idx_routing_is_template_route
    ON mst.routing (is_template_route, industry_template_code)
    WHERE is_template_route = TRUE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_routing_industry_template_route_code
    ON mst.routing (industry_template_code, routing_code)
    WHERE is_template_route = TRUE
      AND industry_template_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_routing_operation_industry_template_code
    ON mst.routing_operation (industry_template_code);

CREATE INDEX IF NOT EXISTS idx_routing_operation_tenant_workspace
    ON mst.routing_operation (tenant_id, workspace_id);

CREATE INDEX IF NOT EXISTS idx_routing_operation_routing_id
    ON mst.routing_operation (routing_id);

COMMIT;

-- ---------------------------------------------------------------------------
-- Post-migration verification (optional — run manually)
-- ---------------------------------------------------------------------------
-- SELECT routing_code, industry_template_code, is_template_route, product_id
-- FROM mst.routing
-- WHERE industry_template_code = 'ACTIVATED_CARBON';
--
-- SELECT operation_seq, operation_code, operation_name, is_quality_gate, is_feasibility_gate
-- FROM mst.routing_operation ro
-- JOIN mst.routing r ON r.routing_id = ro.routing_id
-- WHERE r.routing_code = 'AC_STANDARD_PROCESS'
-- ORDER BY operation_seq;
--
-- SELECT raw_material_type, profile_code, parameter_code, min_value, max_value, unit
-- FROM template.raw_material_parameter_profile
-- WHERE industry_template_code = 'ACTIVATED_CARBON'
-- ORDER BY raw_material_type, parameter_code;
--
-- SELECT t.tenant_code, pw.workspace_code
-- FROM core.project_workspace pw
-- JOIN core.tenant t ON t.tenant_id = pw.tenant_id
-- WHERE t.tenant_code IN ('AUTO_OEM_DEMO', 'SAM_CARBONS_DEMO', 'SAM_CARBONS');
