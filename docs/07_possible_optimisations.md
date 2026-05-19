# Possible Optimisations

This document lists practical improvements to test after the current four-layout
baseline is stable. Each item should be measured with the benchmark suite before
and after the change.

## Measurement First

Before changing implementation details, capture:

```bash
docker compose run --rm app uv run python main.py verify
docker compose run --rm app uv run python main.py benchmark --iterations 5 --warmup 2
docker compose run --rm app uv run python main.py benchmark-optimisations --iterations 3 --warmup 1 --channel 512 --threshold 50
```

For query plans, run `EXPLAIN (ANALYZE, BUFFERS)` manually against the specific
query being changed.

## Ingestion Optimisations

| Idea | Why It May Help | Tradeoff |
|------|------------------|----------|
| Use `COPY` into a staging table | Faster than multiple `INSERT ... SELECT` phases for large seeds | More code and staging cleanup |
| Generate one typed staging table once | Avoids repeating channel generation work per layout | Requires careful transaction handling |
| Batch wide inserts smaller than array/object inserts | Wide insert is currently the slowest seed phase | More knobs to tune |
| Disable or delay secondary indexes during large loads | Reduces write amplification | Need post-load index creation time in measurements |
| Use `UNLOGGED` staging tables | Faster transient seed pipeline | Data lost on crash; not suitable for durable source tables |

## Schema Optimisations

| Idea | Why It May Help | Tradeoff |
|------|------------------|----------|
| Keep only the winning layout in production | Saves 3x duplicate storage/write work | Loses direct apples-to-apples comparisons |
| Add generated columns or expression indexes for hot JSONB channels | Speeds single-channel reads from JSONB | Adds storage and write cost |
| Add BRIN indexes on `created_at` | Useful for append-like time range scans | Low value for full-table benchmarks |
| Partition by time | Reduces scanned data for bounded time windows | More operational complexity |
| Test `real[]` with no GIN index | Current benchmark does full scans; extra indexes may only add write cost | Less flexible for future predicates |

## Query Optimisations

| Idea | Why It May Help | Tradeoff |
|------|------------------|----------|
| Use direct wide-column aggregates for a subset of channels | Fast for known channels | Cannot return 2048 aggregate expressions for all channels in one select list |
| Split wide all-channel min/max into chunks | Avoids target-list limits while keeping direct column aggregates | Multiple queries must be combined |
| Benchmark channel subsets | Many real workloads query fewer than 1024 channels | Less representative of full-scan workloads |
| Add time-window predicates | More realistic for telemetry | Requires time-distributed seed data |
| Compare `jsonb_array_elements` vs `jsonb_array_elements_text` | Avoids text path in some cases | Must measure casts and planner choices |

## PostgreSQL Settings

Test settings per benchmark run, not as untracked assumptions:

```sql
SET jit = off;
SET work_mem = '256MB';
SET max_parallel_workers_per_gather = 4;
SET effective_io_concurrency = 200;
```

Potential database-level settings:

| Setting | Why |
|---------|-----|
| `shared_buffers` | Better cache behavior for repeated benchmark passes |
| `work_mem` | Larger hash/sort operations before spilling |
| `maintenance_work_mem` | Faster index creation after large loads |
| `checkpoint_timeout` / `max_wal_size` | Fewer checkpoints during bulk loading |
| `synchronous_commit = off` for seed-only runs | Faster ingestion when durability during seed is not important |

## Data Model Experiments

| Experiment | Purpose |
|------------|---------|
| `smallint` or scaled integer channels | Test if quantized values are acceptable and faster/smaller |
| `real[]` only | Establish the cost of removing JSONB and wide duplication |
| wide table with channel groups | Split 1024 columns into multiple narrower tables |
| columnar extension outside baseline | Compare against core PostgreSQL after the baseline is known |
| compressed external object storage | Keep raw payload outside PostgreSQL and store derived query shapes in tables |

## Benchmark Harness Improvements

| Improvement | Benefit |
|-------------|---------|
| Save benchmark results as JSON/CSV | Easier comparison across runs and VMs |
| Include `EXPLAIN (ANALYZE, BUFFERS)` capture | Keeps plan changes tied to timing changes |
| Record VM CPU/RAM/disk info | Makes results portable |
| Add `--layouts` and `--metrics` filters | Faster focused iteration |
| Add cold-cache and warm-cache modes | Separates storage I/O from CPU execution |

## Implemented Optimisation Benchmarks

The command below runs focused experiments for the selected channel and
threshold:

```bash
uv run python main.py benchmark-optimisations --iterations 3 --warmup 1 --channel 512 --threshold 50
```

The suite compares no-optimisation threshold scans with these variants:

| Experiment | What It Measures | Build Cost Included |
|------------|------------------|---------------------|
| JSONB array expression index | `count(*)` where one JSONB array element is above threshold | Yes, index build and analyze |
| JSONB object expression index | `count(*)` where one named JSONB key is above threshold | Yes, index build and analyze |
| `real[]` expression index | `count(*)` where one array offset is above threshold | Yes, index build and analyze |
| wide direct column index | `count(*)` where one wide column is above threshold | Yes, index build and analyze |
| hot-channel derived table | Build one narrow table from `real[]`, then query `value > threshold` | Yes, table build, index build, analyze |
| all-channel normalized table | Build `(reading_id, channel_idx, value)` rows from `real[]`, then query one channel | Yes, table build, index build, analyze |
| JSONB array element expansion | Compare `jsonb_array_elements_text` with `jsonb_array_elements` for all-channel threshold counts | No build phase |

The no-optimisation baselines run before any benchmark-created indexes or
derived tables are created. The command removes previous benchmark-created
artifacts for the selected channel at the start of the run.

## Current High-Value Next Steps

1. Add benchmark result export to JSON.
2. Add optional `EXPLAIN (ANALYZE, BUFFERS)` capture per benchmark query.
3. Add time-distributed seed data and benchmark time-window queries with BRIN.
4. Test dropping GIN indexes during seed, then recreate them after loading.
5. Compare the current wide all-channel min/max query with chunked direct-column
   aggregate queries.
