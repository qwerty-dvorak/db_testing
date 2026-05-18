#!/usr/bin/env bash
set -euo pipefail

PGDATA="${PGDATA:-/tmp/pgdata}"
PGPORT="${PGPORT:-5432}"
PGHOST="${PGHOST:-/tmp}"
DB_NAME="${DB_NAME:-project_db}"
PSQL="${PSQL:-}"
PG_CTL="${PG_CTL:-}"

log()  { printf "\033[1;32m[INFO]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[ERR]\033[0m %s\n" "$*" >&2; exit 1; }

find_psql() {
    if [ -n "$PSQL" ] && command -v "$PSQL" &>/dev/null; then
        return 0
    fi
    for dir in /usr/lib/psql18/bin /usr/lib/postgresql/*/bin /usr/pgsql/*/bin /opt/homebrew/opt/postgresql@*/bin; do
        if [ -x "$dir/psql" ]; then
            PSQL="$dir/psql"
            return 0
        fi
    done
    if command -v pgcli &>/dev/null; then
        warn "psql not found — using pgcli as fallback"
        PSQL="pgcli"
        return 0
    fi
    return 1
}

find_pg_ctl() {
    if [ -n "$PG_CTL" ] && command -v "$PG_CTL" &>/dev/null; then
        return 0
    fi
    for dir in /usr/lib/psql18/bin /usr/lib/postgresql/*/bin /usr/pgsql/*/bin /opt/homebrew/opt/postgresql@*/bin; do
        if [ -x "$dir/pg_ctl" ]; then
            PG_CTL="$dir/pg_ctl"
            return 0
        fi
    done
    return 1
}

run_psql() {
    if [ "$PSQL" = "pgcli" ]; then
        echo "$1" | pgcli -h "$PGHOST" "$DB_NAME" 2>&1 | tail -3
    else
        "$PSQL" -h "$PGHOST" -p "$PGPORT" -d "$DB_NAME" -c "$1" 2>&1
    fi
}

run_psql_db() {
    local db=$1 sql=$2
    if [ "$PSQL" = "pgcli" ]; then
        echo "$sql" | pgcli -h "$PGHOST" "$db" 2>&1 | tail -3
    else
        "$PSQL" -h "$PGHOST" -p "$PGPORT" -d "$db" -c "$sql" 2>&1
    fi
}

exec_sql_file() {
    if [ "$PSQL" = "pgcli" ]; then
        local sql; sql=$(cat "$1")
        echo "$sql" | pgcli -h "$PGHOST" "$DB_NAME" 2>&1 | tail -5
    else
        "$PSQL" -h "$PGHOST" -p "$PGPORT" -d "$DB_NAME" -f "$1" 2>&1
    fi
}

check_deps() {
    find_psql       || err "Cannot find psql or pgcli. Install postgresql-client."
    find_pg_ctl     || err "Cannot find pg_ctl. Install postgresql."
    log "Using PSQL: $PSQL"
    log "Using PG_CTL: $PG_CTL"
}

start_postgres() {
    if "$PG_CTL" -D "$PGDATA" status &>/dev/null; then
        log "PostgreSQL is already running (PID: $("$PG_CTL" -D "$PGDATA" status 2>/dev/null | grep -oP '\d+' || true))"
        return 0
    fi
    if [ ! -d "$PGDATA" ]; then
        log "Initialising data directory at $PGDATA ..."
        "$PG_CTL" initdb -D "$PGDATA" --no-locale --encoding=UTF8
    fi
    log "Starting PostgreSQL on port $PGPORT (socket: $PGHOST) ..."
    "$PG_CTL" -D "$PGDATA" -l "$PGDATA/logfile" start
    sleep 2
    log "PostgreSQL started successfully"
}

create_database() {
    local exists
    if [ "$PSQL" = "pgcli" ]; then
        exists=$(echo "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | pgcli -h "$PGHOST" postgres 2>&1 | grep -c "1" || true)
    else
        exists=$("$PSQL" -h "$PGHOST" -p "$PGPORT" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null || echo "0")
    fi
    if [ "$exists" = "1" ]; then
        log "Database '$DB_NAME' already exists"
    else
        log "Creating database '$DB_NAME' ..."
        if [ "$PSQL" = "pgcli" ]; then
            echo "CREATE DATABASE $DB_NAME;" | pgcli -h "$PGHOST" postgres 2>&1 | tail -3
        else
            "$PSQL" -h "$PGHOST" -p "$PGPORT" -d postgres -c "CREATE DATABASE $DB_NAME;" 2>&1
        fi
        log "Database '$DB_NAME' created"
    fi
}

setup_schema() {
    log "Creating pgcrypto extension (if not exists) ..."
    run_psql_db "$DB_NAME" "CREATE EXTENSION IF NOT EXISTS pgcrypto;"

    log "Creating sensor_payloads table ..."
    exec_sql_file "$(dirname "$0")/sql/01_create_table.sql"
    log "Table 'sensor_payloads' is ready"
}

generate_test_data() {
    log "Generating sample sensor data (100 rows) ..."
    exec_sql_file "$(dirname "$0")/sql/02_generate_sample.sql"
    log "Test data inserted"
}

create_aggregates() {
    log "Creating custom aggregate functions ..."
    exec_sql_file "$(dirname "$0")/sql/03_custom_aggregates.sql"
    log "Custom aggregates installed"
}

verify() {
    log "=== Verification ==="
    run_psql "SELECT count(*) AS row_count FROM sensor_payloads;"
    run_psql "SELECT id, created_at, jsonb_typeof(payload) AS payload_type FROM sensor_payloads LIMIT 3;"
    log "Setup complete!"
}

main() {
    check_deps
    start_postgres
    create_database
    setup_schema
    create_aggregates
    generate_test_data
    verify
}

main "$@"
