# Docker

Docker uses the same `uv run` commands as local development.

## Services

| Service | Purpose |
|---------|---------|
| `db` | PostgreSQL 14 on host port `5433` with persistent volume storage |
| `setup` | Creates the current four-layout schema |
| `seed` | Appends generated readings to all four tables |
| `app` | Runs CLI commands against the Docker database |

## Start

```bash
docker compose up -d db
docker compose run --rm setup
docker compose run --rm seed
docker compose run --rm app uv run python main.py status
```

The database is reachable from the host at:

```text
host=localhost port=5433 dbname=project_db user=postgres password=postgres
```

Inside Compose, app containers use `PGHOST=db` and `PGPORT=5432`.

## Seed Size

Default seed:

```bash
docker compose run --rm seed
```

Custom seed:

```bash
SEED_ROWS=100000 SEED_BATCH_SIZE=10000 docker compose run --rm seed
```

## Run Commands

```bash
docker compose run --rm app uv run python main.py verify
docker compose run --rm app uv run python main.py benchmark --iterations 5 --warmup 2
docker compose run --rm app uv run python main.py benchmark-optimisations --iterations 3 --warmup 1 --channel 512 --threshold 50
docker compose run --rm app uv run python main.py query "SELECT count(*) FROM sensor_payloads"
```

`benchmark-optimisations` creates benchmark-only indexes and derived tables,
then includes that build time in the reported totals. It drops prior
benchmark-created artifacts for the selected channel at the start of each run.

## Reset

There is no compatibility migration layer. If the schema changes or you want a
clean database, remove the Docker volume:

```bash
docker compose down -v
docker compose up -d db
docker compose run --rm setup
```
