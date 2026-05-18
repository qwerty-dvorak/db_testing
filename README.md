# db_testing — High-Dimensional Sensor Data in PostgreSQL

Benchmarking framework for storing and querying **1028-channel floating-point sensor telemetry** at scale (1M+ rows) in PostgreSQL.

## Quick Start

```bash
# Full setup — database, schema, test data, custom aggregates
./setup.sh

# Python CLI
uv run python main.py status
uv run python main.py generate --rows 1000
uv run python main.py benchmark --iterations 5
uv run python main.py query "SELECT count(*) FROM sensor_payloads"
```

## Project Structure

```
├── setup.sh                     # Shell-based bootstrap
├── setup_db.py                  # Python-based bootstrap
├── main.py                      # CLI toolkit
├── pyproject.toml
├── sql/
│   ├── 01_create_table.sql      # Schema (UUID PK + JSONB payload)
│   ├── 02_generate_sample.sql   # Sample data generator
│   ├── 03_custom_aggregates.sql # Parallel-safe aggregate functions
│   └── 04_benchmark_queries.sql # EXPLAIN ANALYZE benchmark suite
└── docs/
    ├── 01_architecture_overview.md   # Storage layout analysis
    ├── 02_setup_guide.md             # Setup instructions
    ├── 03_benchmarking.md            # Benchmarking methodology
    └── 04_custom_aggregates.md       # Custom aggregate reference
```

## Table Schema

| Column      | Type                     | Description                             |
|-------------|--------------------------|-----------------------------------------|
| `id`        | `UUID` (PK)              | Auto-generated UUID v4                  |
| `payload`   | `JSONB` (NOT NULL)       | 1028-element float8 array              |
| `created_at`| `TIMESTAMPTZ`            | Ingestion timestamp (default now())     |

## Key Documentation

| Document | Covers |
|----------|--------|
| [Architecture Overview](docs/01_architecture_overview.md) | JSONB internals, TOAST, MVCC, memory contexts |
| [Setup Guide](docs/02_setup_guide.md) | Installation, configuration, troubleshooting |
| [Benchmarking](docs/03_benchmarking.md) | EXPLAIN ANALYZE methodology, work_mem tuning |
| [Custom Aggregates](docs/04_custom_aggregates.md) | Aggregate API, state function design, parallel execution |

## Requirements

- PostgreSQL 14+ (18 tested)
- Python 3.13+
- uv (optional, for Python workflow)
