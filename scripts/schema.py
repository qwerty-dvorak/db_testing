"""Database schema management for the four sensor payload layouts.

Usage:
    from scripts.connection import get_conn
    from scripts.schema import create_table, drop_table

    conn = get_conn()
    create_table(conn)
    drop_table(conn)
"""

from __future__ import annotations

import psycopg


CHANNEL_COUNT = 1024

LAYOUT_TABLES = [
    "sensor_payloads",
    "sensor_payloads_json_object",
    "sensor_payloads_array",
    "sensor_payloads_wide",
]


def _wide_channel_defs(channels: int = CHANNEL_COUNT) -> str:
    return ",\n    ".join(
        f"ch{i:04d} FLOAT8 NOT NULL" for i in range(1, channels + 1)
    )


CREATE_JSONB_ARRAY_SQL = """
CREATE TABLE IF NOT EXISTS sensor_payloads (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CREATE_JSONB_OBJECT_SQL = """
CREATE TABLE IF NOT EXISTS sensor_payloads_json_object (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CREATE_ARRAY_SQL = """
CREATE TABLE IF NOT EXISTS sensor_payloads_array (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    FLOAT8[] NOT NULL CHECK (array_length(payload, 1) = 1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def create_wide_sql(channels: int = CHANNEL_COUNT) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS sensor_payloads_wide (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    {_wide_channel_defs(channels)}
)
"""


CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_sensor_payloads_created_at "
    "ON sensor_payloads (created_at DESC)",

    "CREATE INDEX IF NOT EXISTS idx_sensor_payloads_gin "
    "ON sensor_payloads USING GIN (payload jsonb_path_ops)",

    "CREATE INDEX IF NOT EXISTS idx_sensor_payloads_json_object_created_at "
    "ON sensor_payloads_json_object (created_at DESC)",

    "CREATE INDEX IF NOT EXISTS idx_sensor_payloads_json_object_gin "
    "ON sensor_payloads_json_object USING GIN (payload jsonb_path_ops)",

    "CREATE INDEX IF NOT EXISTS idx_sensor_payloads_array_created_at "
    "ON sensor_payloads_array (created_at DESC)",

    "CREATE INDEX IF NOT EXISTS idx_sensor_payloads_wide_created_at "
    "ON sensor_payloads_wide (created_at DESC)",
]

COMMENT_SQL = """
COMMENT ON TABLE sensor_payloads IS
    'High-dimensional sensor telemetry -- 1024-channel JSONB payloads';
COMMENT ON TABLE sensor_payloads_json_object IS
    'High-dimensional sensor telemetry -- 1024 named-channel JSONB objects';
COMMENT ON TABLE sensor_payloads_array IS
    'High-dimensional sensor telemetry -- native float8[] payloads';
COMMENT ON TABLE sensor_payloads_wide IS
    'High-dimensional sensor telemetry -- one float8 column per channel';
COMMENT ON COLUMN sensor_payloads.id IS
    'UUID v4, generated via gen_random_uuid()';
COMMENT ON COLUMN sensor_payloads.payload IS
    'JSONB array of 1024 float8 values: [0.123, 0.456, ...]';
COMMENT ON COLUMN sensor_payloads.created_at IS
    'Ingestion timestamp with timezone';
"""


def create_table(conn: psycopg.Connection) -> None:
    """Create all sensor payload layout tables with indexes and comments."""
    conn.execute(CREATE_JSONB_ARRAY_SQL)
    conn.execute(CREATE_JSONB_OBJECT_SQL)
    conn.execute(CREATE_ARRAY_SQL)
    conn.execute(create_wide_sql())
    for sql in CREATE_INDEXES_SQL:
        conn.execute(sql)
    conn.execute(COMMENT_SQL)
    conn.commit()


def drop_table(conn: psycopg.Connection, cascade: bool = True) -> None:
    """Drop all layout tables (and optionally dependent objects)."""
    suffix = " CASCADE" if cascade else ""
    for table in reversed(LAYOUT_TABLES):
        conn.execute(f"DROP TABLE IF EXISTS {table}{suffix}")
    conn.commit()


def table_exists(conn: psycopg.Connection) -> bool:
    """Return True if every layout table exists."""
    cur = conn.execute(
        """
        SELECT count(*)
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
        """,
        (LAYOUT_TABLES,),
    )
    return cur.fetchone()[0] == len(LAYOUT_TABLES)


def row_count(conn: psycopg.Connection) -> int:
    """Return the number of rows in the JSONB-array baseline table."""
    try:
        cur = conn.execute("SELECT count(*) FROM sensor_payloads")
        return cur.fetchone()[0]
    except Exception:
        return 0


def table_size(conn: psycopg.Connection) -> str:
    """Return human-readable total size across all layout tables."""
    cur = conn.execute(
        """
        SELECT pg_size_pretty(
            COALESCE(sum(pg_total_relation_size(to_regclass(table_name))), 0)
        )
        FROM unnest(%s::text[]) AS t(table_name)
        """,
        (LAYOUT_TABLES,),
    )
    return cur.fetchone()[0]


def layout_stats(conn: psycopg.Connection) -> list[dict[str, object]]:
    """Return row count and size for each physical layout table."""
    stats: list[dict[str, object]] = []
    for table in LAYOUT_TABLES:
        cur = conn.execute(
            f"""
            SELECT
                %s AS table_name,
                count(*) AS rows,
                pg_size_pretty(pg_total_relation_size(%s::regclass)) AS size
            FROM {table}
            """,
            (table, table),
        )
        row = cur.fetchone()
        stats.append({"table": row[0], "rows": row[1], "size": row[2]})
    return stats
