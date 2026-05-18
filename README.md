# db_testing — High-Dimensional Sensor Data in PostgreSQL

Benchmarking framework for storing and querying **1024-channel floating-point sensor telemetry** at scale (1M+ rows) in PostgreSQL.

## Quick Start

```bash
# Install dependencies
uv sync

# Full setup — database, schema, test data, custom aggregates
./setup.sh

# Or manually:
uv run python setup_db.py

# Status check
uv run python main.py status

# Generate 1000 sample rows with 1024 channels each
uv run python main.py generate --rows 1000 --channels 1024

# Run benchmarks
uv run python main.py benchmark --iterations 5

# Ad-hoc query
uv run python main.py query "SELECT count(*) FROM sensor_payloads"
```

## Project Structure

```
├── setup.sh                     # Shell bootstrap (delegates to setup_db.py)
├── setup_db.py                  # Python bootstrap (idempotent)
├── main.py                      # CLI: status / verify / generate / benchmark / query
├── pyproject.toml
├── scripts/
│   ├── __init__.py
│   ├── connection.py            # psycopg connection helpers
│   ├── schema.py                # Table create / drop / inspect
│   ├── aggregates.py            # Custom aggregate SQL + installer
│   ├── sample_data.py           # Synthetic 1024-channel data generator
│   ├── verify.py                # Verification checks + formatted report
│   └── benchmark.py             # Timed benchmark runner
├── sql/
│   ├── 01_create_table.sql              # PG 18 schema
│   ├── 01_create_table_pg16.sql         # PG 16 schema
│   ├── 02_generate_sample.sql           # PG 18 sample data
│   ├── 02_generate_sample_pg16.sql      # PG 16 sample data
│   ├── 03_custom_aggregates.sql         # PG 18 aggregates
│   ├── 03_custom_aggregates_pg16.sql    # PG 16 aggregates
│   ├── 04_benchmark_queries.sql         # PG 18 benchmarks
│   ├── 04_benchmark_queries_pg16.sql    # PG 16 benchmarks
│   └── 05_1024_channel_layout_benchmarks.sql # Postgres-only layout comparisons
└── docs/
    ├── 01_architecture_overview.md       # JSONB internals, TOAST, MVCC
    ├── 02_setup_guide.md                 # Installation and configuration
    ├── 03_benchmarking.md                # EXPLAIN ANALYZE methodology
    ├── 04_custom_aggregates.md           # Aggregate API reference
    └── 05_1024_channel_performance_plan.md # Postgres-only layout comparisons
```

## Table Schema

| Column      | Type                     | Description                       |
|-------------|--------------------------|-----------------------------------|
| `id`        | `UUID` (PK)              | UUID v4 (`gen_random_uuid()`)     |
| `payload`   | `JSONB` (NOT NULL)       | 1024-element float8 array         |
| `created_at`| `TIMESTAMPTZ`            | Ingestion timestamp               |

## Key Documentation

| Document | Covers |
|----------|--------|
| [Architecture](docs/01_architecture_overview.md) | JSONB internals, TOAST, MVCC, memory contexts |
| [Setup Guide](docs/02_setup_guide.md) | Installation, configuration, troubleshooting |
| [Benchmarking](docs/03_benchmarking.md) | EXPLAIN ANALYZE, work_mem tuning, metrics |
| [Custom Aggregates](docs/04_custom_aggregates.md) | State functions, parallel execution, performance |
| [1024-Channel Plan](docs/05_1024_channel_performance_plan.md) | Postgres-only JSONB, array, normalized, and wide-table benchmarks |

## Requirements

- PostgreSQL 14+ (16 or 18 tested)
- Python 3.13+
- uv 0.5+
