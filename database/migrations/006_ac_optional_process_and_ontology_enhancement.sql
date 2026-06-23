-- =============================================================================
-- Migration 006: AC optional process steps + ontology traceability (additive)
-- =============================================================================
-- Database : nyra_mes_core
-- Purpose  : Support optional post-screening process steps for Activated Carbon,
--            strengthen parameter/execution metadata, and additive KG traceability
--            without duplicating existing mes_core structures.
--
-- Rules:
--   - nyra_mes_core ONLY — does not touch legacy oemauto or any other database
--   - No DROP / DELETE / RENAME of existing tables, columns, sequences,
--     views, functions, triggers, or seed data
--   - Reuses mst.routing_operation, mst.routing_operation_parameter,
--     exec.operation_execution, exec.parameter_reading, kg.triple_store_staging
--   - Default AC flows unchanged; optional ops seeded with is_optional = TRUE
--   - Safe to re-run (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS / ON CONFLICT)
--   - Do NOT run against live / production RDS unless explicitly approved
--   - No nyra-mes-api or nyra-mes-ui code changes required for this script
--
-- Run manually:
--   psql -d nyra_mes_core -f database/migrations/006_ac_optional_process_and_ontology_enhancement.sql
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Extend mst.routing_operation — mandatory / optional step flags
-- ---------------------------------------------------------------------------
ALTER TABLE mst.routing_operation
    ADD COLUMN IF NOT EXISTS is_mandatory                 BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS is_optional                  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS insert_after_operation_code  VARCHAR(64);

COMMENT ON COLUMN mst.routing_operation.is_mandatory IS
    'TRUE for steps required in the default manufacturing flow';
COMMENT ON COLUMN mst.routing_operation.is_optional IS
    'TRUE for optional post-screening (or customer-specific) steps that may be skipped';
COMMENT ON COLUMN mst.routing_operation.insert_after_operation_code IS
    'When is_optional=TRUE, anchor operation_code after which this step may be inserted';

-- Backfill: all existing operations are mandatory, non-optional
UPDATE mst.routing_operation
SET is_mandatory = TRUE,
    is_optional  = FALSE,
    updated_at   = NOW()
WHERE is_mandatory IS DISTINCT FROM TRUE
   OR is_optional IS DISTINCT FROM FALSE;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_routing_operation_optional_flags'
          AND conrelid = 'mst.routing_operation'::regclass
    ) THEN
        ALTER TABLE mst.routing_operation
            ADD CONSTRAINT chk_routing_operation_optional_flags CHECK (
                NOT (is_mandatory = TRUE AND is_optional = TRUE)
            );
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Extend mst.routing_operation_parameter — dropdown + report visibility
-- ---------------------------------------------------------------------------
ALTER TABLE mst.routing_operation_parameter
    ADD COLUMN IF NOT EXISTS dropdown_options JSONB,
    ADD COLUMN IF NOT EXISTS show_in_report    BOOLEAN NOT NULL DEFAULT TRUE;

COMMENT ON COLUMN mst.routing_operation_parameter.dropdown_options IS
    'JSON array of allowed values when data_type = DROPDOWN';
COMMENT ON COLUMN mst.routing_operation_parameter.show_in_report IS
    'When FALSE, parameter is hidden from standard AC process reports';

-- Normalize legacy data_type values before CHECK constraint
UPDATE mst.routing_operation_parameter
SET data_type = CASE UPPER(TRIM(data_type))
    WHEN 'TEXT' THEN 'TEXT'
    WHEN 'STRING' THEN 'TEXT'
    WHEN 'NUMERIC' THEN 'NUMBER'
    WHEN 'NUMBER' THEN 'NUMBER'
    WHEN 'INT' THEN 'NUMBER'
    WHEN 'INTEGER' THEN 'NUMBER'
    WHEN 'FLOAT' THEN 'NUMBER'
    WHEN 'DECIMAL' THEN 'NUMBER'
    WHEN 'DATE' THEN 'DATE'
    WHEN 'DATETIME' THEN 'DATE'
    WHEN 'BOOL' THEN 'BOOLEAN'
    WHEN 'BOOLEAN' THEN 'BOOLEAN'
    WHEN 'SELECT' THEN 'DROPDOWN'
    WHEN 'DROPDOWN' THEN 'DROPDOWN'
    WHEN 'REMARK' THEN 'REMARKS'
    WHEN 'REMARKS' THEN 'REMARKS'
    WHEN 'NOTE' THEN 'REMARKS'
    WHEN 'NOTES' THEN 'REMARKS'
    ELSE 'TEXT'
END,
    updated_at = NOW()
WHERE data_type IS NOT NULL
  AND TRIM(data_type) <> '';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_parameter_data_type'
          AND conrelid = 'mst.routing_operation_parameter'::regclass
    ) THEN
        ALTER TABLE mst.routing_operation_parameter
            ADD CONSTRAINT chk_parameter_data_type CHECK (
                data_type IS NULL
                OR data_type IN ('TEXT', 'NUMBER', 'DATE', 'BOOLEAN', 'DROPDOWN', 'REMARKS')
            );
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 3. Extend exec.operation_execution — operator + remarks
-- ---------------------------------------------------------------------------
ALTER TABLE exec.operation_execution
    ADD COLUMN IF NOT EXISTS operator_code VARCHAR(64),
    ADD COLUMN IF NOT EXISTS remarks       TEXT;

COMMENT ON COLUMN exec.operation_execution.operator_code IS
    'Operator identifier for this process execution (work order)';
COMMENT ON COLUMN exec.operation_execution.remarks IS
    'Free-text remarks for the process execution';

-- ---------------------------------------------------------------------------
-- 4. Extend exec.parameter_reading — link to parameter definition + recorder
-- ---------------------------------------------------------------------------
ALTER TABLE exec.parameter_reading
    ADD COLUMN IF NOT EXISTS routing_operation_parameter_id UUID
        REFERENCES mst.routing_operation_parameter (id),
    ADD COLUMN IF NOT EXISTS recorded_by VARCHAR(128);

CREATE INDEX IF NOT EXISTS idx_parameter_reading_routing_operation_parameter
    ON exec.parameter_reading (routing_operation_parameter_id);

COMMENT ON COLUMN exec.parameter_reading.routing_operation_parameter_id IS
    'Optional FK to mst.routing_operation_parameter for typed capture linkage';
COMMENT ON COLUMN exec.parameter_reading.recorded_by IS
    'Operator who recorded this parameter value';

-- ---------------------------------------------------------------------------
-- 5. Seed optional AC template operations (post-screening, skippable)
-- ---------------------------------------------------------------------------
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
    is_mandatory,
    is_optional,
    insert_after_operation_code,
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
    FALSE,
    TRUE,
    FALSE,
    TRUE,
    'AC-OP-SCREENING',
    'ACTIVATED_CARBON',
    v.operation_code,
    FALSE,
    jsonb_build_object(
        'process_step', v.process_step,
        'industry_template_code', 'ACTIVATED_CARBON',
        'is_optional_process', TRUE
    )
FROM mst.routing r
JOIN core.tenant t ON t.tenant_id = r.tenant_id
CROSS JOIN (VALUES
    (
        '34000000-0000-4000-8000-000000000501'::uuid,
        'AC-OP-OPT-INSPECTION',
        75,
        'Optional Inspection',
        'QUALITY',
        TRUE,
        'OPTIONAL_INSPECTION'
    ),
    (
        '34000000-0000-4000-8000-000000000502'::uuid,
        'AC-OP-OPT-REPROCESSING',
        76,
        'Optional Reprocessing',
        'PRODUCTION',
        FALSE,
        'OPTIONAL_REPROCESSING'
    ),
    (
        '34000000-0000-4000-8000-000000000503'::uuid,
        'AC-OP-OPT-DRYING',
        77,
        'Optional Drying',
        'PRODUCTION',
        FALSE,
        'OPTIONAL_DRYING'
    ),
    (
        '34000000-0000-4000-8000-000000000504'::uuid,
        'AC-OP-OPT-ADDITIONAL-COOLING',
        78,
        'Optional Additional Cooling',
        'PRODUCTION',
        FALSE,
        'OPTIONAL_COOLING'
    ),
    (
        '34000000-0000-4000-8000-000000000505'::uuid,
        'AC-OP-OPT-CUSTOMER-PROCESS',
        79,
        'Customer-Specific Process',
        'PRODUCTION',
        FALSE,
        'OPTIONAL_CUSTOMER_PROCESS'
    )
) AS v(
    routing_operation_id,
    operation_code,
    operation_seq,
    operation_name,
    operation_type,
    is_quality_gate,
    process_step
)
WHERE t.tenant_code = 'SAM_CARBONS'
  AND r.routing_code = 'AC_STANDARD_PROCESS'
  AND r.is_template_route = TRUE
ON CONFLICT (tenant_id, routing_id, operation_code) DO NOTHING;

-- Same optional ops for SAM_CARBONS_DEMO (if template route exists)
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
    is_mandatory,
    is_optional,
    insert_after_operation_code,
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
    FALSE,
    TRUE,
    FALSE,
    TRUE,
    'AC-OP-SCREENING',
    'ACTIVATED_CARBON',
    v.operation_code,
    FALSE,
    jsonb_build_object(
        'process_step', v.process_step,
        'industry_template_code', 'ACTIVATED_CARBON',
        'is_optional_process', TRUE
    )
FROM mst.routing r
JOIN core.tenant t ON t.tenant_id = r.tenant_id
CROSS JOIN (VALUES
    (
        '34000000-0000-4000-8000-000000000601'::uuid,
        'AC-OP-OPT-INSPECTION',
        75,
        'Optional Inspection',
        'QUALITY',
        TRUE,
        'OPTIONAL_INSPECTION'
    ),
    (
        '34000000-0000-4000-8000-000000000602'::uuid,
        'AC-OP-OPT-REPROCESSING',
        76,
        'Optional Reprocessing',
        'PRODUCTION',
        FALSE,
        'OPTIONAL_REPROCESSING'
    ),
    (
        '34000000-0000-4000-8000-000000000603'::uuid,
        'AC-OP-OPT-DRYING',
        77,
        'Optional Drying',
        'PRODUCTION',
        FALSE,
        'OPTIONAL_DRYING'
    ),
    (
        '34000000-0000-4000-8000-000000000604'::uuid,
        'AC-OP-OPT-ADDITIONAL-COOLING',
        78,
        'Optional Additional Cooling',
        'PRODUCTION',
        FALSE,
        'OPTIONAL_COOLING'
    ),
    (
        '34000000-0000-4000-8000-000000000605'::uuid,
        'AC-OP-OPT-CUSTOMER-PROCESS',
        79,
        'Customer-Specific Process',
        'PRODUCTION',
        FALSE,
        'OPTIONAL_CUSTOMER_PROCESS'
    )
) AS v(
    routing_operation_id,
    operation_code,
    operation_seq,
    operation_name,
    operation_type,
    is_quality_gate,
    process_step
)
WHERE t.tenant_code = 'SAM_CARBONS_DEMO'
  AND r.routing_code = 'AC_STANDARD_PROCESS'
  AND r.is_template_route = TRUE
ON CONFLICT (tenant_id, routing_id, operation_code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. Seed configurable parameters for optional operations (template route)
-- ---------------------------------------------------------------------------
INSERT INTO mst.routing_operation_parameter (
    id,
    tenant_id,
    workspace_id,
    routing_operation_id,
    parameter_code,
    parameter_name,
    data_type,
    unit,
    is_mandatory,
    display_order,
    is_active,
    show_in_report,
    dropdown_options
)
SELECT
    v.id,
    ro.tenant_id,
    NULL,
    ro.routing_operation_id,
    v.parameter_code,
    v.parameter_name,
    v.data_type,
    v.unit,
    v.is_mandatory,
    v.display_order,
    TRUE,
    v.show_in_report,
    v.dropdown_options::jsonb
FROM mst.routing_operation ro
JOIN mst.routing r ON r.routing_id = ro.routing_id
JOIN core.tenant t ON t.tenant_id = ro.tenant_id
CROSS JOIN (VALUES
    -- Optional Inspection
    ('35000000-0000-4000-8000-000000000501'::uuid, 'AC-OP-OPT-INSPECTION', 'INSPECTION_RESULT', 'Inspection Result', 'DROPDOWN', NULL, TRUE, 10, TRUE, '["PASS","FAIL","HOLD"]'),
    ('35000000-0000-4000-8000-000000000502'::uuid, 'AC-OP-OPT-INSPECTION', 'INSPECTION_REMARKS', 'Inspection Remarks', 'REMARKS', NULL, FALSE, 20, TRUE, NULL),
    ('35000000-0000-4000-8000-000000000503'::uuid, 'AC-OP-OPT-INSPECTION', 'INSPECTOR', 'Inspector', 'TEXT', NULL, FALSE, 30, TRUE, NULL),
    -- Optional Reprocessing
    ('35000000-0000-4000-8000-000000000511'::uuid, 'AC-OP-OPT-REPROCESSING', 'REPROCESS_REASON', 'Reprocess Reason', 'DROPDOWN', NULL, TRUE, 10, TRUE, '["OFF_SPEC_MESH","HIGH_ASH","LOW_CTC","CUSTOMER_REQUEST","OTHER"]'),
    ('35000000-0000-4000-8000-000000000512'::uuid, 'AC-OP-OPT-REPROCESSING', 'REPROCESS_QTY', 'Reprocess Quantity', 'NUMBER', 'kg', TRUE, 20, TRUE, NULL),
    ('35000000-0000-4000-8000-000000000513'::uuid, 'AC-OP-OPT-REPROCESSING', 'REPROCESS_REMARKS', 'Reprocess Remarks', 'REMARKS', NULL, FALSE, 30, TRUE, NULL),
    -- Optional Drying
    ('35000000-0000-4000-8000-000000000521'::uuid, 'AC-OP-OPT-DRYING', 'DRYING_TEMP', 'Drying Temperature', 'NUMBER', 'C', TRUE, 10, TRUE, NULL),
    ('35000000-0000-4000-8000-000000000522'::uuid, 'AC-OP-OPT-DRYING', 'DRYING_DURATION', 'Drying Duration', 'NUMBER', 'min', TRUE, 20, TRUE, NULL),
    ('35000000-0000-4000-8000-000000000523'::uuid, 'AC-OP-OPT-DRYING', 'DRYING_REMARKS', 'Drying Remarks', 'REMARKS', NULL, FALSE, 30, TRUE, NULL),
    -- Optional Additional Cooling
    ('35000000-0000-4000-8000-000000000531'::uuid, 'AC-OP-OPT-ADDITIONAL-COOLING', 'COOLING_END_TEMP', 'Cooling End Temperature', 'NUMBER', 'C', TRUE, 10, TRUE, NULL),
    ('35000000-0000-4000-8000-000000000532'::uuid, 'AC-OP-OPT-ADDITIONAL-COOLING', 'COOLING_REMARKS', 'Cooling Remarks', 'REMARKS', NULL, FALSE, 20, TRUE, NULL),
    -- Customer-specific
    ('35000000-0000-4000-8000-000000000541'::uuid, 'AC-OP-OPT-CUSTOMER-PROCESS', 'CUSTOM_PROCESS_NAME', 'Custom Process Name', 'TEXT', NULL, TRUE, 10, TRUE, NULL),
    ('35000000-0000-4000-8000-000000000542'::uuid, 'AC-OP-OPT-CUSTOMER-PROCESS', 'CUSTOM_PROCESS_RESULT', 'Custom Process Result', 'TEXT', NULL, FALSE, 20, TRUE, NULL),
    ('35000000-0000-4000-8000-000000000543'::uuid, 'AC-OP-OPT-CUSTOMER-PROCESS', 'CUSTOM_REMARKS', 'Custom Remarks', 'REMARKS', NULL, FALSE, 30, TRUE, NULL)
) AS v(
    id,
    operation_code,
    parameter_code,
    parameter_name,
    data_type,
    unit,
    is_mandatory,
    display_order,
    show_in_report,
    dropdown_options
)
WHERE t.tenant_code IN ('SAM_CARBONS', 'SAM_CARBONS_DEMO')
  AND r.routing_code = 'AC_STANDARD_PROCESS'
  AND r.is_template_route = TRUE
  AND ro.operation_code = v.operation_code
  AND NOT EXISTS (
      SELECT 1
      FROM mst.routing_operation_parameter existing
      WHERE existing.tenant_id = ro.tenant_id
        AND existing.routing_operation_id = ro.routing_operation_id
        AND existing.parameter_code = v.parameter_code
  );

-- ---------------------------------------------------------------------------
-- 7. KG traceability helper + reporting schema (additive views only)
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS reporting;

COMMENT ON SCHEMA reporting IS
    'Additive reporting views for Activated Carbon — does not replace legacy reports';

CREATE OR REPLACE FUNCTION kg.upsert_traceability_triple(
    p_tenant_id       UUID,
    p_workspace_id    UUID,
    p_subject_uri     TEXT,
    p_predicate_uri   TEXT,
    p_object_uri      TEXT DEFAULT NULL,
    p_object_literal  TEXT DEFAULT NULL,
    p_object_datatype TEXT DEFAULT NULL,
    p_source_table    TEXT DEFAULT NULL,
    p_source_id       UUID DEFAULT NULL
)
RETURNS UUID
LANGUAGE plpgsql
AS $$
DECLARE
    v_triple_id UUID;
BEGIN
    SELECT triple_id
    INTO v_triple_id
    FROM kg.triple_store_staging
    WHERE tenant_id = p_tenant_id
      AND subject_uri = p_subject_uri
      AND predicate_uri = p_predicate_uri
      AND COALESCE(object_uri, '') = COALESCE(p_object_uri, '')
      AND COALESCE(object_literal, '') = COALESCE(p_object_literal, '')
    LIMIT 1;

    IF v_triple_id IS NOT NULL THEN
        UPDATE kg.triple_store_staging
        SET workspace_id    = COALESCE(p_workspace_id, workspace_id),
            object_datatype = COALESCE(p_object_datatype, object_datatype),
            source_table    = COALESCE(p_source_table, source_table),
            source_id       = COALESCE(p_source_id, source_id),
            updated_at      = NOW()
        WHERE triple_id = v_triple_id;
        RETURN v_triple_id;
    END IF;

    INSERT INTO kg.triple_store_staging (
        tenant_id,
        workspace_id,
        subject_uri,
        predicate_uri,
        object_uri,
        object_literal,
        object_datatype,
        source_table,
        source_id
    )
    VALUES (
        p_tenant_id,
        p_workspace_id,
        p_subject_uri,
        p_predicate_uri,
        p_object_uri,
        p_object_literal,
        p_object_datatype,
        p_source_table,
        p_source_id
    )
    RETURNING triple_id INTO v_triple_id;

    RETURN v_triple_id;
END;
$$;

COMMENT ON FUNCTION kg.upsert_traceability_triple IS
    'Idempotent Subject → Predicate → Object upsert into kg.triple_store_staging';

CREATE OR REPLACE VIEW reporting.v_ac_standard_predicates AS
SELECT *
FROM (VALUES
    ('urn:nyra:predicate:supplies',       'supplies',       'Supplier → Raw Material Batch'),
    ('urn:nyra:predicate:issued_to',      'issued to',      'Raw Material Batch → Kiln'),
    ('urn:nyra:predicate:produces',       'produces',       'Kiln Batch → Finished Goods Batch'),
    ('urn:nyra:predicate:captures',       'captures',       'Routing Operation → Operation Parameter'),
    ('urn:nyra:predicate:executes',       'executes',       'Work Order → Routing Operation'),
    ('urn:nyra:predicate:dispatched_to',  'dispatched to',  'Finished Goods Bag → Customer'),
    ('urn:nyra:predicate:sold_as',        'sold as',        'Scrap Material → Scrap Dispatch'),
    ('urn:nyra:predicate:undergoes',      'undergoes',      'Production Lot → Optional Process'),
    ('urn:nyra:predicate:tested_by',      'tested by',      'Production Lot → Quality Check')
) AS t(predicate_uri, predicate_label, description);

COMMENT ON VIEW reporting.v_ac_standard_predicates IS
    'Canonical AC traceability predicates for triplet ontology (no base-table changes)';

CREATE OR REPLACE VIEW reporting.v_ac_process_execution AS
SELECT
    t.tenant_code,
    pl.lot_code,
    pl.production_lot_id,
    r.routing_code,
    ro.operation_code,
    ro.operation_name,
    ro.operation_sequence,
    ro.is_mandatory,
    ro.is_optional,
    ro.is_active,
    ro.metadata ->> 'process_step' AS process_step,
    oe.execution_code,
    oe.status AS execution_status,
    oe.operator_code,
    oe.started_at,
    oe.completed_at,
    oe.remarks,
    rop.parameter_code,
    rop.parameter_name,
    rop.data_type,
    rop.is_mandatory AS parameter_mandatory,
    rop.show_in_report,
    pr.reading_value,
    pr.reading_text,
    pr.uom,
    pr.recorded_by,
    pr.recorded_at
FROM exec.operation_execution oe
JOIN trn.production_lot pl ON pl.production_lot_id = oe.production_lot_id
JOIN core.tenant t ON t.tenant_id = oe.tenant_id
JOIN mst.routing_operation ro ON ro.routing_operation_id = oe.routing_operation_id
JOIN mst.routing r ON r.routing_id = ro.routing_id
LEFT JOIN exec.parameter_reading pr ON pr.execution_id = oe.execution_id
LEFT JOIN mst.routing_operation_parameter rop
    ON rop.id = pr.routing_operation_parameter_id
    OR (
        pr.routing_operation_parameter_id IS NULL
        AND rop.routing_operation_id = ro.routing_operation_id
        AND rop.parameter_code = pr.parameter_code
    )
WHERE COALESCE(r.industry_template_code, ro.industry_template_code) = 'ACTIVATED_CARBON'
   OR (ro.metadata ->> 'industry_template_code') = 'ACTIVATED_CARBON';

COMMENT ON VIEW reporting.v_ac_process_execution IS
    'AC lot process execution with parameters — filters report-visible fields via show_in_report';

CREATE OR REPLACE VIEW reporting.v_ac_lot_traceability AS
SELECT
    t.tenant_code,
    pl.lot_code,
    pl.production_lot_id,
    ts.subject_uri,
    ts.predicate_uri,
    sp.predicate_label,
    ts.object_uri,
    ts.object_literal,
    ts.source_table,
    ts.source_id,
    ts.created_at AS triple_created_at
FROM kg.triple_store_staging ts
JOIN core.tenant t ON t.tenant_id = ts.tenant_id
JOIN trn.production_lot pl
    ON ts.subject_uri = ('urn:nyra:ac:lot:' || pl.lot_code)
    OR ts.object_uri = ('urn:nyra:ac:lot:' || pl.lot_code)
    OR ts.subject_uri LIKE ('urn:nyra:ac:execution:%')
LEFT JOIN reporting.v_ac_standard_predicates sp
    ON sp.predicate_uri = ts.predicate_uri
WHERE ts.subject_uri LIKE 'urn:nyra:ac:%'
   OR ts.object_uri LIKE 'urn:nyra:ac:%'
   OR ts.predicate_uri LIKE 'urn:nyra:predicate:%';

COMMENT ON VIEW reporting.v_ac_lot_traceability IS
    'Lot-centric view of AC traceability triples from kg.triple_store_staging';

COMMIT;
