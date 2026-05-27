-- Execution capture on work orders (operator, actual machine, downtime).
-- Run once against your Nyra MES PostgreSQL database before using
-- start/complete fields that persist beyond event remarks.

ALTER TABLE trn.work_order
  ADD COLUMN IF NOT EXISTS operator_name VARCHAR(255),
  ADD COLUMN IF NOT EXISTS actual_machine_id BIGINT REFERENCES mst.machine(id),
  ADD COLUMN IF NOT EXISTS downtime_minutes NUMERIC(18, 4);
