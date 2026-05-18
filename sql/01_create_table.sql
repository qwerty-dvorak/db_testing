-- ============================================================================
-- 01_create_table.sql
-- Creates the core sensor telemetry table with JSONB storage
-- ============================================================================

-- Note: gen_random_uuid() is available natively since PostgreSQL 13.
-- No pgcrypto extension required.

DROP TABLE IF EXISTS sensor_payloads CASCADE;

CREATE TABLE sensor_payloads (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  sensor_payloads IS 'High-dimensional sensor telemetry -- 1028-channel floating-point payloads stored as JSONB';
COMMENT ON COLUMN sensor_payloads.id         IS 'Globally unique reading identifier (UUID v4, generated via gen_random_uuid)';
COMMENT ON COLUMN sensor_payloads.payload    IS 'JSONB array of 1028 double-precision floats, e.g. [0.123, 0.456, ...]';
COMMENT ON COLUMN sensor_payloads.created_at IS 'Ingestion timestamp with timezone, defaults to current UTC';

CREATE INDEX idx_sensor_payloads_created_at ON sensor_payloads (created_at DESC);
CREATE INDEX idx_sensor_payloads_gin ON sensor_payloads USING GIN (payload jsonb_path_ops);
