-- =============================================================================
-- Migration 003: Metadata-driven industry template loading
-- =============================================================================
-- Database : nyra_mes_core
-- Purpose  : Additive, backward-compatible support for metadata-driven industry
--            modules (Automobile OEM, Activated Carbon, future industries).
--
-- Rules:
--   - No DROP / DELETE of existing tables or rows
--   - Does not modify AUTO_OEM_DEMO tenant data or AUTOMOBILE_OEM master seed
--   - Preserves existing ACTIVATED_CARBON rows when already present (COALESCE upsert)
--   - Safe to re-run (IF NOT EXISTS / ON CONFLICT / ADD COLUMN IF NOT EXISTS)
--
-- Run manually against nyra_mes_core (NOT executed automatically):
--   psql -d nyra_mes_core -f database/migrations/003_metadata_driven_industry_templates.sql
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Extend template.industry_template with UI/API routing metadata
-- ---------------------------------------------------------------------------
ALTER TABLE template.industry_template
    ADD COLUMN IF NOT EXISTS module_code          VARCHAR(128),
    ADD COLUMN IF NOT EXISTS landing_page         VARCHAR(512),
    ADD COLUMN IF NOT EXISTS ui_module_name        VARCHAR(128),
    ADD COLUMN IF NOT EXISTS api_module_name        VARCHAR(128),
    ADD COLUMN IF NOT EXISTS icon_name              VARCHAR(64),
    ADD COLUMN IF NOT EXISTS dashboard_component    VARCHAR(128),
    ADD COLUMN IF NOT EXISTS display_order          INTEGER NOT NULL DEFAULT 100;

COMMENT ON COLUMN template.industry_template.module_code IS
    'Frontend route namespace slug, e.g. automotive-oem';
COMMENT ON COLUMN template.industry_template.landing_page IS
    'Default SPA landing path for this industry module';
COMMENT ON COLUMN template.industry_template.ui_module_name IS
    'Frontend lazy-loaded module identifier';
COMMENT ON COLUMN template.industry_template.api_module_name IS
    'Frontend API client module identifier';
COMMENT ON COLUMN template.industry_template.icon_name IS
    'Icon key for navigation tiles';
COMMENT ON COLUMN template.industry_template.dashboard_component IS
    'Primary dashboard React component name';
COMMENT ON COLUMN template.industry_template.display_order IS
    'Sort order on industry picker (lower = first)';

COMMENT ON COLUMN template.industry_template.template_code IS
    'Stable industry template code (API/UI alias: industry_template_code)';

-- ---------------------------------------------------------------------------
-- 5. Project / workspace support
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.project_workspace (
    workspace_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    workspace_code  VARCHAR(64)  NOT NULL,
    workspace_name  VARCHAR(256) NOT NULL,
    status          VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE',
    metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_project_workspace_code UNIQUE (tenant_id, workspace_code),
    CONSTRAINT chk_project_workspace_status CHECK (
        status IN ('ACTIVE', 'SUSPENDED', 'ARCHIVED')
    )
);

CREATE INDEX IF NOT EXISTS idx_project_workspace_tenant
    ON core.project_workspace (tenant_id);

CREATE INDEX IF NOT EXISTS idx_project_workspace_tenant_status
    ON core.project_workspace (tenant_id, status);

DROP TRIGGER IF EXISTS trg_project_workspace_updated_at ON core.project_workspace;
CREATE TRIGGER trg_project_workspace_updated_at
    BEFORE UPDATE ON core.project_workspace
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

COMMENT ON TABLE core.project_workspace IS
    'Tenant-scoped project/plant workspaces. Future industry data may scope to workspace_id.';

CREATE TABLE IF NOT EXISTS core.user_project_access (
    access_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID        NOT NULL REFERENCES core.app_user (user_id) ON DELETE CASCADE,
    workspace_id  UUID        NOT NULL REFERENCES core.project_workspace (workspace_id) ON DELETE CASCADE,
    role_code     VARCHAR(64) NOT NULL,
    is_default    BOOLEAN     NOT NULL DEFAULT FALSE,
    granted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_project_access UNIQUE (user_id, workspace_id),
    CONSTRAINT chk_user_project_role CHECK (
        role_code IN ('MES_Admin', 'MES_Planner', 'MES_Operator', 'MES_Quality', 'MES_Viewer')
    )
);

CREATE INDEX IF NOT EXISTS idx_user_project_access_user
    ON core.user_project_access (user_id);

CREATE INDEX IF NOT EXISTS idx_user_project_access_workspace
    ON core.user_project_access (workspace_id);

DROP TRIGGER IF EXISTS trg_user_project_access_updated_at ON core.user_project_access;
CREATE TRIGGER trg_user_project_access_updated_at
    BEFORE UPDATE ON core.user_project_access
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

COMMENT ON TABLE core.user_project_access IS
    'Maps users to project workspaces with MES role codes.';

-- ---------------------------------------------------------------------------
-- 6. Capability catalog + template mapping
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS core.capability (
    capability_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capability_code  VARCHAR(128) NOT NULL,
    capability_name  VARCHAR(256) NOT NULL,
    description      TEXT,
    category         VARCHAR(64),
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
    metadata         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_capability_code UNIQUE (capability_code)
);

CREATE INDEX IF NOT EXISTS idx_capability_code
    ON core.capability (capability_code);

CREATE INDEX IF NOT EXISTS idx_capability_category
    ON core.capability (category);

DROP TRIGGER IF EXISTS trg_capability_updated_at ON core.capability;
CREATE TRIGGER trg_capability_updated_at
    BEFORE UPDATE ON core.capability
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

COMMENT ON TABLE core.capability IS
    'Platform capability catalog (industry-agnostic). Referenced by template.industry_capability.';

CREATE TABLE IF NOT EXISTS template.industry_capability (
    industry_capability_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    industry_template_id UUID         NOT NULL
        REFERENCES template.industry_template (industry_template_id) ON DELETE CASCADE,
    capability_id        UUID         NOT NULL
        REFERENCES core.capability (capability_id) ON DELETE CASCADE,
    display_order        INTEGER      NOT NULL DEFAULT 100,
    is_required          BOOLEAN      NOT NULL DEFAULT FALSE,
    metadata             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_industry_capability UNIQUE (industry_template_id, capability_id)
);

CREATE INDEX IF NOT EXISTS idx_industry_capability_template
    ON template.industry_capability (industry_template_id);

CREATE INDEX IF NOT EXISTS idx_industry_capability_capability
    ON template.industry_capability (capability_id);

DROP TRIGGER IF EXISTS trg_industry_capability_updated_at ON template.industry_capability;
CREATE TRIGGER trg_industry_capability_updated_at
    BEFORE UPDATE ON template.industry_capability
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

COMMENT ON TABLE template.industry_capability IS
    'Maps industry templates to enabled platform capabilities.';

-- ---------------------------------------------------------------------------
-- 2. AUTOMOBILE_OEM — metadata only (does not alter existing seed UUID/tenant links)
-- ---------------------------------------------------------------------------
UPDATE template.industry_template
SET
    module_code       = 'automotive-oem',
    landing_page      = '/automotive-oem/dashboard',
    ui_module_name    = 'AutomotiveOemModule',
    api_module_name   = 'automotiveOemApi',
    icon_name         = 'car',
    dashboard_component = 'AutomotiveOemDashboard',
    display_order     = 10,
    updated_at        = NOW()
WHERE template_code = 'AUTOMOBILE_OEM';

-- ---------------------------------------------------------------------------
-- 3. ACTIVATED_CARBON — insert if missing; enrich only NULL metadata fields
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
    'a1000000-0000-4000-8000-000000000002',
    'ACTIVATED_CARBON',
    'Activated Carbon Manufacturing',
    'Kiln activation, screening, quality testing, yield analysis, and traceability for activated carbon plants.',
    '1.0.0',
    'activated-carbon',
    '/activated-carbon/dashboard',
    'ActivatedCarbonModule',
    'activatedCarbonApi',
    'factory',
    'ActivatedCarbonDashboard',
    20,
    '{"process_families": ["Pyrolysis", "Activation", "Screening", "QC"], "default_uom": "KG"}'::jsonb
)
ON CONFLICT (template_code) DO NOTHING;

-- Backfill metadata columns only where not already set (preserves existing AC customizations)
UPDATE template.industry_template
SET
    template_name       = COALESCE(template_name, 'Activated Carbon Manufacturing'),
    module_code         = COALESCE(module_code, 'activated-carbon'),
    landing_page        = COALESCE(landing_page, '/activated-carbon/dashboard'),
    ui_module_name      = COALESCE(ui_module_name, 'ActivatedCarbonModule'),
    api_module_name     = COALESCE(api_module_name, 'activatedCarbonApi'),
    icon_name           = COALESCE(icon_name, 'factory'),
    dashboard_component = COALESCE(dashboard_component, 'ActivatedCarbonDashboard'),
    display_order       = CASE
                              WHEN display_order IS NULL OR display_order = 100 THEN 20
                              ELSE display_order
                          END,
    updated_at          = NOW()
WHERE template_code = 'ACTIVATED_CARBON';

-- ---------------------------------------------------------------------------
-- 4. SAM_CARBONS_DEMO tenant (Activated Carbon demo plant)
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
    'b2000000-0000-4000-8000-000000000003',
    'SAM_CARBONS_DEMO',
    'Activated Carbon Demo Plant',
    it.industry_template_id,
    'Asia/Kolkata',
    '{"demo": true, "industry": "ACTIVATED_CARBON"}'::jsonb
FROM template.industry_template it
WHERE it.template_code = 'ACTIVATED_CARBON'
ON CONFLICT (tenant_code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 8. SAM_CARBONS_DEMO_WS workspace
-- ---------------------------------------------------------------------------
INSERT INTO core.project_workspace (
    workspace_id,
    tenant_id,
    workspace_code,
    workspace_name,
    status,
    metadata
)
SELECT
    'e7000000-0000-4000-8000-000000000001',
    t.tenant_id,
    'SAM_CARBONS_DEMO_WS',
    'Activated Carbon Demo Workspace',
    'ACTIVE',
    '{"demo": true, "plant": "Activated Carbon Demo Plant"}'::jsonb
FROM core.tenant t
WHERE t.tenant_code = 'SAM_CARBONS_DEMO'
ON CONFLICT (tenant_id, workspace_code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 7. Seed Activated Carbon capabilities
-- ---------------------------------------------------------------------------
INSERT INTO core.capability (
    capability_id, capability_code, capability_name, description, category, metadata
) VALUES
(
    'f8000000-0000-4000-8000-000000000001',
    'AC_RAW_MATERIAL_INWARD',
    'Raw Material Inward',
    'Log and track inbound raw material receipts.',
    'INBOUND',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000002',
    'AC_RAW_MATERIAL_QC',
    'Raw Material QC',
    'Quality inspection of incoming raw materials.',
    'QUALITY',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000003',
    'AC_KILN_FEED',
    'Kiln Feed',
    'Charge kiln feed batches from prepared raw material.',
    'PRODUCTION',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000004',
    'AC_KILN_ACTIVATION',
    'Kiln Activation',
    'Track pyrolysis and steam activation cycles.',
    'PRODUCTION',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000005',
    'AC_HOURLY_KILN_PARAMETERS',
    'Hourly Kiln Parameters',
    'Capture hourly temperature, pressure, and flow readings.',
    'EXECUTION',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000006',
    'AC_SCREENING',
    'Screening',
    'Size classification and screening operations.',
    'PRODUCTION',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000007',
    'AC_QUALITY_TESTING',
    'Quality Testing',
    'Iodine number, moisture, ash, and batch quality tests.',
    'QUALITY',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000008',
    'AC_YIELD_ANALYSIS',
    'Yield Analysis',
    'Mass-balance and yield analytics across activation batches.',
    'ANALYTICS',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'f8000000-0000-4000-8000-000000000009',
    'AC_TRACEABILITY',
    'Traceability',
    'Batch genealogy from raw material to finished carbon.',
    'TRACEABILITY',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
),
(
    'f8000000-0000-4000-8000-00000000000a',
    'AC_KNOWLEDGE_GRAPH',
    'Knowledge Graph',
    'Ontology and knowledge-graph views for activated carbon workflows.',
    'INTELLIGENCE',
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
)
ON CONFLICT (capability_code) DO NOTHING;

-- Link capabilities to ACTIVATED_CARBON template
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
    '{"industry": "ACTIVATED_CARBON"}'::jsonb
FROM template.industry_template it
CROSS JOIN (VALUES
    ('f9000000-0000-4000-8000-000000000001'::uuid, 'AC_RAW_MATERIAL_INWARD',        10, TRUE),
    ('f9000000-0000-4000-8000-000000000002'::uuid, 'AC_RAW_MATERIAL_QC',            20, TRUE),
    ('f9000000-0000-4000-8000-000000000003'::uuid, 'AC_KILN_FEED',                  30, TRUE),
    ('f9000000-0000-4000-8000-000000000004'::uuid, 'AC_KILN_ACTIVATION',            40, TRUE),
    ('f9000000-0000-4000-8000-000000000005'::uuid, 'AC_HOURLY_KILN_PARAMETERS',     50, FALSE),
    ('f9000000-0000-4000-8000-000000000006'::uuid, 'AC_SCREENING',                  60, TRUE),
    ('f9000000-0000-4000-8000-000000000007'::uuid, 'AC_QUALITY_TESTING',            70, TRUE),
    ('f9000000-0000-4000-8000-000000000008'::uuid, 'AC_YIELD_ANALYSIS',             80, FALSE),
    ('f9000000-0000-4000-8000-000000000009'::uuid, 'AC_TRACEABILITY',               90, TRUE),
    ('f9000000-0000-4000-8000-00000000000a'::uuid, 'AC_KNOWLEDGE_GRAPH',           100, FALSE)
) AS v(industry_capability_id, capability_code, display_order, is_required)
JOIN core.capability c ON c.capability_code = v.capability_code
WHERE it.template_code = 'ACTIVATED_CARBON'
ON CONFLICT (industry_template_id, capability_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 9. Add nullable workspace_id to all tenant-scoped operational tables
--     (backward-compatible — existing rows remain valid with workspace_id NULL)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    r RECORD;
    idx_name TEXT;
BEGIN
    FOR r IN
        SELECT c.table_schema, c.table_name
        FROM information_schema.columns c
        WHERE c.column_name = 'tenant_id'
          AND c.table_schema IN ('mst', 'trn', 'exec', 'qms', 'kg')
          AND NOT EXISTS (
              SELECT 1
              FROM information_schema.columns c2
              WHERE c2.table_schema = c.table_schema
                AND c2.table_name = c.table_name
                AND c2.column_name = 'workspace_id'
          )
        GROUP BY c.table_schema, c.table_name
        ORDER BY c.table_schema, c.table_name
    LOOP
        EXECUTE format(
            'ALTER TABLE %I.%I ADD COLUMN IF NOT EXISTS workspace_id UUID '
            'REFERENCES core.project_workspace (workspace_id)',
            r.table_schema,
            r.table_name
        );

        idx_name := format('idx_%s_%s_workspace', r.table_schema, r.table_name);
        IF length(idx_name) > 63 THEN
            idx_name := format('idx_%s_ws', replace(r.table_schema || '_' || r.table_name, '.', '_'));
        END IF;

        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I.%I (workspace_id)',
            idx_name,
            r.table_schema,
            r.table_name
        );
    END LOOP;
END $$;

-- Composite indexes for tenant + workspace scoping (future queries)
DO $$
DECLARE
    r RECORD;
    idx_name TEXT;
BEGIN
    FOR r IN
        SELECT c.table_schema, c.table_name
        FROM information_schema.columns c
        WHERE c.column_name = 'tenant_id'
          AND c.table_schema IN ('mst', 'trn', 'exec', 'qms', 'kg')
          AND EXISTS (
              SELECT 1
              FROM information_schema.columns c2
              WHERE c2.table_schema = c.table_schema
                AND c2.table_name = c.table_name
                AND c2.column_name = 'workspace_id'
          )
        GROUP BY c.table_schema, c.table_name
        ORDER BY c.table_schema, c.table_name
    LOOP
        idx_name := format('idx_%s_%s_tenant_workspace', r.table_schema, r.table_name);
        IF length(idx_name) > 63 THEN
            idx_name := format('idx_%s_tw', replace(r.table_schema || '_' || r.table_name, '.', '_'));
        END IF;

        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I.%I (tenant_id, workspace_id)',
            idx_name,
            r.table_schema,
            r.table_name
        );
    END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 10. Ensure indexes on tenant_id, workspace_id, industry_template_code,
--     template_code, capability_code
-- ---------------------------------------------------------------------------
-- industry_template_code is stored as template_code on template.industry_template
CREATE INDEX IF NOT EXISTS idx_industry_template_code
    ON template.industry_template (template_code);

CREATE INDEX IF NOT EXISTS idx_industry_template_display_order
    ON template.industry_template (display_order, template_code);

CREATE INDEX IF NOT EXISTS idx_tenant_code
    ON core.tenant (tenant_code);

-- Resolve tenant -> industry template code without redundant joins in hot paths
CREATE INDEX IF NOT EXISTS idx_tenant_industry_template_code
    ON core.tenant (industry_template_id);

-- Ensure tenant_id indexes on all tenant-scoped tables (including core.* if applicable)
DO $$
DECLARE
    r RECORD;
    idx_name TEXT;
BEGIN
    FOR r IN
        SELECT c.table_schema, c.table_name
        FROM information_schema.columns c
        WHERE c.column_name = 'tenant_id'
          AND c.table_schema IN ('core', 'mst', 'trn', 'exec', 'qms', 'kg')
        GROUP BY c.table_schema, c.table_name
        ORDER BY c.table_schema, c.table_name
    LOOP
        idx_name := format('idx_%s_%s_tenant', r.table_schema, r.table_name);
        IF length(idx_name) > 63 THEN
            idx_name := format('idx_%s_t', replace(r.table_schema || '_' || r.table_name, '.', '_'));
        END IF;

        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS %I ON %I.%I (tenant_id)',
            idx_name,
            r.table_schema,
            r.table_name
        );
    END LOOP;
END $$;

COMMIT;

-- ---------------------------------------------------------------------------
-- Post-migration verification (optional — run manually)
-- ---------------------------------------------------------------------------
-- SELECT template_code, module_code, landing_page, display_order
-- FROM template.industry_template
-- ORDER BY display_order, template_code;
--
-- SELECT t.tenant_code, it.template_code AS industry_template_code
-- FROM core.tenant t
-- JOIN template.industry_template it ON it.industry_template_id = t.industry_template_id
-- WHERE t.tenant_code IN ('AUTO_OEM_DEMO', 'SAM_CARBONS_DEMO');
--
-- SELECT pw.workspace_code, t.tenant_code
-- FROM core.project_workspace pw
-- JOIN core.tenant t ON t.tenant_id = pw.tenant_id
-- WHERE pw.workspace_code = 'SAM_CARBONS_DEMO_WS';
--
-- SELECT it.template_code, c.capability_code
-- FROM template.industry_capability ic
-- JOIN template.industry_template it ON it.industry_template_id = ic.industry_template_id
-- JOIN core.capability c ON c.capability_id = ic.capability_id
-- WHERE it.template_code = 'ACTIVATED_CARBON'
-- ORDER BY ic.display_order;
