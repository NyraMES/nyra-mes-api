-- =============================================================================
-- nyra_mes_core — supplier master + inward receipt linkage (safe to re-run)
-- =============================================================================

CREATE SEQUENCE IF NOT EXISTS core.supplier_code_seq START 1;

CREATE TABLE IF NOT EXISTS mst.supplier (
    supplier_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     UUID         NOT NULL REFERENCES core.tenant (tenant_id),
    workspace_id  UUID         REFERENCES core.project_workspace (workspace_id),
    supplier_code VARCHAR(64)  NOT NULL,
    supplier_name VARCHAR(256) NOT NULL,
    status        VARCHAR(32)  NOT NULL DEFAULT 'ACTIVE',
    metadata      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_supplier_code UNIQUE (tenant_id, supplier_code)
);

CREATE INDEX IF NOT EXISTS idx_supplier_tenant ON mst.supplier (tenant_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_supplier_updated_at'
    ) THEN
        CREATE TRIGGER trg_supplier_updated_at
            BEFORE UPDATE ON mst.supplier
            FOR EACH ROW EXECUTE PROCEDURE core.set_updated_at();
    END IF;
END $$;

ALTER TABLE trn.customer_order
    ADD COLUMN IF NOT EXISTS supplier_id UUID REFERENCES mst.supplier (supplier_id);

CREATE INDEX IF NOT EXISTS idx_customer_order_supplier
    ON trn.customer_order (tenant_id, supplier_id);

ALTER TABLE trn.customer_order
    ALTER COLUMN customer_id DROP NOT NULL;

COMMENT ON TABLE mst.supplier IS 'Raw material vendors — separate from end customers (mst.customer)';
