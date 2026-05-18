-- ============================================================================
-- 04_benchmark_queries_pg16.sql
-- PostgreSQL 16-compatible benchmark queries
--
-- All features are available on PG 16 (EXPLAIN ANALYZE BUFFERS, LATERAL,
-- parallel query, etc.).
-- ============================================================================

-- B1: Row count
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT count(*) FROM sensor_payloads;

-- B2: Full unnest (all channels)
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT id, value
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS value;

-- B3: Global min / max across all 1.028 billion values
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT array_global_min(v), array_global_max(v)
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS v;

-- B4: Single-channel extraction (channel 512)
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT avg(extract_channel(payload, 511)) FROM sensor_payloads;

-- B5: Per-row min/max (correlated subquery pattern)
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT
    id,
    (SELECT min(v) FROM jsonb_array_to_float8(payload) AS v) AS row_min,
    (SELECT max(v) FROM jsonb_array_to_float8(payload) AS v) AS row_max
FROM sensor_payloads
LIMIT 100;
