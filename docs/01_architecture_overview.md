# Architecture Overview

This project benchmarks 1024-channel sensor readings in PostgreSQL using four
physical layouts. Each generated reading is written to every layout with the
same `id`, `created_at`, and channel values.

## Layouts

| Table | Shape | Notes |
|-------|-------|-------|
| `sensor_payloads` | JSONB array | Compact API shape, but every analytical query extracts and casts JSONB values |
| `sensor_payloads_json_object` | JSONB object with `ch0001` ... `ch1024` keys | Self-describing payload, larger than the array because every row repeats keys |
| `sensor_payloads_array` | `real[]` | Typed positional array; still TOASTed, but avoids JSONB parsing/casts |
| `sensor_payloads_wide` | 1024 `real` columns | Direct column reads; rigid schema; viable with `real`, not `float8`, because 1024 `float8` columns exceed PostgreSQL row-size limits |

## Why `real` For Typed Layouts

PostgreSQL heap rows must fit on an 8 KB page before TOAST can help. A wide
table with 1024 `float8` columns needs at least 8192 bytes for channel values
before tuple overhead, so inserts fail with a row-size error. The typed array
and wide-table layouts use `real` (`float4`) to keep the 1024-column wide table
valid while preserving a direct native-float comparison against JSONB layouts.

## Real-Time Analysis

There are no summary tables or precomputed analysis builds in the CLI.
Benchmarks run the actual query work:

- single-channel min/max/avg
- all-channel min/max
- all-channel threshold counts
- row counts

Timing includes extraction, casts, unnesting, grouping, threshold checks, and
result fetches.

## Storage Expectations

JSONB object storage is usually largest because each row stores 1024 repeated
key names. JSONB array avoids repeated keys but still has JSONB encoding and
TOAST overhead. `real[]` is usually the smallest typed layout. Wide rows can be
fast for single-column scans and threshold counts, but all-channel min/max uses
a generated lateral `VALUES` query to return one row per channel.
