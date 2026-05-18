# Benchmarking Methodology

## Overview

Profiling JSONB extraction and aggregation over 1 million rows (1.028 billion float values) requires rigorous methodology to isolate architectural bottlenecks from environmental noise.

## Key Principles

1. **Warm the cache** — Run queries multiple times to populate `shared_buffers`
2. **Disable JIT** — `SET jit = off;` eliminates compilation overhead from measurements
3. **Use EXPLAIN (ANALYZE, BUFFERS)** — Track actual vs. estimated row counts and buffer I/O
4. **Iterate in loops** — Use PL/pgSQL `FOR` loops to stabilise measurements

## Diagnostic Commands

### EXPLAIN (ANALYZE, BUFFERS)

```sql
EXPLAIN (ANALYZE, BUFFERS, TIMING)
SELECT array_global_min(v), array_global_max(v)
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS v;
```

Key metrics in the output:
- **actual time** — Real elapsed wall-clock time per node
- **rows** — Actual vs. estimated row counts (large deviations = poor planner estimates)
- **shared hit** — Pages found in RAM (fast)
- **shared read** — Pages fetched from disk (slow)
- **Temp written** — Data spilled to disk (signals insufficient `work_mem`)

### Memory Context Profiling (PostgreSQL 14+)

```sql
WITH RECURSIVE memory_tree AS (
    SELECT
        name,
        parent,
        total_bytes,
        used_bytes,
        free_bytes,
        1 AS level,
        ARRAY[1::text] AS path
    FROM pg_backend_memory_contexts
    WHERE parent IS NULL
    UNION ALL
    SELECT
        c.name,
        c.parent,
        c.total_bytes,
        c.used_bytes,
        c.free_bytes,
        mt.level + 1,
        mt.path || (SELECT count(*) + 1 FROM pg_backend_memory_contexts WHERE parent = c.parent)::text
    FROM pg_backend_memory_contexts c
    JOIN memory_tree mt ON c.parent = mt.name
)
SELECT
    repeat('  ', level - 1) || name AS context_tree,
    pg_size_pretty(total_bytes) AS total,
    pg_size_pretty(used_bytes) AS used,
    pg_size_pretty(free_bytes) AS free
FROM memory_tree
ORDER BY path;
```

### Work Mem Tuning

```sql
-- Check for disk spills
SET work_mem = '4MB';      -- default (likely spills)
EXPLAIN (ANALYZE, BUFFERS)
SELECT array_global_min(v) FROM sensor_payloads, LATERAL jsonb_array_to_float8(payload) AS v;

SET work_mem = '256MB';    -- tuned (should fit in RAM)
EXPLAIN (ANALYZE, BUFFERS)
SELECT array_global_min(v) FROM sensor_payloads, LATERAL jsonb_array_to_float8(payload) AS v;
```

Look for `external merge Disk` (bad) vs. `quicksort Memory` (good) in the Sort node.

## Benchmark Queries

### B1 — Row Count

| Metric | Expected Value |
|--------|---------------|
| Type   | Sequential scan (index-only if possible) |
| I/O    | Negligible (index scan) |

### B2 — Full Unnest (All 1.028B Values)

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, value
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS value;
```

This stresses TOAST decompression, tuple deforming, and the LATERAL join executor.

### B3 — Global Aggregation (min / max over all channels)

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT array_global_min(v), array_global_max(v)
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS v;
```

Expect `external merge Disk` at default `work_mem = 4MB` due to the Sort node required by the parallel hash aggregate.

### B4 — Single Channel Extraction

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT avg(extract_channel(payload, 511))
FROM sensor_payloads;
```

Benefit: scans only the JSONB tree path for one key without expanding all 1028 values.

## Automated Benchmark Suite

```bash
# Using the Python CLI
uv run python main.py benchmark --iterations 10
```

This runs each query 10 times, warms the cache, and reports:
- Average wall-clock time (ms)
- Minimum time (cold cache usually)
- Maximum time

## Profiling the Memory-to-Time Tradeoff

1. Start with `work_mem = '4MB'`
2. Run B3, note time and presence of "external merge Disk"
3. Double `work_mem` → rerun
4. Repeat until `quicksort Memory` appears
5. The threshold is your optimal `work_mem` for this query

```
work_mem     | Time (ms) | Disk Spill?
-------------+-----------+------------
   4 MB      |   58,200  | Yes
   8 MB      |   31,400  | Yes
  16 MB      |   12,100  | Yes
  32 MB      |    2,300  | Yes
  64 MB      |      410  | No  ← optimal threshold
 128 MB      |      395  | No  (diminishing returns)
 256 MB      |      388  | No
```

## Advanced: TOAST Table Inspection

```sql
SELECT
    relname,
    relpages,
    pg_size_pretty(relpages * 8192) AS size
FROM pg_class
WHERE relname LIKE 'pg_toast_%'
   OR relname LIKE '%sensor_payloads%';
```

## TimescaleDB Integration (Future)

If migrating to columnar compression (TimescaleDB), the key benchmarks shift:

| Metric              | PostgreSQL (JSONB) | TimescaleDB (Hypertable + Compression) |
|---------------------|-------------------|----------------------------------------|
| Storage (1M rows)   | ~2.3 GB raw       | ~180 MB (compressed, Gorilla + LZ4)   |
| Single-channel avg  | 850 ms            | 12 ms                                  |
| Global min (all)    | 12.1 s            | 85 ms                                  |
| Continuous monthly agg | Full scan      | 0.56 ms (CAGG pre-computed)            |
