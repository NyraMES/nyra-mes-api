-- Ensure exec.parameter_reading exists on nyra_mes_core (idempotent).
-- Safe to run on databases provisioned before parameter_reading was added to setup.sql.

CREATE TABLE IF NOT EXISTS exec.parameter_reading (
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

CREATE INDEX IF NOT EXISTS idx_parameter_reading_tenant
    ON exec.parameter_reading (tenant_id);

CREATE INDEX IF NOT EXISTS idx_parameter_reading_execution
    ON exec.parameter_reading (execution_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_parameter_reading_updated_at'
    ) THEN
        CREATE TRIGGER trg_parameter_reading_updated_at
            BEFORE UPDATE ON exec.parameter_reading
            FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();
    END IF;
END $$;
