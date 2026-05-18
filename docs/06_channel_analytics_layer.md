# Exact Channel Analytics Layer

This layer optimizes practical 1024-channel workloads without TimescaleDB or storage extensions. It keeps raw data rebuildable, but answers large analytical queries from derived Postgres tables.

## Workflow

```bash
# 1. Generate or load baseline JSONB readings.
uv run python main.py generate --rows 1000000 --channels 1024

# 2. Install analytics tables/functions, convert JSONB to float8[], and build summaries.
uv run python main.py analytics-build --bucket-size "1 hour" --block-size 4096

# 3. Check derived table sizes.
uv run python main.py analytics-status

# 4. Benchmark exact summary-backed queries.
uv run python main.py analytics-benchmark --threshold 50
```

## Tables

| Table | Purpose |
|-------|---------|
| `sensor_readings_raw` | Typed `float8[]` copy of the raw 1024-channel readings |
| `channel_bucket_stats` | Exact `count`, `min`, `max`, and `sum` per `(bucket_start, channel_idx)` |
| `channel_value_blocks` | Sorted value blocks per `(bucket_start, channel_idx)` for exact threshold counts |

The raw source can be rebuilt from the existing `sensor_payloads` JSONB table with:

```sql
SELECT load_sensor_readings_raw_from_jsonb(true);
```

The summaries can be rebuilt with:

```sql
SELECT rebuild_channel_analytics('1 hour'::interval, 4096);
```

## Query Algorithms

### Per-Channel Min/Max

For full buckets, min/max reads only `channel_bucket_stats`. For partial boundary buckets, `channel_minmax_exact()` scans `sensor_readings_raw` only for the boundary fragments and combines the results.

```sql
SELECT *
FROM channel_minmax_exact(
    '2026-01-01 00:00:00+00',
    '2026-01-02 00:00:00+00',
    '1 hour'
);
```

### Ad-Hoc Threshold Counts

`channel_threshold_counts_exact()` counts rows where each channel is strictly greater than an arbitrary threshold.

For full buckets:

- Blocks with `value_max <= threshold` are skipped.
- Blocks with `value_min > threshold` are counted fully.
- Boundary blocks use `float8_count_le(sorted_values, threshold)`, a binary search over the sorted block array.

For partial boundary buckets, raw readings are scanned only for those fragments.

```sql
SELECT *
FROM channel_threshold_counts_exact(
    '2026-01-01 00:00:00+00',
    '2026-01-02 00:00:00+00',
    50.0,
    '1 hour'
);
```

## Tuning Defaults

| Setting | Default | Notes |
|---------|---------|-------|
| Bucket size | `1 hour` | Use smaller buckets for more precise time slicing and less raw boundary scanning |
| Block size | `4096` | Larger blocks reduce metadata rows; smaller blocks reduce boundary search/scanning work |
| Raw time index | BRIN on `created_at` | Compact and effective for append-like time-series ingest |

For million-plus rows, start with `1 hour` buckets and `4096` values per block. Change one parameter at a time and compare `EXPLAIN (ANALYZE, BUFFERS)` output.
