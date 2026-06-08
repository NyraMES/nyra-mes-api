-- Allow the same operation_code (e.g. MOULDING) on different routings within a tenant.
-- Previously operation_code was unique per tenant, which blocked Routing Master saves
-- when demo/seed operations already existed.

ALTER TABLE mst.routing_operation
    DROP CONSTRAINT IF EXISTS uq_routing_operation_code;

ALTER TABLE mst.routing_operation
    ADD CONSTRAINT uq_routing_operation_code
    UNIQUE (tenant_id, routing_id, operation_code);
