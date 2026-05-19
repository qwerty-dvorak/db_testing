# Fresh VM Runbook

This runbook starts from a clean VM and ends with a verified Docker benchmark
run. It assumes a Debian/Ubuntu-style host. Adjust package commands for other
distributions.

## 1. Install System Packages

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates curl docker.io docker-compose-plugin
```

Enable Docker and let the current user run it:

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker
```

Check Docker:

```bash
docker --version
docker compose version
```

## 2. Clone The Repository

```bash
git clone https://github.com/qwerty-dvorak/db_testing.git
cd db_testing
```

## 3. Start PostgreSQL

The Compose database uses PostgreSQL 14, exposes host port `5433`, and stores
data in the named volume `db_testing_postgres_data`.

```bash
docker compose up -d db
docker compose ps
```

Expected result: `db` is running and healthy.

## 4. Build The App Image

The Dockerfile installs and runs Python through `uv`.

```bash
docker compose build
```

## 5. Create Schema

```bash
docker compose run --rm setup
```

This creates the four current layout tables:

- `sensor_payloads`
- `sensor_payloads_json_object`
- `sensor_payloads_array`
- `sensor_payloads_wide`

## 6. Seed Data

Small smoke seed:

```bash
SEED_ROWS=100 SEED_BATCH_SIZE=100 docker compose run --rm seed
```

Default benchmark seed:

```bash
docker compose run --rm seed
```

The default seed appends 10,000 readings. Each reading is written to all four
tables with the same `id`, `created_at`, and channel values.

## 7. Verify

```bash
docker compose run --rm app uv run python main.py status
docker compose run --rm app uv run python main.py verify
```

Check that every layout reports the same row count.

## 8. Run Benchmarks

Smoke benchmark:

```bash
docker compose run --rm app uv run python main.py benchmark --iterations 1 --warmup 0
```

Standard benchmark:

```bash
docker compose run --rm app uv run python main.py benchmark --iterations 5 --warmup 2 --channel 512 --threshold 50
```

## 9. Connect To PostgreSQL From The Host

Connection details:

```text
host=localhost port=5433 dbname=project_db user=postgres password=postgres
```

Example with `psql` if installed:

```bash
psql "host=localhost port=5433 dbname=project_db user=postgres password=postgres"
```

## 10. Reset Everything

This deletes the persistent Docker database volume.

```bash
docker compose down -v
docker compose up -d db
docker compose run --rm setup
```

## 11. Update An Existing VM Checkout

```bash
cd db_testing
git pull --ff-only
docker compose build
docker compose run --rm app uv run python main.py verify
```

If schema files changed, use a clean volume:

```bash
docker compose down -v
docker compose up -d db
docker compose run --rm setup
docker compose run --rm seed
```

## Troubleshooting

Docker permission denied:

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

Port `5433` already in use:

```bash
sudo ss -ltnp | grep 5433
```

Edit `docker-compose.yml` if another service must keep that port.

Database not healthy:

```bash
docker compose logs db
```

Rebuild without cache:

```bash
docker compose build --no-cache
```
