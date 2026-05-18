# Setup Guide — project_db

## Prerequisites

| Dependency      | Minimum Version | Check Command                 |
|-----------------|-----------------|-------------------------------|
| PostgreSQL      | 14 (18 tested)  | `pg_config --version`         |
| Python          | 3.13            | `python3 --version`           |
| uv              | 0.5+            | `uv --version`                |

## Quick Start (Shell)

```bash
# 1 — set up the database, schema, test data, and aggregates
./setup.sh

# 2 — verify
./setup.sh  # runs verification at the end
```

## Quick Start (Python)

```bash
# 1 — install dependencies
uv sync

# 2 — run the Python setup
uv run python setup_db.py

# 3 — verify with the CLI
uv run python main.py status
```

## Manual Step-by-Step

### 1. Initialise and Start PostgreSQL

```bash
# Initialise a data directory
pg_ctl initdb -D /tmp/pgdata --no-locale --encoding=UTF8

# Start the server
pg_ctl -D /tmp/pgdata -l /tmp/pgdata/logfile start
```

### 2. Create the Database

```bash
psql -h /tmp -d postgres -c "CREATE DATABASE project_db;"
```

### 3. Create the Table

```bash
psql -h /tmp -d project_db -f sql/01_create_table.sql
```

### 4. Install Custom Aggregates

```bash
psql -h /tmp -d project_db -f sql/03_custom_aggregates.sql
```

### 5. Load Test Data

```bash
psql -h /tmp -d project_db -f sql/02_generate_sample.sql
```

### 6. Verify

```bash
psql -h /tmp -d project_db -c "SELECT count(*) FROM sensor_payloads;"
```

## Table Schema

```sql
CREATE TABLE sensor_payloads (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## Custom Aggregate Functions

| Function              | Description                                      |
|-----------------------|--------------------------------------------------|
| `jsonb_array_to_float8(j JSONB)` | Set-returning: extracts all floats from a JSONB array |
| `array_global_min(FLOAT8)`       | Minimum value across all unnested rows           |
| `array_global_max(FLOAT8)`       | Maximum value across all unnested rows           |
| `array_global_sum(FLOAT8)`       | Running sum (parallel-safe)                      |
| `array_global_count(FLOAT8)`     | Running count (parallel-safe)                    |
| `jsonb_array_avg(j JSONB)`       | Average of all floats in a single JSONB array    |
| `extract_channel(j JSONB, idx)`  | Extract a specific channel by 0-based index      |

## Benchmarking

```bash
# Run 5 iterations of each benchmark query
uv run python main.py benchmark --iterations 5

# Generate 1,000 rows of test data
uv run python main.py generate --rows 1000

# Run an ad-hoc query
uv run python main.py query "SELECT count(*) FROM sensor_payloads"
```

## Troubleshooting

**PostgreSQL won't start:**
```bash
# Check the log
cat /tmp/pgdata/logfile | tail -20

# Ensure no stale PID file
rm -f /tmp/pgdata/postmaster.pid
```

**psql not found:**
```bash
# Void Linux
sudo xbps-install postgresql18-client

# Or use pgcli as fallback
pip install pgcli
```

**Socket connection fails:**
```bash
# Find the socket
ls /tmp/.s.PGSQL.*
# Connect explicitly
psql -h /tmp -d project_db
```

**TOAST-related performance:**
```sql
-- Check TOAST table size
SELECT relname, pg_size_pretty(pg_total_relation_size(oid))
FROM pg_class WHERE reltoastrelid != 0;
```
