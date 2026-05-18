-- ============================================================================
-- 04_benchmark_queries.sql
-- Benchmark queries for testing JSONB array extraction & aggregation performance
-- ============================================================================

-- ---------------------------------------------------------------------------
-- B1: Count total payloads
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT count(*) FROM sensor_payloads;

-- ---------------------------------------------------------------------------
-- B2: Extract all values from all payloads (unnest, no aggregation)
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT id, value
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS value;

-- ---------------------------------------------------------------------------
-- B3: Global min across all 1.028 billion float values
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT array_global_min(value), array_global_max(value)
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS value;

-- ---------------------------------------------------------------------------
-- B4: Average of a single channel across all rows (channel 512)
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    min(extract_channel(payload, 511)),
    max(extract_channel(payload, 511)),
    avg(extract_channel(payload, 511))
FROM sensor_payloads;

-- ---------------------------------------------------------------------------
-- B5: Per-row min/max using custom aggregate on JSONB
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    id,
    (SELECT min(v) FROM jsonb_array_to_float8(payload) AS v) AS row_min,
    (SELECT max(v) FROM jsonb_array_to_float8(payload) AS v) AS row_max
FROM sensor_payloads
LIMIT 100;

-- ---------------------------------------------------------------------------
-- B6: Extract a specific index path via jsonb_path_query
-- ---------------------------------------------------------------------------
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT id, jsonb_path_query(payload, '$[0]')::text::float8 AS first_channel
FROM sensor_payloads
LIMIT 1000;

-- ---------------------------------------------------------------------------
-- B7: Generate 1 000 000 rows (use with caution — takes minutes)
-- ---------------------------------------------------------------------------
/*
INSERT INTO sensor_payloads (payload)
SELECT
    jsonb_agg((random() * 100.0)::float8 ORDER BY i) AS payload
FROM generate_series(1, 1000) AS s(idx)
CROSS JOIN generate_series(1, 1028) AS i
GROUP BY s.idx;
*/
