-- ============================================================================
-- 01_create_table_pg16.sql
-- PostgreSQL 16-compatible schema for sensor_payloads
--
-- Differences from PG 18 version: none — gen_random_uuid() is available
-- natively since PG 13. This file is identical but explicitly tested on PG 16.
-- ============================================================================

DROP TABLE IF EXISTS sensor_payloads CASCADE;

CREATE TABLE sensor_payloads (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE  sensor_payloads
    IS 'High-dimensional sensor telemetry -- 1028-channel JSONB payloads';
COMMENT ON COLUMN sensor_payloads.id
    IS 'UUID v4, generated via gen_random_uuid() (PG 13+ built-in)';
COMMENT ON COLUMN sensor_payloads.payload
    IS 'JSONB array of 1028 float8 values: [0.123, 0.456, ...]';
COMMENT ON COLUMN sensor_payloads.created_at
    IS 'Ingestion timestamp with timezone, defaults to now()';

CREATE INDEX idx_sensor_payloads_created_at
    ON sensor_payloads (created_at DESC);

CREATE INDEX idx_sensor_payloads_gin
    ON sensor_payloads USING GIN (payload jsonb_path_ops);
