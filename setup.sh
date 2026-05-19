#!/usr/bin/env bash
# ============================================================================
# setup.sh — Full bootstrap of project_db via uv
#
#   1. Starts PostgreSQL (if not running)
#   2. Creates the project_db database
#   3. Creates the sensor_payloads table
#   4. Installs custom aggregate functions
#   5. Inserts sample data
#   6. Runs verification
# ============================================================================
set -euo pipefail

PGDATA="${PGDATA:-/tmp/pgdata}"
DB_NAME="${DB_NAME:-project_db}"
SAMPLE_ROWS="${SAMPLE_ROWS:-100}"

log()  { printf "\033[1;32m[INFO]\033[0m %s\n" "$*"; }
err()  { printf "\033[1;31m[ERR]\033[0m %s\n" "$*" >&2; exit 1; }

command -v uv >/dev/null 2>&1 || err "uv not found (install from https://docs.astral.sh/uv/)"

log "uv: $(uv --version)"
log "Data dir:    $PGDATA"
log "Database:    $DB_NAME"
log "Sample rows: $SAMPLE_ROWS"
echo ""

uv run python setup_db.py \
    --pgdata "$PGDATA" \
    --db "$DB_NAME" \
    --rows "$SAMPLE_ROWS"

log "All done! Run 'uv run python main.py status' to check."
