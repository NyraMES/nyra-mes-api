-- =============================================================================
-- nyra_mes_core — business code sequences (run on existing DB if missing)
-- =============================================================================
-- Auto-generates codes via PostgreSQL nextval only (no MAX/code fallback in the API).
-- Safe to re-run (IF NOT EXISTS).
-- =============================================================================

CREATE SEQUENCE IF NOT EXISTS core.supplier_code_seq START 1;
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

COMMENT ON SEQUENCE core.customer_code_seq IS 'Next customer_code suffix (CUST00001) — tenant-scoped uniqueness on mst.customer';
COMMENT ON SEQUENCE core.product_code_seq IS 'Next product_code suffix (PART00001)';
