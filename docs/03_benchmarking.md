# Benchmarking

The benchmark suite compares the four current layouts in real time. It does not
create summary tables and it does not hide build time outside the measured
queries.

```bash
uv run python main.py benchmark --iterations 5 --warmup 2 --channel 512 --threshold 50
```

## Query Groups

For each layout, the suite runs:

| Metric | Result shape |
|--------|--------------|
| Row count | One row |
| Single-channel min/max/avg | One row |
| All-channel min/max | 1024 rows |
| All-channel threshold count | 1024 rows |

The CLI logs:

- rows returned
- warmup timings
- every timed iteration
- average, min, median, max, standard deviation
- total measured query time
- benchmark suite wall time

## Layout Notes

JSONB array and JSONB object queries cast JSONB scalar text to numeric values at
query time. `real[]` queries unnest a typed array. Wide-table queries read
direct columns; the all-channel min/max query uses a generated lateral `VALUES`
list so PostgreSQL returns the same 1024-row shape as the other layouts without
exceeding the target-list limit.

## Recommended Runs

Small smoke test:

```bash
uv run python main.py benchmark --iterations 1 --warmup 0
```

More stable local comparison:

```bash
uv run python main.py benchmark --iterations 5 --warmup 2
```

Container comparison:

```bash
docker compose run --rm app uv run python main.py benchmark --iterations 5 --warmup 2
```

## Inspecting Plans

For deeper diagnosis, use `EXPLAIN (ANALYZE, BUFFERS)` manually through
`main.py query` or `psql`. Example:

```bash
uv run python main.py query "
EXPLAIN (ANALYZE, BUFFERS)
SELECT ord::int - 1 AS channel_idx, min(value), max(value)
FROM sensor_payloads_array
CROSS JOIN LATERAL unnest(payload) WITH ORDINALITY AS u(value, ord)
GROUP BY ord
ORDER BY ord
"
```

Useful PostgreSQL settings to vary during experiments:

```sql
SET jit = off;
SET work_mem = '256MB';
SET max_parallel_workers_per_gather = 4;
```
