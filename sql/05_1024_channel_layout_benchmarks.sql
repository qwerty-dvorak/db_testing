-- ============================================================================
-- 05_1024_channel_layout_benchmarks.sql
-- PostgreSQL-only layout comparisons for 1M readings x 1024 channels.
--
-- This file intentionally uses only core PostgreSQL features. It does not
-- require TimescaleDB, Citus, columnar extensions, or custom data types.
-- ============================================================================

SET jit = off;
SET work_mem = '256MB';
SET max_parallel_workers_per_gather = 4;

-- ---------------------------------------------------------------------------
-- A. Existing JSONB array layout: one row per reading.
-- Table: sensor_payloads(id uuid, payload jsonb, created_at timestamptz)
-- Payload shape: [12.3, 45.6, ...] with 1024 elements.
-- ---------------------------------------------------------------------------

-- A1. Min/max for one channel across 1M rows.
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    min((payload->>511)::float8) AS min_channel_512,
    max((payload->>511)::float8) AS max_channel_512
FROM sensor_payloads;

-- A2. Min/max for every channel across 1M rows.
-- Expected work: 1M x 1024 JSONB text extractions and casts.
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    channel_idx,
    min(value) AS min_value,
    max(value) AS max_value
FROM sensor_payloads
CROSS JOIN LATERAL (
    SELECT ord::int - 1 AS channel_idx, value::float8 AS value
    FROM jsonb_array_elements_text(payload) WITH ORDINALITY AS e(value, ord)
    WHERE ord <= 1024
) AS channels
GROUP BY channel_idx
ORDER BY channel_idx;

-- ---------------------------------------------------------------------------
-- B. JSONB object layout: one row per reading, named channels.
-- Use when channel names matter more than positional array compactness.
-- Payload shape: {"ch0001": 12.3, "ch0002": 45.6, ...}
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS sensor_payloads_json_object;
CREATE TABLE sensor_payloads_json_object (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO sensor_payloads_json_object (id, payload, created_at)
SELECT
    id,
    jsonb_object_agg('ch' || lpad(ord::text, 4, '0'), value ORDER BY ord),
    created_at
FROM sensor_payloads
CROSS JOIN LATERAL jsonb_array_elements(payload) WITH ORDINALITY AS e(value, ord)
WHERE ord <= 1024
GROUP BY id, created_at;

ANALYZE sensor_payloads_json_object;

-- B1. Min/max for one channel.
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    min((payload->>'ch0512')::float8) AS min_channel_512,
    max((payload->>'ch0512')::float8) AS max_channel_512
FROM sensor_payloads_json_object;

-- B2. Min/max for every channel.
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    key AS channel_name,
    min(value::float8) AS min_value,
    max(value::float8) AS max_value
FROM sensor_payloads_json_object
CROSS JOIN LATERAL jsonb_each_text(payload) AS e(key, value)
GROUP BY key
ORDER BY key;

-- ---------------------------------------------------------------------------
-- C. Native float8[] layout: one row per reading, typed array payload.
-- Usually the best drop-in replacement for JSONB when channels are numeric
-- and positional. Still TOASTed, but avoids JSONB scalar text conversion.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS sensor_payloads_array;
CREATE TABLE sensor_payloads_array (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    float8[] NOT NULL CHECK (array_length(payload, 1) = 1024),
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO sensor_payloads_array (id, payload, created_at)
SELECT
    id,
    array_agg(value::float8 ORDER BY ord),
    created_at
FROM sensor_payloads
CROSS JOIN LATERAL jsonb_array_elements_text(payload) WITH ORDINALITY AS e(value, ord)
WHERE ord <= 1024
GROUP BY id, created_at;

ANALYZE sensor_payloads_array;

-- C1. Min/max for one channel.
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    min(payload[512]) AS min_channel_512,
    max(payload[512]) AS max_channel_512
FROM sensor_payloads_array;

-- C2. Min/max for every channel.
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    ord::int - 1 AS channel_idx,
    min(value) AS min_value,
    max(value) AS max_value
FROM sensor_payloads_array
CROSS JOIN LATERAL unnest(payload) WITH ORDINALITY AS u(value, ord)
GROUP BY ord
ORDER BY ord;

-- ---------------------------------------------------------------------------
-- D. Normalized row layout: one row per reading-channel value.
-- 1M readings x 1024 channels = 1.024B rows. It is simple SQL and indexable
-- per channel, but storage and insert volume are much larger.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS sensor_channel_values;
CREATE TABLE sensor_channel_values (
    reading_id  uuid NOT NULL,
    channel_idx int2 NOT NULL CHECK (channel_idx BETWEEN 0 AND 1023),
    value       float8 NOT NULL,
    created_at  timestamptz NOT NULL,
    PRIMARY KEY (reading_id, channel_idx)
);

INSERT INTO sensor_channel_values (reading_id, channel_idx, value, created_at)
SELECT
    id,
    ord::int - 1,
    value::float8,
    created_at
FROM sensor_payloads
CROSS JOIN LATERAL jsonb_array_elements_text(payload) WITH ORDINALITY AS e(value, ord)
WHERE ord <= 1024;

CREATE INDEX idx_sensor_channel_values_channel
    ON sensor_channel_values (channel_idx, value);
CREATE INDEX idx_sensor_channel_values_created_at
    ON sensor_channel_values (created_at);
ANALYZE sensor_channel_values;

-- D1. Min/max for one channel. This should use idx_sensor_channel_values_channel.
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    min(value) AS min_channel_512,
    max(value) AS max_channel_512
FROM sensor_channel_values
WHERE channel_idx = 511;

-- D2. Min/max for every channel.
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    channel_idx,
    min(value) AS min_value,
    max(value) AS max_value
FROM sensor_channel_values
GROUP BY channel_idx
ORDER BY channel_idx;

-- ---------------------------------------------------------------------------
-- E. Wide table layout: one physical column per channel.
-- This is fastest for "all channels in one scan" in plain row-store Postgres,
-- but rigid. DDL and load SQL are generated because writing 1024 columns by
-- hand is not maintainable.
-- ---------------------------------------------------------------------------

-- E1. Create and load sensor_payloads_wide (... ch0001 float8, ...).
DO $$
DECLARE
    channel_defs text;
    channel_names text;
    channel_values text;
BEGIN
    SELECT
        string_agg('ch' || lpad(i::text, 4, '0') || ' float8 NOT NULL', ', ' ORDER BY i),
        string_agg('ch' || lpad(i::text, 4, '0'), ', ' ORDER BY i),
        string_agg(format('(payload->>%s)::float8', i - 1), ', ' ORDER BY i)
    INTO channel_defs, channel_names, channel_values
    FROM generate_series(1, 1024) AS g(i);

    EXECUTE 'DROP TABLE IF EXISTS sensor_payloads_wide';
    EXECUTE format(
        'CREATE TABLE sensor_payloads_wide (
             id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
             created_at timestamptz NOT NULL DEFAULT now(),
             %s
         )',
        channel_defs
    );
    EXECUTE format(
        'INSERT INTO sensor_payloads_wide (id, created_at, %s)
         SELECT id, created_at, %s
         FROM sensor_payloads',
        channel_names,
        channel_values
    );
END $$;

ANALYZE sensor_payloads_wide;

-- E2. Generate one-scan min/max SQL for every wide-table channel.
-- Run the generated statement to return one row with 2048 extrema columns.
SELECT format(
    'EXPLAIN (ANALYZE, BUFFERS, TIMING) SELECT %s FROM sensor_payloads_wide;',
    string_agg(
        format(
            'min(%1$s) AS min_%1$s, max(%1$s) AS max_%1$s',
            'ch' || lpad(i::text, 4, '0')
        ),
        ', ' ORDER BY i
    )
)
FROM generate_series(1, 1024) AS g(i);

-- E3. One-channel min/max example.
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT min(ch0512), max(ch0512)
FROM sensor_payloads_wide;
