-- =============================================================================
-- Nyra MES Core — Fresh PostgreSQL database setup
-- =============================================================================
-- Database     : nyra_mes_core  (NEW — does not modify any existing database)
-- Purpose      : Multi-tenant MES platform with pluggable industry templates
-- First template: AUTOMOBILE_OEM (Activated Carbon, Foundry, Textile, etc.
--                are added as new template.industry_template rows — no DDL change)
--
-- How to run in DBeaver
-- ---------------------
-- Step 1 (optional, as superuser on database "postgres"):
--   Execute ONLY the "CREATE DATABASE" block below if nyra_mes_core does not exist.
-- Step 2: Connect DBeaver to database nyra_mes_core.
-- Step 3: Execute the remainder of this script (from extensions onward).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- STEP 1 — Run while connected to "postgres" (or another admin DB), NOT inside
--           a transaction. Skip if nyra_mes_core already exists.
-- -----------------------------------------------------------------------------
-- CREATE DATABASE nyra_mes_core
--     WITH ENCODING = 'UTF8'
--          LC_COLLATE = 'en_US.UTF-8'
--          LC_CTYPE = 'en_US.UTF-8'
--          TEMPLATE = template0;
--
-- On Windows-hosted Postgres you may use: LC_COLLATE = 'English_United States.1252'

-- =============================================================================
-- STEP 2+ — Connect to nyra_mes_core before running everything below
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ---------------------------------------------------------------------------
-- Schemas
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS template;
CREATE SCHEMA IF NOT EXISTS ont;
CREATE SCHEMA IF NOT EXISTS mst;
CREATE SCHEMA IF NOT EXISTS trn;
CREATE SCHEMA IF NOT EXISTS exec;
CREATE SCHEMA IF NOT EXISTS qms;
CREATE SCHEMA IF NOT EXISTS kg;

COMMENT ON SCHEMA core     IS 'Tenancy, identity, and cross-tenant platform metadata';
COMMENT ON SCHEMA template IS 'Industry templates (AUTOMOBILE_OEM, FOUNDRY, TEXTILE, …)';
COMMENT ON SCHEMA ont      IS 'Ontology / semantic graph metadata (RDF-ready, industry-agnostic)';
COMMENT ON SCHEMA mst      IS 'Master data — tenant-scoped';
COMMENT ON SCHEMA trn      IS 'Transactional manufacturing documents — tenant-scoped';
COMMENT ON SCHEMA exec     IS 'Shop-floor execution events — tenant-scoped';
COMMENT ON SCHEMA qms      IS 'Quality management — tenant-scoped';
COMMENT ON SCHEMA kg       IS 'Knowledge graph staging (triples export/import)';

-- ---------------------------------------------------------------------------
-- Business code sequences — numeric suffix from PostgreSQL nextval only (not app logic).
-- Example: SELECT nextval('core.customer_code_seq') -> 1  =>  customer_code 'CUST00001'
-- ---------------------------------------------------------------------------
CREATE SEQUENCE IF NOT EXISTS core.customer_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.product_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.resource_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.equipment_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.routing_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.routing_operation_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.customer_order_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.customer_order_line_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.production_order_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.lot_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.feasibility_check_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.execution_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.schedule_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.quality_check_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.ncr_code_seq START 1;
CREATE SEQUENCE IF NOT EXISTS core.dispatch_code_seq START 1;

-- ---------------------------------------------------------------------------
-- Shared trigger: maintain updated_at
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

-- =============================================================================
-- CORE & TEMPLATE
-- =============================================================================

CREATE TABLE template.industry_template (
    industry_template_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_code        VARCHAR(64)  NOT NULL,
    template_name        VARCHAR(256) NOT NULL,
    description          TEXT,
    template_version     VARCHAR(32)  NOT NULL DEFAULT '1.0.0',
    is_active            BOOLEAN      NOT NULL DEFAULT TRUE,
    metadata             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_industry_template_code UNIQUE (template_code)
);

CREATE TRIGGER trg_industry_template_updated_at
    BEFORE UPDATE ON template.industry_template
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

COMMENT ON TABLE template.industry_template IS
    'Catalog of industry templates. New industries = new rows (no schema migration).';

CREATE TABLE core.tenant (
    tenant_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_code          VARCHAR(64)  NOT NULL,
    tenant_name          VARCHAR(256) NOT NULL,
    industry_template_id UUID         NOT NULL
        REFERENCES template.industry_template (industry_template_id),
    status               VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE',
    timezone             VARCHAR(64)  NOT NULL DEFAULT 'UTC',
    metadata             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tenant_code UNIQUE (tenant_code),
    CONSTRAINT chk_tenant_status CHECK (status IN ('ACTIVE', 'SUSPENDED', 'ARCHIVED'))
);

CREATE INDEX idx_tenant_industry_template ON core.tenant (industry_template_id);

CREATE TRIGGER trg_tenant_updated_at
    BEFORE UPDATE ON core.tenant
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE core.app_user (
    user_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cognito_sub  VARCHAR(128),
    email        VARCHAR(320) NOT NULL,
    display_name VARCHAR(256),
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,
    metadata     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_app_user_email UNIQUE (email),
    CONSTRAINT uq_app_user_cognito_sub UNIQUE (cognito_sub)
);

CREATE TRIGGER trg_app_user_updated_at
    BEFORE UPDATE ON core.app_user
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE core.user_tenant_access (
    access_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID        NOT NULL REFERENCES core.app_user (user_id) ON DELETE CASCADE,
    tenant_id    UUID        NOT NULL REFERENCES core.tenant (tenant_id) ON DELETE CASCADE,
    role_code    VARCHAR(64) NOT NULL,
    is_default   BOOLEAN     NOT NULL DEFAULT FALSE,
    granted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_tenant UNIQUE (user_id, tenant_id),
    CONSTRAINT chk_user_role CHECK (
        role_code IN ('MES_Admin', 'MES_Planner', 'MES_Operator', 'MES_Quality', 'MES_Viewer')
    )
);

CREATE INDEX idx_user_tenant_access_tenant ON core.user_tenant_access (tenant_id);
CREATE INDEX idx_user_tenant_access_user   ON core.user_tenant_access (user_id);

CREATE TRIGGER trg_user_tenant_access_updated_at
    BEFORE UPDATE ON core.user_tenant_access
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

-- Ontology schema placeholder (industry-agnostic semantic layer; populated by app/ETL)
COMMENT ON SCHEMA ont IS 'Future: ont.class, ont.relationship, ont.entity_mapping — no tables required at bootstrap';

-- =============================================================================
-- MASTER DATA (mst.*) — all tenant-scoped
-- =============================================================================

CREATE TABLE mst.customer (
    customer_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    customer_code VARCHAR(64)  NOT NULL,
    customer_name VARCHAR(256) NOT NULL,
    status        VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE',
    metadata      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_customer_code UNIQUE (tenant_id, customer_code)
);

CREATE INDEX idx_customer_tenant ON mst.customer (tenant_id);

CREATE TRIGGER trg_customer_updated_at
    BEFORE UPDATE ON mst.customer
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE mst.product (
    product_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID          NOT NULL REFERENCES core.tenant (tenant_id),
    product_code  VARCHAR(64)   NOT NULL,
    product_name  VARCHAR(256)  NOT NULL,
    product_type  VARCHAR(64),
    uom           VARCHAR(16)   NOT NULL DEFAULT 'EA',
    status        VARCHAR(32)   NOT NULL DEFAULT 'ACTIVE',
    metadata      JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_product_code UNIQUE (tenant_id, product_code)
);

CREATE INDEX idx_product_tenant ON mst.product (tenant_id);

CREATE TRIGGER trg_product_updated_at
    BEFORE UPDATE ON mst.product
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE mst.resource (
    resource_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    resource_code VARCHAR(64)  NOT NULL,
    resource_name VARCHAR(256) NOT NULL,
    resource_type VARCHAR(64)  NOT NULL,
    status        VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE',
    metadata      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_resource_code UNIQUE (tenant_id, resource_code),
    CONSTRAINT chk_resource_type CHECK (
        resource_type IN ('MACHINE', 'LABOR', 'TOOL', 'MATERIAL', 'WORKCELL', 'OTHER')
    )
);

CREATE INDEX idx_resource_tenant ON mst.resource (tenant_id);
CREATE INDEX idx_resource_type   ON mst.resource (tenant_id, resource_type);

CREATE TRIGGER trg_resource_updated_at
    BEFORE UPDATE ON mst.resource
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE mst.equipment (
    equipment_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    equipment_code VARCHAR(64)  NOT NULL,
    equipment_name VARCHAR(256) NOT NULL,
    resource_id    UUID         REFERENCES mst.resource (resource_id),
    equipment_type VARCHAR(64),
    status         VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE',
    metadata       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_equipment_code UNIQUE (tenant_id, equipment_code)
);

CREATE INDEX idx_equipment_tenant   ON mst.equipment (tenant_id);
CREATE INDEX idx_equipment_resource ON mst.equipment (resource_id);

CREATE TRIGGER trg_equipment_updated_at
    BEFORE UPDATE ON mst.equipment
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE mst.routing (
    routing_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    routing_code    VARCHAR(64)  NOT NULL,
    product_id      UUID         NOT NULL REFERENCES mst.product (product_id),
    routing_version VARCHAR(32)  NOT NULL DEFAULT '1',
    process_family  VARCHAR(64),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    metadata        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_routing_code UNIQUE (tenant_id, routing_code)
);

CREATE INDEX idx_routing_tenant  ON mst.routing (tenant_id);
CREATE INDEX idx_routing_product ON mst.routing (tenant_id, product_id);

CREATE TRIGGER trg_routing_updated_at
    BEFORE UPDATE ON mst.routing
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE mst.routing_operation (
    routing_operation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID          NOT NULL REFERENCES core.tenant (tenant_id),
    routing_id           UUID          NOT NULL REFERENCES mst.routing (routing_id) ON DELETE CASCADE,
    operation_code       VARCHAR(64)   NOT NULL,
    operation_sequence   INTEGER       NOT NULL,
    operation_name       VARCHAR(256)  NOT NULL,
    standard_cycle_min   NUMERIC(12,4),
    metadata             JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_routing_operation_code UNIQUE (tenant_id, routing_id, operation_code),
    CONSTRAINT uq_routing_operation_seq  UNIQUE (tenant_id, routing_id, operation_sequence),
    CONSTRAINT chk_routing_operation_seq CHECK (operation_sequence > 0)
);

CREATE INDEX idx_routing_operation_tenant  ON mst.routing_operation (tenant_id);
CREATE INDEX idx_routing_operation_routing ON mst.routing_operation (routing_id);

CREATE TRIGGER trg_routing_operation_updated_at
    BEFORE UPDATE ON mst.routing_operation
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE mst.operation_resource_requirement (
    requirement_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    routing_operation_id UUID         NOT NULL REFERENCES mst.routing_operation (routing_operation_id) ON DELETE CASCADE,
    resource_id          UUID         NOT NULL REFERENCES mst.resource (resource_id),
    requirement_type     VARCHAR(32)  NOT NULL DEFAULT 'PRIMARY',
    quantity             NUMERIC(18,4) NOT NULL DEFAULT 1,
    uom                  VARCHAR(16)  NOT NULL DEFAULT 'EA',
    metadata             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_op_resource_req UNIQUE (tenant_id, routing_operation_id, resource_id, requirement_type),
    CONSTRAINT chk_requirement_type CHECK (
        requirement_type IN ('PRIMARY', 'SECONDARY', 'TOOL', 'LABOR', 'MATERIAL')
    )
);

CREATE INDEX idx_op_resource_req_tenant    ON mst.operation_resource_requirement (tenant_id);
CREATE INDEX idx_op_resource_req_operation ON mst.operation_resource_requirement (routing_operation_id);
CREATE INDEX idx_op_resource_req_resource  ON mst.operation_resource_requirement (resource_id);

CREATE TRIGGER trg_op_resource_req_updated_at
    BEFORE UPDATE ON mst.operation_resource_requirement
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

-- =============================================================================
-- TRANSACTIONAL (trn.*)
-- =============================================================================

CREATE TABLE trn.customer_order (
    customer_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID          NOT NULL REFERENCES core.tenant (tenant_id),
    order_code        VARCHAR(64)   NOT NULL,
    customer_id       UUID          NOT NULL REFERENCES mst.customer (customer_id),
    order_date        DATE          NOT NULL DEFAULT CURRENT_DATE,
    status            VARCHAR(32)   NOT NULL DEFAULT 'OPEN',
    metadata          JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_customer_order_code UNIQUE (tenant_id, order_code)
);

CREATE INDEX idx_customer_order_tenant   ON trn.customer_order (tenant_id);
CREATE INDEX idx_customer_order_customer ON trn.customer_order (tenant_id, customer_id);

CREATE TRIGGER trg_customer_order_updated_at
    BEFORE UPDATE ON trn.customer_order
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE trn.customer_order_line (
    order_line_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID          NOT NULL REFERENCES core.tenant (tenant_id),
    order_id      UUID          NOT NULL REFERENCES trn.customer_order (customer_order_id) ON DELETE CASCADE,
    line_code     VARCHAR(64)   NOT NULL,
    product_id    UUID          NOT NULL REFERENCES mst.product (product_id),
    quantity      NUMERIC(18,4) NOT NULL,
    uom           VARCHAR(16)   NOT NULL DEFAULT 'EA',
    status        VARCHAR(32)   NOT NULL DEFAULT 'OPEN',
    metadata      JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_order_line_code UNIQUE (tenant_id, line_code),
    CONSTRAINT chk_order_line_qty CHECK (quantity > 0)
);

CREATE INDEX idx_order_line_tenant ON trn.customer_order_line (tenant_id);
CREATE INDEX idx_order_line_order  ON trn.customer_order_line (order_id);

CREATE TRIGGER trg_customer_order_line_updated_at
    BEFORE UPDATE ON trn.customer_order_line
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE trn.production_order (
    production_order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID          NOT NULL REFERENCES core.tenant (tenant_id),
    production_order_code VARCHAR(64) NOT NULL,
    order_line_id       UUID          NOT NULL REFERENCES trn.customer_order_line (order_line_id),
    planned_quantity    NUMERIC(18,4) NOT NULL,
    status              VARCHAR(32)   NOT NULL DEFAULT 'PLANNED',
    metadata            JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_production_order_code UNIQUE (tenant_id, production_order_code),
    CONSTRAINT chk_production_order_qty CHECK (planned_quantity > 0)
);

CREATE INDEX idx_production_order_tenant     ON trn.production_order (tenant_id);
CREATE INDEX idx_production_order_order_line ON trn.production_order (order_line_id);

CREATE TRIGGER trg_production_order_updated_at
    BEFORE UPDATE ON trn.production_order
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE trn.production_lot (
    production_lot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         UUID          NOT NULL REFERENCES core.tenant (tenant_id),
    lot_code          VARCHAR(64)   NOT NULL,
    production_order_id UUID        NOT NULL REFERENCES trn.production_order (production_order_id) ON DELETE CASCADE,
    lot_quantity      NUMERIC(18,4) NOT NULL,
    status            VARCHAR(32)   NOT NULL DEFAULT 'CREATED',
    metadata          JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_production_lot_code UNIQUE (tenant_id, lot_code),
    CONSTRAINT chk_lot_qty CHECK (lot_quantity > 0)
);

CREATE INDEX idx_production_lot_tenant ON trn.production_lot (tenant_id);
CREATE INDEX idx_production_lot_po     ON trn.production_lot (production_order_id);

CREATE TRIGGER trg_production_lot_updated_at
    BEFORE UPDATE ON trn.production_lot
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE trn.feasibility_check (
    feasibility_check_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    check_code           VARCHAR(64)  NOT NULL,
    production_lot_id    UUID         NOT NULL REFERENCES trn.production_lot (production_lot_id),
    overall_status       VARCHAR(32)  NOT NULL DEFAULT 'PENDING',
    checked_at           TIMESTAMPTZ,
    metadata             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_feasibility_check_code UNIQUE (tenant_id, check_code),
    CONSTRAINT chk_feasibility_status CHECK (
        overall_status IN ('PENDING', 'OK', 'BLOCKED', 'WAIVED')
    )
);

CREATE INDEX idx_feasibility_check_tenant ON trn.feasibility_check (tenant_id);
CREATE INDEX idx_feasibility_check_lot    ON trn.feasibility_check (production_lot_id);

CREATE TRIGGER trg_feasibility_check_updated_at
    BEFORE UPDATE ON trn.feasibility_check
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE trn.feasibility_check_detail (
    feasibility_detail_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id              UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    feasibility_check_id   UUID         NOT NULL REFERENCES trn.feasibility_check (feasibility_check_id) ON DELETE CASCADE,
    check_key              VARCHAR(128) NOT NULL,
    check_label            VARCHAR(256),
    status                 VARCHAR(32)  NOT NULL DEFAULT 'PENDING',
    message                TEXT,
    metadata               JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_feasibility_detail_key UNIQUE (tenant_id, feasibility_check_id, check_key)
);

CREATE INDEX idx_feasibility_detail_tenant ON trn.feasibility_check_detail (tenant_id);
CREATE INDEX idx_feasibility_detail_check  ON trn.feasibility_check_detail (feasibility_check_id);

CREATE TRIGGER trg_feasibility_detail_updated_at
    BEFORE UPDATE ON trn.feasibility_check_detail
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

-- =============================================================================
-- EXECUTION (exec.*)
-- =============================================================================

CREATE TABLE exec.operation_execution (
    execution_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    execution_code       VARCHAR(64)  NOT NULL,
    production_lot_id    UUID         NOT NULL REFERENCES trn.production_lot (production_lot_id),
    routing_operation_id UUID         NOT NULL REFERENCES mst.routing_operation (routing_operation_id),
    equipment_id         UUID         REFERENCES mst.equipment (equipment_id),
    status               VARCHAR(32)  NOT NULL DEFAULT 'NOT_STARTED',
    started_at           TIMESTAMPTZ,
    completed_at         TIMESTAMPTZ,
    metadata             JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_execution_code UNIQUE (tenant_id, execution_code),
    CONSTRAINT chk_execution_status CHECK (
        status IN ('NOT_STARTED', 'IN_PROGRESS', 'COMPLETED', 'HOLD', 'SCRAPPED')
    )
);

CREATE INDEX idx_operation_execution_tenant    ON exec.operation_execution (tenant_id);
CREATE INDEX idx_operation_execution_lot       ON exec.operation_execution (production_lot_id);
CREATE INDEX idx_operation_execution_operation ON exec.operation_execution (routing_operation_id);

CREATE TRIGGER trg_operation_execution_updated_at
    BEFORE UPDATE ON exec.operation_execution
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE exec.parameter_reading (
    parameter_reading_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID          NOT NULL REFERENCES core.tenant (tenant_id),
    execution_id         UUID          NOT NULL REFERENCES exec.operation_execution (execution_id) ON DELETE CASCADE,
    parameter_code       VARCHAR(128)  NOT NULL,
    parameter_name       VARCHAR(256),
    reading_value        NUMERIC(18,6),
    reading_text         TEXT,
    uom                  VARCHAR(16),
    recorded_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    metadata             JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_parameter_reading UNIQUE (tenant_id, execution_id, parameter_code, recorded_at)
);

CREATE INDEX idx_parameter_reading_tenant     ON exec.parameter_reading (tenant_id);
CREATE INDEX idx_parameter_reading_execution  ON exec.parameter_reading (execution_id);

CREATE TRIGGER trg_parameter_reading_updated_at
    BEFORE UPDATE ON exec.parameter_reading
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

-- =============================================================================
-- QUALITY (qms.*)
-- =============================================================================

CREATE TABLE qms.quality_check (
    quality_check_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    check_code       VARCHAR(64)  NOT NULL,
    production_lot_id UUID        NOT NULL REFERENCES trn.production_lot (production_lot_id),
    check_type       VARCHAR(64)  NOT NULL DEFAULT 'IN_PROCESS',
    status           VARCHAR(32)  NOT NULL DEFAULT 'OPEN',
    metadata         JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_quality_check_code UNIQUE (tenant_id, check_code)
);

CREATE INDEX idx_quality_check_tenant ON qms.quality_check (tenant_id);
CREATE INDEX idx_quality_check_lot    ON qms.quality_check (production_lot_id);

CREATE TRIGGER trg_quality_check_updated_at
    BEFORE UPDATE ON qms.quality_check
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

CREATE TABLE qms.quality_result (
    quality_result_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id          UUID          NOT NULL REFERENCES core.tenant (tenant_id),
    quality_check_id   UUID          NOT NULL REFERENCES qms.quality_check (quality_check_id) ON DELETE CASCADE,
    characteristic_code VARCHAR(128) NOT NULL,
    characteristic_name VARCHAR(256),
    measured_value     NUMERIC(18,6),
    measured_text      TEXT,
    uom                VARCHAR(16),
    result_status      VARCHAR(32)   NOT NULL DEFAULT 'PASS',
    recorded_at        TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    metadata           JSONB         NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_quality_result_char UNIQUE (tenant_id, quality_check_id, characteristic_code)
);

CREATE INDEX idx_quality_result_tenant ON qms.quality_result (tenant_id);
CREATE INDEX idx_quality_result_check  ON qms.quality_result (quality_check_id);

CREATE TRIGGER trg_quality_result_updated_at
    BEFORE UPDATE ON qms.quality_result
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

-- =============================================================================
-- KNOWLEDGE GRAPH STAGING (kg.*)
-- =============================================================================

CREATE TABLE kg.triple_store_staging (
    triple_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    subject_uri  TEXT         NOT NULL,
    predicate_uri TEXT        NOT NULL,
    object_uri   TEXT,
    object_literal TEXT,
    object_datatype VARCHAR(128),
    source_table VARCHAR(128),
    source_id    UUID,
    export_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_triple_object CHECK (object_uri IS NOT NULL OR object_literal IS NOT NULL),
    CONSTRAINT chk_triple_export_status CHECK (
        export_status IN ('PENDING', 'EXPORTED', 'FAILED', 'SKIPPED')
    )
);

CREATE INDEX idx_triple_staging_tenant  ON kg.triple_store_staging (tenant_id);
CREATE INDEX idx_triple_staging_status  ON kg.triple_store_staging (tenant_id, export_status);
CREATE INDEX idx_triple_staging_subject ON kg.triple_store_staging (tenant_id, subject_uri);

CREATE TRIGGER trg_triple_staging_updated_at
    BEFORE UPDATE ON kg.triple_store_staging
    FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();

-- =============================================================================
-- SEED: Industry template, tenant, Automobile OEM master data
-- =============================================================================

-- Fixed UUIDs for reproducible seeds and cross-references
-- Template
INSERT INTO template.industry_template (
    industry_template_id, template_code, template_name, description, template_version, metadata
) VALUES (
    'a1000000-0000-4000-8000-000000000001',
    'AUTOMOBILE_OEM',
    'Automobile OEM Supplier',
    'Casting, machining, and assembly workflows for automotive Tier-1/Tier-2 suppliers.',
    '1.0.0',
    '{"process_families": ["Casting", "Machining", "Assembly"], "default_uom": "EA"}'::jsonb
);

-- Tenant
INSERT INTO core.tenant (
    tenant_id, tenant_code, tenant_name, industry_template_id, timezone, metadata
) VALUES (
    'b2000000-0000-4000-8000-000000000001',
    'AUTO_OEM_DEMO',
    'Automobile OEM Demo Tenant',
    'a1000000-0000-4000-8000-000000000001',
    'Asia/Kolkata',
    '{"demo": true, "industry": "AUTOMOBILE_OEM"}'::jsonb
);

-- Demo admin user (map cognito_sub after Cognito provisioning)
INSERT INTO core.app_user (
    user_id, email, display_name, metadata
) VALUES (
    'c3000000-0000-4000-8000-000000000001',
    'admin@auto-oem-demo.nyra.local',
    'Auto OEM Demo Admin',
    '{"note": "Assign cognito_sub when user is created in Cognito"}'::jsonb
);

INSERT INTO core.user_tenant_access (
    access_id, user_id, tenant_id, role_code, is_default
) VALUES (
    'd4000000-0000-4000-8000-000000000001',
    'c3000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000001',
    'MES_Admin',
    TRUE
);

-- Customer
INSERT INTO mst.customer (
    customer_id, tenant_id, customer_code, customer_name, metadata
) VALUES (
    'e5000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000001',
    'CUST-OEM-001',
    'Global Auto OEM Ltd.',
    '{"segment": "OEM"}'::jsonb
);

-- Product — cast iron brake disc (typical auto OEM casting part)
INSERT INTO mst.product (
    product_id, tenant_id, product_code, product_name, product_type, uom, metadata
) VALUES (
    'f6000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000001',
    'PART-BRK-DISC-001',
    'Cast Iron Brake Disc 280mm',
    'CASTING',
    'EA',
    '{"material": "GG25", "weight_kg": 12.4}'::jsonb
);

-- Resources
INSERT INTO mst.resource (
    resource_id, tenant_id, resource_code, resource_name, resource_type, metadata
) VALUES
(
    '10000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000001',
    'RES-MOULD-L01',
    'Moulding Line 1',
    'MACHINE',
    '{"line": "Moulding"}'::jsonb
),
(
    '10000000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000001',
    'RES-POUR-L01',
    'Pouring Line 1',
    'MACHINE',
    '{"line": "Pouring"}'::jsonb
),
(
    '10000000-0000-4000-8000-000000000003',
    'b2000000-0000-4000-8000-000000000001',
    'RES-FETT-ST01',
    'Fettling Station 1',
    'WORKCELL',
    '{"line": "Fettling"}'::jsonb
),
(
    '10000000-0000-4000-8000-000000000004',
    'b2000000-0000-4000-8000-000000000001',
    'RES-OP-CAST-01',
    'Casting Operator Pool',
    'LABOR',
    '{"shift": "A"}'::jsonb
);

-- Equipment linked to machine resources
INSERT INTO mst.equipment (
    equipment_id, tenant_id, equipment_code, equipment_name, resource_id, equipment_type, metadata
) VALUES
(
    '11000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000001',
    'EQ-MOULD-L01',
    'DISA Moulding Machine L1',
    '10000000-0000-4000-8000-000000000001',
    'MOULDING_MACHINE',
    '{"manufacturer": "DISA"}'::jsonb
),
(
    '11000000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000001',
    'EQ-POUR-L01',
    'Induction Furnace Pour L1',
    '10000000-0000-4000-8000-000000000002',
    'FURNACE',
    '{"capacity_kg": 500}'::jsonb
);

-- Routing for brake disc
INSERT INTO mst.routing (
    routing_id, tenant_id, routing_code, product_id, routing_version, process_family, metadata
) VALUES (
    '12000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000001',
    'ROUTE-BRK-DISC-V1',
    'f6000000-0000-4000-8000-000000000001',
    '1',
    'Casting',
    '{"template": "AUTOMOBILE_OEM"}'::jsonb
);

-- Routing operations: Moulding → Pouring → Fettling
INSERT INTO mst.routing_operation (
    routing_operation_id, tenant_id, routing_id, operation_code,
    operation_sequence, operation_name, standard_cycle_min, metadata
) VALUES
(
    '13000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000001',
    '12000000-0000-4000-8000-000000000001',
    'OP-MOULD-001',
    10,
    'Moulding',
    30.0000,
    '{"process_type": "Casting"}'::jsonb
),
(
    '13000000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000001',
    '12000000-0000-4000-8000-000000000001',
    'OP-POUR-001',
    20,
    'Pouring',
    25.0000,
    '{"process_type": "Casting"}'::jsonb
),
(
    '13000000-0000-4000-8000-000000000003',
    'b2000000-0000-4000-8000-000000000001',
    '12000000-0000-4000-8000-000000000001',
    'OP-FETT-001',
    30,
    'Fettling',
    15.0000,
    '{"process_type": "Finishing"}'::jsonb
);

-- Operation resource requirements
INSERT INTO mst.operation_resource_requirement (
    requirement_id, tenant_id, routing_operation_id, resource_id,
    requirement_type, quantity, uom, metadata
) VALUES
(
    '14000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000001',
    '13000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000001',
    'PRIMARY',
    1,
    'EA',
    '{}'::jsonb
),
(
    '14000000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000001',
    '13000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000004',
    'LABOR',
    2,
    'EA',
    '{"operators": 2}'::jsonb
),
(
    '14000000-0000-4000-8000-000000000003',
    'b2000000-0000-4000-8000-000000000001',
    '13000000-0000-4000-8000-000000000002',
    '10000000-0000-4000-8000-000000000002',
    'PRIMARY',
    1,
    'EA',
    '{}'::jsonb
),
(
    '14000000-0000-4000-8000-000000000004',
    'b2000000-0000-4000-8000-000000000001',
    '13000000-0000-4000-8000-000000000003',
    '10000000-0000-4000-8000-000000000003',
    'PRIMARY',
    1,
    'EA',
    '{}'::jsonb
);

-- Sample ontology triples staged for the demo tenant (brake disc routing chain)
INSERT INTO kg.triple_store_staging (
    triple_id, tenant_id, subject_uri, predicate_uri, object_uri, source_table, source_id
) VALUES
(
    '15000000-0000-4000-8000-000000000001',
    'b2000000-0000-4000-8000-000000000001',
    'mes:Product/PART-BRK-DISC-001',
    'mes:hasRouting',
    'mes:Routing/ROUTE-BRK-DISC-V1',
    'mst.routing',
    '12000000-0000-4000-8000-000000000001'
),
(
    '15000000-0000-4000-8000-000000000002',
    'b2000000-0000-4000-8000-000000000001',
    'mes:Routing/ROUTE-BRK-DISC-V1',
    'mes:hasOperation',
    'mes:Operation/OP-MOULD-001',
    'mst.routing_operation',
    '13000000-0000-4000-8000-000000000001'
);

COMMIT;

-- =============================================================================
-- Post-run verification (optional — run separately in DBeaver)
-- =============================================================================
-- SELECT template_code FROM template.industry_template;
-- SELECT tenant_code, tenant_name FROM core.tenant;
-- SELECT product_code, product_name FROM mst.product WHERE tenant_id = 'b2000000-0000-4000-8000-000000000001';
-- SELECT operation_code, operation_name, operation_sequence
--   FROM mst.routing_operation
--  WHERE tenant_id = 'b2000000-0000-4000-8000-000000000001'
--  ORDER BY operation_sequence;
-- SELECT COUNT(*) AS table_count
--   FROM information_schema.tables
--  WHERE table_schema IN ('core','template','ont','mst','trn','exec','qms','kg')
--    AND table_type = 'BASE TABLE';
