"""Custom aggregate functions for JSONB array analytics.

Installs parallel-safe custom aggregates for computing min, max, sum,
and count over unnested JSONB float arrays, plus convenience wrappers.

Usage:
    from scripts.connection import get_conn
    from scripts.aggregates import install_aggregates, drop_aggregates

    conn = get_conn()
    install_aggregates(conn)
"""

from __future__ import annotations

import psycopg


# ---- Helper: JSONB array -> FLOAT8 column ----
HELPER_FUNCTIONS = [
    """
    CREATE OR REPLACE FUNCTION jsonb_array_to_float8(j JSONB)
    RETURNS TABLE(value FLOAT8)
    LANGUAGE SQL IMMUTABLE PARALLEL SAFE
    AS $$ SELECT (jsonb_array_elements_text(j)::FLOAT8) $$
    """,
    """
    CREATE OR REPLACE FUNCTION extract_channel(j JSONB, idx INT)
    RETURNS FLOAT8 LANGUAGE SQL IMMUTABLE PARALLEL SAFE
    AS $$ SELECT (j->>idx)::FLOAT8 $$
    """,
    """
    CREATE OR REPLACE FUNCTION jsonb_array_avg(j JSONB)
    RETURNS FLOAT8 LANGUAGE SQL IMMUTABLE PARALLEL SAFE
    AS $$ SELECT avg(value) FROM jsonb_array_to_float8(j) $$
    """,
]

# ---- State transition functions ----
STATE_FUNCTIONS = [
    """
    CREATE OR REPLACE FUNCTION float_min_state(state FLOAT8, incoming FLOAT8)
    RETURNS FLOAT8 LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
    AS $$ BEGIN
        IF state IS NULL THEN RETURN incoming;
        ELSIF incoming < state THEN RETURN incoming;
        ELSE RETURN state; END IF;
    END; $$
    """,
    """
    CREATE OR REPLACE FUNCTION float_max_state(state FLOAT8, incoming FLOAT8)
    RETURNS FLOAT8 LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
    AS $$ BEGIN
        IF state IS NULL THEN RETURN incoming;
        ELSIF incoming > state THEN RETURN incoming;
        ELSE RETURN state; END IF;
    END; $$
    """,
    """
    CREATE OR REPLACE FUNCTION float_sum_state(state FLOAT8, incoming FLOAT8)
    RETURNS FLOAT8 LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
    AS $$ BEGIN
        IF state IS NULL THEN RETURN incoming;
        ELSE RETURN state + incoming; END IF;
    END; $$
    """,
    """
    CREATE OR REPLACE FUNCTION float_count_state(state INT, incoming FLOAT8)
    RETURNS INT LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
    AS $$ BEGIN RETURN COALESCE(state, 0) + 1; END; $$
    """,
    """
    CREATE OR REPLACE FUNCTION float_count_combine(s1 INT, s2 INT)
    RETURNS INT LANGUAGE SQL IMMUTABLE PARALLEL SAFE
    AS $$ SELECT COALESCE(s1, 0) + COALESCE(s2, 0) $$
    """,
]

# ---- Custom aggregate definitions ----
AGGREGATE_DEFS = [
    """
    CREATE AGGREGATE array_global_min(FLOAT8) (
        sfunc = float_min_state,
        stype = FLOAT8,
        PARALLEL = SAFE,
        COMBINEFUNC = float_min_state
    )
    """,
    """
    CREATE AGGREGATE array_global_max(FLOAT8) (
        sfunc = float_max_state,
        stype = FLOAT8,
        PARALLEL = SAFE,
        COMBINEFUNC = float_max_state
    )
    """,
    """
    CREATE AGGREGATE array_global_sum(FLOAT8) (
        sfunc = float_sum_state,
        stype = FLOAT8,
        PARALLEL = SAFE,
        COMBINEFUNC = float_sum_state
    )
    """,
    """
    CREATE AGGREGATE array_global_count(FLOAT8) (
        sfunc = float_count_state,
        stype = INT,
        PARALLEL = SAFE,
        COMBINEFUNC = float_count_combine
    )
    """,
]


def drop_existing(conn: psycopg.Connection) -> None:
    """Drop pre-existing aggregates and functions for a clean install."""

    # Use a separate connection for drops so failures don't abort the main txn
    import psycopg as _psycopg
    info = conn.info
    drop_conn = _psycopg.connect(
        host=info.host, port=info.port, dbname=info.dbname,
    )
    drop_conn.autocommit = True

    drop_targets = [
        ("AGGREGATE", "jsonb_array_avg(jsonb)"),
        ("AGGREGATE", "extract_channel(jsonb, integer)"),
        ("AGGREGATE", "float_count_combine(integer, integer)"),
        ("AGGREGATE", "array_global_count(double precision)"),
        ("AGGREGATE", "array_global_sum(double precision)"),
        ("AGGREGATE", "array_global_max(double precision)"),
        ("AGGREGATE", "array_global_min(double precision)"),
        ("FUNCTION", "float_count_state(integer, double precision)"),
        ("FUNCTION", "float_sum_state(double precision, double precision)"),
        ("FUNCTION", "float_max_state(double precision, double precision)"),
        ("FUNCTION", "float_min_state(double precision, double precision)"),
        ("FUNCTION", "jsonb_array_to_float8(jsonb)"),
    ]
    for kind, sig in drop_targets:
        try:
            drop_conn.execute(f"DROP {kind} IF EXISTS {sig} CASCADE")
        except Exception:
            pass

    drop_conn.close()


def install_aggregates(conn: psycopg.Connection) -> None:
    """Install all custom aggregates, state functions, and helpers."""
    drop_existing(conn)

    for sql in HELPER_FUNCTIONS:
        conn.execute(sql)
    for sql in STATE_FUNCTIONS:
        conn.execute(sql)
    for sql in AGGREGATE_DEFS:
        conn.execute(sql)

    conn.commit()


def aggregates_installed(conn: psycopg.Connection) -> bool:
    """Check if the custom aggregates exist in the database."""
    cur = conn.execute(
        "SELECT 1 FROM pg_proc WHERE proname = 'array_global_min'",
    )
    return cur.fetchone() is not None


def verify_aggregates(conn: psycopg.Connection) -> dict:
    """Run a quick verification of the aggregates and return stats."""
    cur = conn.execute("""
        SELECT
            array_global_min(v) AS min_val,
            array_global_max(v) AS max_val,
            array_global_sum(v) AS sum_val,
            array_global_count(v) AS cnt
        FROM sensor_payloads,
        LATERAL jsonb_array_to_float8(payload) AS v
    """)
    row = cur.fetchone()
    return {
        "global_min": float(row[0]),
        "global_max": float(row[1]),
        "global_sum": float(row[2]),
        "total_values": int(row[3]),
    }
