# db_testing

PostgreSQL benchmark project for 1024-channel sensor readings. It stores the
same generated data in four physical layouts and compares them with real-time
queries.

## Quick Start

Docker:

```bash
docker compose up -d db
docker compose run --rm setup
docker compose run --rm seed
docker compose run --rm app uv run python main.py status
docker compose run --rm app uv run python main.py benchmark --iterations 5 --warmup 2
docker compose run --rm app uv run python main.py benchmark-optimisations --iterations 3 --warmup 1
```

Local:

```bash
uv sync
./setup.sh
uv run python main.py status
uv run python main.py benchmark --iterations 5 --warmup 2
```

PostgreSQL in Docker is exposed on `localhost:5433` and persists data in the
`db_testing_postgres_data` volume.

## Layouts

Every generated reading is inserted into all four tables with the same `id`,
`created_at`, and 1024 channel values.

| Table | Layout |
|-------|--------|
| `sensor_payloads` | JSONB array payload |
| `sensor_payloads_json_object` | JSONB object payload with `ch0001` ... `ch1024` keys |
| `sensor_payloads_array` | Native `real[]` payload |
| `sensor_payloads_wide` | 1024 `real` columns |

The typed layouts use `real` because a 1024-column `float8` wide table exceeds
PostgreSQL heap-row size limits.

## CLI

Use `uv run` for every Python command:

```bash
uv run python setup_db.py --rows 100
uv run python main.py verify
uv run python main.py generate --bulk --rows 10000 --channels 1024 --batch-size 10000
uv run python main.py benchmark --iterations 5 --warmup 2 --channel 512 --threshold 50
uv run python main.py benchmark-optimisations --iterations 3 --warmup 1 --channel 512 --threshold 50
uv run python main.py query "SELECT count(*) FROM sensor_payloads"
```

Benchmark output includes warmup times, every timed run, result row counts,
avg/min/median/max/stdev, and total measured query time.
The optimisation benchmark also reports table-build time, index-build time,
query time, total time including build work, and speedup against the matching
baseline threshold scan where available.

## Project Structure

```text
├── Dockerfile
├── docker-compose.yml
├── main.py
├── setup_db.py
├── setup.sh
├── pyproject.toml
├── uv.lock
├── scripts/
│   ├── benchmark.py       # real-time four-layout benchmark suite
│   ├── connection.py      # PostgreSQL connection helpers
│   ├── sample_data.py     # same-data generator for all four layouts
│   ├── schema.py          # current four-layout schema
│   └── verify.py          # consistency and size checks
├── sql/
│   └── realtime_layout_reference.sql
└── docs/
    ├── 01_architecture_overview.md
    ├── 02_setup_guide.md
    ├── 03_benchmarking.md
    ├── 04_docker.md
    ├── 05_1024_channel_performance_plan.md
    ├── 06_fresh_vm_runbook.md
    └── 07_possible_optimisations.md
```

## Docs

| Document | Covers |
|----------|--------|
| [Architecture](docs/01_architecture_overview.md) | Four layouts, row-size limits, real-time analysis model |
| [Setup](docs/02_setup_guide.md) | Local and Docker setup, reset workflow, CLI commands |
| [Benchmarking](docs/03_benchmarking.md) | Query groups, optimisation runs, timing output, plan inspection |
| [Docker](docs/04_docker.md) | Compose services, port 5433, volume reset |
| [Layout Reference](docs/05_1024_channel_performance_plan.md) | Schema shapes and tradeoffs |
| [Fresh VM Runbook](docs/06_fresh_vm_runbook.md) | Start from a clean VM and run setup, seed, verify, benchmark |
| [Possible Optimisations](docs/07_possible_optimisations.md) | Ingestion, schema, query, PostgreSQL, and harness improvements |

## Requirements

- PostgreSQL 14+
- Python 3.10+
- uv 0.5+
