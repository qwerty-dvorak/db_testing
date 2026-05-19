# db_testing — High-Dimensional Sensor Data in PostgreSQL

Benchmarking framework for storing and querying **1024-channel floating-point sensor telemetry** at scale (1M+ rows) in PostgreSQL.

## Quick Start

### Docker

```bash
# Start persistent PostgreSQL 14 on host port 5433
docker compose up -d db

# Initialise schema/aggregates without deleting existing data
docker compose run --rm setup

# Append 10,000 generated rows using the bulk insert path
docker compose run --rm seed

# Run CLI commands through uv inside Docker
docker compose run --rm app uv run python main.py status
docker compose run --rm app uv run python main.py benchmark --iterations 5
```

Database files are stored in the named Docker volume `db_testing_postgres_data`.
PostgreSQL is exposed to the host at `localhost:5433`. See
[Docker Guide](docs/07_docker.md) for setup, seeding, reset, and CLI workflows.

### Local

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

# Compare JSONB array, JSONB object, float8[], and wide-table layouts in real time
uv run python main.py benchmark --iterations 5 --warmup 2 --threshold 50

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
│   └── benchmark.py             # Real-time four-layout benchmark runner
├── sql/
│   ├── 01_create_table.sql              # PG 18 schema
│   ├── 01_create_table_pg16.sql         # PG 16 schema
│   ├── 02_generate_sample.sql           # PG 18 sample data
│   ├── 02_generate_sample_pg16.sql      # PG 16 sample data
│   ├── 03_custom_aggregates.sql         # PG 18 aggregates
│   ├── 03_custom_aggregates_pg16.sql    # PG 16 aggregates
│   ├── 04_benchmark_queries.sql         # PG 18 benchmarks
│   ├── 04_benchmark_queries_pg16.sql    # PG 16 benchmarks
│   ├── 05_1024_channel_layout_benchmarks.sql # Postgres-only layout comparisons
│   └── 06_channel_analytics.sql         # Historical summary/block analytics SQL
└── docs/
    ├── 01_architecture_overview.md       # JSONB internals, TOAST, MVCC
    ├── 02_setup_guide.md                 # Installation and configuration
    ├── 03_benchmarking.md                # EXPLAIN ANALYZE methodology
    ├── 04_custom_aggregates.md           # Aggregate API reference
    ├── 05_1024_channel_performance_plan.md # Postgres-only layout comparisons
    ├── 06_channel_analytics_layer.md     # Historical summary-layer notes
    └── 07_docker.md                      # Docker, persistent storage, and seeding
```

## Storage Layouts

Every generated reading is inserted into four tables with the same `id`,
`created_at`, and 1024 channel values:

| Table | Layout |
|-------|--------|
| `sensor_payloads` | JSONB array payload |
| `sensor_payloads_json_object` | JSONB object payload with `ch0001` ... `ch1024` keys |
| `sensor_payloads_array` | Native `float8[]` payload |
| `sensor_payloads_wide` | 1024 `float8` columns |

## Key Documentation

| Document | Covers |
|----------|--------|
| [Architecture](docs/01_architecture_overview.md) | JSONB internals, TOAST, MVCC, memory contexts |
| [Setup Guide](docs/02_setup_guide.md) | Installation, configuration, troubleshooting |
| [Benchmarking](docs/03_benchmarking.md) | EXPLAIN ANALYZE, work_mem tuning, metrics |
| [Custom Aggregates](docs/04_custom_aggregates.md) | State functions, parallel execution, performance |
| [1024-Channel Plan](docs/05_1024_channel_performance_plan.md) | Real-time JSONB array, JSONB object, float8[], and wide-table benchmarks |
| [Channel Analytics Layer](docs/06_channel_analytics_layer.md) | Historical notes for the removed precomputed summary approach |
| [Docker Guide](docs/07_docker.md) | PostgreSQL 14 containers, persistent volume storage, port 5433, and bulk seeding |

## Requirements

- PostgreSQL 14+ (16 or 18 tested)
- Python 3.10+
- uv 0.5+
