-- =============================================================================
-- OPTIONAL: Drop legacy oemauto data-capture tables (NOT nyra_mes_core).
-- =============================================================================
--
-- Run ONLY against the legacy oemauto database when:
--   * Activated Carbon uses exec.parameter_reading on nyra_mes_core (done), AND
--   * You no longer need Automotive OEM WorkOrderCaptureForm /data-capture/* routes.
--
-- DO NOT run this if LEGACY_DB_ENABLED=true and Automotive OEM execution still
-- uses WorkOrderCaptureForm (src/components/WorkOrderCaptureForm.jsx).
--
-- Default production (LEGACY_DB_ENABLED=false) does not use these tables.
-- Automotive OEM /workflow/* pages use nyra_mes_core /api/* and are unaffected.
-- =============================================================================

BEGIN;

DROP TABLE IF EXISTS trn.operation_data_capture_value CASCADE;
DROP TABLE IF EXISTS trn.operation_data_capture CASCADE;
DROP TABLE IF EXISTS mst.data_capture_field CASCADE;
DROP TABLE IF EXISTS mst.data_capture_template CASCADE;

COMMIT;
