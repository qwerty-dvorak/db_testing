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

## Optimisation Benchmark

Use this command for focused threshold-count experiments:

```bash
uv run python main.py benchmark-optimisations --iterations 3 --warmup 1 --channel 512 --threshold 50
```

The optimisation suite starts by dropping benchmark-created optimisation
artifacts for the selected channel. It then runs the no-optimisation threshold
baselines before building any expression indexes or derived tables.

It currently measures:

| Family | Variants |
|--------|----------|
| JSONB array channel threshold | Sequential scan, expression index |
| JSONB object channel threshold | Sequential scan, expression index |
| `real[]` channel threshold | Sequential scan, expression index, hot-channel derived table, all-channel normalized derived table |
| wide channel threshold | Sequential scan, direct column index |
| JSONB array all-channel threshold | `jsonb_array_elements_text` vs `jsonb_array_elements` |

For derived tables and indexes, build work is part of the reported benchmark.
The summary includes:

- count of rows where the selected channel is greater than the threshold
- total build time
- table-build time
- index-build time
- average timed query time
- total time including build, warmup, and timed query runs
- query speedup against the first baseline in the same family

Container run:

```bash
docker compose run --rm app uv run python main.py benchmark-optimisations --iterations 3 --warmup 1 --channel 512 --threshold 50
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
