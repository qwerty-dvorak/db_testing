# Docker Guide

Docker runs the same Python commands as the local workflow through `uv run`.
The database service is PostgreSQL 14, listens on host port `5433`, and stores
its data in the named Docker volume `db_testing_postgres_data`.

## Services

| Service | Purpose |
|---------|---------|
| `db` | PostgreSQL 14 with persistent volume storage |
| `setup` | Creates the database schema and aggregate functions without dropping existing rows |
| `seed` | Appends generated sensor rows with the bulk insert path |
| `app` | Runs CLI commands against the Docker PostgreSQL database |

## Start PostgreSQL

```bash
docker compose up -d db
```

The database is reachable from the host at:

```text
host=localhost port=5433 dbname=project_db user=postgres password=postgres
```

Inside Compose, app containers use `PGHOST=db` and `PGPORT=5432`.

## Initialise Schema

```bash
docker compose run --rm setup
```

This command uses `setup_db.py --no-reset --rows 0`, so existing data in the
volume remains intact. To intentionally rebuild from scratch, remove the
volume with:

```bash
docker compose down -v
```

Only use `down -v` when you want to delete the persisted PostgreSQL data.

## Seed Persistent Data

```bash
docker compose run --rm setup
docker compose run --rm seed
```

By default this appends 10,000 rows with 1,024 channels using:

```bash
uv run python main.py generate --bulk --rows 10000 --channels 1024 --batch-size 10000
```

Change the seed size with environment variables:

```bash
SEED_ROWS=100000 SEED_BATCH_SIZE=10000 docker compose run --rm seed
```

The seed service appends rows. It does not drop or truncate the table.

## Run CLI Commands

```bash
docker compose run --rm app uv run python main.py status
docker compose run --rm app uv run python main.py verify
docker compose run --rm app uv run python main.py benchmark --iterations 5
docker compose run --rm app uv run python main.py analytics-build --bucket-size "1 hour"
```

## Local Persistent PostgreSQL

For non-Docker development, `setup.sh` and `setup_db.py` use `.pgdata` by
default instead of `/tmp/pgdata`. The `.pgdata` directory is ignored by Git.

```bash
./setup.sh
uv run python main.py status
```
