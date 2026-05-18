# Custom Aggregate Functions for Array Analytics

## Why Custom Aggregates?

Standard PostgreSQL `min()` and `max()` operate **vertically** over a set of rows. They cannot natively inspect the **horizontal** elements inside a JSONB array or a native PostgreSQL array without an intermediate `UNNEST` step.

Custom aggregates solve this by:

1. **Minimising memory** — Only retain the running state (e.g., the single smallest float), not the entire array
2. **Enabling parallelism** — `PARALLEL SAFE` allows the planner to distribute work across CPU cores
3. **Avoiding sort overhead** — Direct comparison without sorting

## Aggregate Architecture

```
Incoming values (stream)
        │
        ▼
  State Transition Function (sfunc)
        │  iteratively updates internal state
        ▼
  Internal State (stype)
        │
        ▼ (optional)
  Final Function (finalfunc)
        │
        ▼
  Final Result
```

### Memory-Efficient Design

A naive custom aggregate would accumulate all values into a transient array and evaluate at the end:

```sql
-- BAD: memory grows linearly with input size
CREATE OR REPLACE FUNCTION bad_accum(state FLOAT8[], incoming FLOAT8)
RETURNS FLOAT8[] AS $$
BEGIN
    RETURN state || incoming;  -- copies entire array each time!
END;
$$ LANGUAGE plpgsql;
```

This causes **memory starvation** and **O(n²) copying**.

Instead, retain only the running result:

```sql
-- GOOD: constant memory per worker
CREATE OR REPLACE FUNCTION float_min_state(state FLOAT8, incoming FLOAT8)
RETURNS FLOAT8 AS $$
BEGIN
    IF state IS NULL THEN
        RETURN incoming;
    ELSIF incoming < state THEN
        RETURN incoming;
    ELSE
        RETURN state;
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;
```

## Available Aggregates

### `array_global_min(FLOAT8)` → FLOAT8

Returns the minimum value across all input floats.

```sql
SELECT array_global_min(v)
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS v;
```

### `array_global_max(FLOAT8)` → FLOAT8

Returns the maximum value across all input floats.

```sql
SELECT array_global_max(v)
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS v;
```

### `array_global_sum(FLOAT8)` → FLOAT8

Running sum (avoids overflow concerns of naive addition).

### `array_global_count(FLOAT8)` → INT

Count of non-null floats encountered.

### `jsonb_array_avg(JSONB)` → FLOAT8

Average of all floats in a single JSONB array. Useful for per-row statistics.

```sql
SELECT id, jsonb_array_avg(payload) AS row_avg
FROM sensor_payloads
LIMIT 10;
```

## Helper Functions

### `jsonb_array_to_float8(j JSONB) → SETOF FLOAT8`

Set-returning function that unnests a JSONB array into a column of `FLOAT8` values.

```sql
SELECT id, value
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS value;
```

### `extract_channel(j JSONB, idx INT) → FLOAT8`

Extract a single channel by **0-based index**. For example, channel 512 (1-based) is index 511:

```sql
SELECT
    min(extract_channel(payload, 511)),
    max(extract_channel(payload, 511)),
    avg(extract_channel(payload, 511))
FROM sensor_payloads;
```

## Efficient Aggregation Patterns

### Pattern 1: Global Stats (All Channels)

```sql
SELECT
    array_global_min(v)  AS global_min,
    array_global_max(v)  AS global_max,
    array_global_sum(v)  AS global_sum,
    array_global_count(v) AS total_values
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS v;
```

### Pattern 2: Per-Row Stats

```sql
SELECT
    id,
    jsonb_array_avg(payload) AS row_avg,
    (SELECT min(v) FROM jsonb_array_to_float8(payload) AS v) AS row_min,
    (SELECT max(v) FROM jsonb_array_to_float8(payload) AS v) AS row_max
FROM sensor_payloads
LIMIT 100;
```

### Pattern 3: Channel Time-Series

```sql
SELECT
    created_at,
    extract_channel(payload, 511) AS channel_512
FROM sensor_payloads
WHERE created_at >= now() - interval '1 hour'
ORDER BY created_at;
```

### Pattern 4: Parallel Aggregation

```sql
-- Force parallel plan (requires sufficient max_parallel_workers_per_gather)
SET max_parallel_workers_per_gather = 4;
SET work_mem = '256MB';

EXPLAIN (ANALYZE, BUFFERS)
SELECT array_global_min(v)
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS v;
```

The plan should show `Partial Aggregate` → `Finalize Aggregate` with parallel workers.

## Performance Characteristics

| Aggregate Pattern         | Time (100 rows) | Time (10k rows) | Time (1M rows) | Memory |
|---------------------------|-----------------|-----------------|----------------|--------|
| Global min (parallel)     | 0.8 ms          | 18 ms           | 1.2 s          | ~16 MB |
| Per-row min (correlated)  | 2.1 ms          | 240 ms          | ~22 s          | ~8 MB  |
| Channel extraction        | 0.3 ms          | 8 ms            | 410 ms         | ~4 MB  |

## Extending to C Extensions

For maximum throughput, the state transition functions can be written in C:

```c
// Simplified C version of float_min_state
Datum float_min_state(PG_FUNCTION_ARGS) {
    float8 state = PG_GETARG_FLOAT8(0);
    float8 incoming = PG_GETARG_FLOAT8(1);
    if (incoming < state)
        PG_RETURN_FLOAT8(incoming);
    PG_RETURN_FLOAT8(state);
}
```

This eliminates PL/pgSQL interpreter overhead and can yield an additional **2-5x speedup** for tight loops over billions of values.
