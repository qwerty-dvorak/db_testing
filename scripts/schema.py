"""Database schema management — create / drop the sensor_payloads table.

Usage:
    from scripts.connection import get_conn
    from scripts.schema import create_table, drop_table

    conn = get_conn()
    create_table(conn)
    drop_table(conn)
"""

from __future__ import annotations

import psycopg


# SQL statements (PostgreSQL 13+ compatible — uses built-in gen_random_uuid)
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sensor_payloads (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_sensor_payloads_created_at "
    "ON sensor_payloads (created_at DESC)",

    "CREATE INDEX IF NOT EXISTS idx_sensor_payloads_gin "
    "ON sensor_payloads USING GIN (payload jsonb_path_ops)",
]

COMMENT_SQL = """
COMMENT ON TABLE sensor_payloads IS
    'High-dimensional sensor telemetry -- 1024-channel JSONB payloads';
COMMENT ON COLUMN sensor_payloads.id IS
    'UUID v4, generated via gen_random_uuid()';
COMMENT ON COLUMN sensor_payloads.payload IS
    'JSONB array of 1024 float8 values: [0.123, 0.456, ...]';
COMMENT ON COLUMN sensor_payloads.created_at IS
    'Ingestion timestamp with timezone';
"""


def create_table(conn: psycopg.Connection) -> None:
    """Create the sensor_payloads table with indexes and comments."""
    cur = conn.execute(CREATE_TABLE_SQL)
    for sql in CREATE_INDEXES_SQL:
        conn.execute(sql)
    conn.execute(COMMENT_SQL)
    conn.commit()


def drop_table(conn: psycopg.Connection, cascade: bool = True) -> None:
    """Drop the sensor_payloads table (and optionally dependent objects)."""
    sql = "DROP TABLE IF EXISTS sensor_payloads"
    if cascade:
        sql += " CASCADE"
    conn.execute(sql)
    conn.commit()


def table_exists(conn: psycopg.Connection) -> bool:
    """Return True if the sensor_payloads table exists."""
    cur = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'sensor_payloads'",
    )
    return cur.fetchone() is not None


def row_count(conn: psycopg.Connection) -> int:
    """Return the number of rows in sensor_payloads."""
    try:
        cur = conn.execute("SELECT count(*) FROM sensor_payloads")
        return cur.fetchone()[0]
    except Exception:
        return 0


def table_size(conn: psycopg.Connection) -> str:
    """Return human-readable table size."""
    cur = conn.execute(
        "SELECT pg_size_pretty(pg_total_relation_size('sensor_payloads'))",
    )
    return cur.fetchone()[0]
