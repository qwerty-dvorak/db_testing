# 1024-Channel Performance Plan

This project should benchmark the real target query directly:

```sql
-- For 1,000,000 readings, return 1024 rows:
-- channel_idx, min_value, max_value.
SELECT channel_idx, min(value), max(value)
FROM ...
GROUP BY channel_idx
ORDER BY channel_idx;
```

The benchmark must stay PostgreSQL-only. Do not use TimescaleDB or other storage extensions when comparing layouts.

## Baseline Scale

| Metric | Value |
|--------|-------|
| Readings | 1,000,000 rows |
| Channels per reading | 1024 |
| Values scanned for all-channel extrema | 1.024 billion |
| Value type | `float8` |

Run each query with:

```sql
SET jit = off;
SET work_mem = '256MB';
SET max_parallel_workers_per_gather = 4;
EXPLAIN (ANALYZE, BUFFERS, TIMING) ...
```

Always record elapsed time, shared hits/reads, temp reads/writes, row estimates, and whether the plan parallelized.

## Layout Options

### 1. JSONB Array

Current baseline:

```sql
CREATE TABLE sensor_payloads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

All-channel extrema:

```sql
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
```

Use this when payload schema changes often. Expect it to be slower than native arrays because every value is extracted from JSONB and cast.

### 2. JSONB Object

Shape:

```json
{"ch0001": 12.3, "ch0002": 45.6}
```

All-channel extrema:

```sql
SELECT
    key AS channel_name,
    min(value::float8) AS min_value,
    max(value::float8) AS max_value
FROM sensor_payloads_json_object
CROSS JOIN LATERAL jsonb_each_text(payload) AS e(key, value)
GROUP BY key
ORDER BY key;
```

Use this only if channel names must be self-describing inside each row. It stores repeated key names and is usually worse than JSONB arrays for fixed 1024-channel telemetry.

### 3. Native `real[]`

Schema:

```sql
CREATE TABLE sensor_payloads_array (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload real[] NOT NULL CHECK (array_length(payload, 1) = 1024),
    created_at timestamptz NOT NULL DEFAULT now()
);
```

All-channel extrema:

```sql
SELECT
    ord::int - 1 AS channel_idx,
    min(value) AS min_value,
    max(value) AS max_value
FROM sensor_payloads_array
CROSS JOIN LATERAL unnest(payload) WITH ORDINALITY AS u(value, ord)
GROUP BY ord
ORDER BY ord;
```

This is the best drop-in alternative to JSONB for fixed numeric channels. It keeps one row per reading, preserves channel position, and avoids JSONB text extraction.

### 4. Wide 1024-Column Table

Shape:

```sql
CREATE TABLE sensor_payloads_wide (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    ch0001 real NOT NULL,
    ch0002 real NOT NULL
    -- through ch1024
);
```

All-channel extrema:

```sql
SELECT
    min(ch0001), max(ch0001),
    min(ch0002), max(ch0002)
    -- through ch1024
FROM sensor_payloads_wide;
```

This is likely the fastest plain-Postgres row-store option for all-channel min/max because it scans typed columns without unnesting. The cost is rigid DDL and generated SQL. PostgreSQL’s 1600-column table limit allows 1024 channels, but there is little headroom for schema growth.

## Recommendation

The benchmark suite compares four layouts:

1. JSONB array, because it is the current implementation and most flexible.
2. JSONB object, because it measures the cost of named key-value payloads.
3. Native `real[]`, because it is the cleanest fixed-channel replacement.
4. Wide table, because it establishes the fastest realistic plain-Postgres baseline for min/max across every channel.

All comparison queries are real time. The CLI does not build derived summary
tables before benchmarking, so extraction, casts, unnesting, aggregation, and
threshold counting are included in the measured query time.

The runnable SQL for these layouts is in `sql/05_1024_channel_layout_benchmarks.sql`.
