# Setup Guide

## Requirements

| Dependency | Version |
|------------|---------|
| PostgreSQL | 14+ |
| Python | 3.10+ |
| uv | 0.5+ |
| Docker | Optional, for the container workflow |

Use `uv` for all Python commands.

## Local Setup

```bash
uv sync
./setup.sh
uv run python main.py status
uv run python main.py verify
```

`setup.sh` stores local PostgreSQL data in `.pgdata` by default. The directory
is ignored by Git.

Manual equivalent:

```bash
uv run python setup_db.py --pgdata .pgdata --rows 100
```

For an already-running PostgreSQL server:

```bash
PGHOST=/tmp PGPORT=5432 PGDATABASE=project_db uv run python setup_db.py --no-start
```

## Docker Setup

```bash
docker compose up -d db
docker compose run --rm setup
docker compose run --rm seed
docker compose run --rm app uv run python main.py status
```

Docker PostgreSQL listens on host port `5433` and stores data in the
`db_testing_postgres_data` volume. See [Docker](04_docker.md).

## CLI Commands

```bash
uv run python main.py status
uv run python main.py verify
uv run python main.py generate --rows 1000 --channels 1024
uv run python main.py generate --bulk --rows 10000 --channels 1024 --batch-size 10000
uv run python main.py benchmark --iterations 5 --warmup 2 --threshold 50
uv run python main.py query "SELECT count(*) FROM sensor_payloads"
```

## Schema

Setup creates four tables:

| Table | Payload shape |
|-------|---------------|
| `sensor_payloads` | JSONB array: `[12.3, 45.6, ...]` |
| `sensor_payloads_json_object` | JSONB object: `{"ch0001": 12.3, ...}` |
| `sensor_payloads_array` | Native `real[]` |
| `sensor_payloads_wide` | Columns `ch0001 real` through `ch1024 real` |

`generate` appends the same generated readings to all four tables. `setup_db.py`
uses `--reset` by default, which drops and recreates the current four-layout
schema. Use `--no-reset` only when you intentionally want to keep existing rows
and the existing schema already matches the current code.

## Resetting Data

Local:

```bash
rm -rf .pgdata
./setup.sh
```

Docker:

```bash
docker compose down -v
docker compose up -d db
docker compose run --rm setup
```
