#!/usr/bin/env python3
"""
setup_db.py — Programmatic PostgreSQL database initialisation for project_db.

Connects directly via psycopg (libpq) — no psql binary required.

Usage:
    python setup_db.py
    python setup_db.py --pgdata /custom/path
    python setup_db.py --no-start
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def find_pg_tool(name: str) -> str | None:
    candidates = [
        "/usr/lib/psql18/bin", "/usr/lib/postgresql/*/bin",
        "/usr/pgsql/*/bin", "/opt/homebrew/opt/postgresql@*/bin",
    ]
    for base in candidates:
        for p in Path("/").glob(base.lstrip("/")):
            candidate = p / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    import shutil
    return shutil.which(name)


def start_postgres(pgdata: Path) -> None:
    pg_ctl = find_pg_tool("pg_ctl")
    if pg_ctl is None:
        print("[WARN] pg_ctl not found — assume PostgreSQL is already running")
        return
    status = subprocess.run([pg_ctl, "-D", str(pgdata), "status"],
                            capture_output=True, text=True)
    if status.returncode == 0:
        print(f"[INFO] PostgreSQL already running (data: {pgdata})")
        return
    if not pgdata.exists():
        print(f"[INFO] Initialising data directory at {pgdata} ...")
        subprocess.run([pg_ctl, "initdb", "-D", str(pgdata), "--no-locale", "--encoding=UTF8"], check=True)
    print(f"[INFO] Starting PostgreSQL (data: {pgdata}) ...")
    subprocess.run([pg_ctl, "-D", str(pgdata), "-l", str(pgdata / "logfile"), "start"], check=True)
    time.sleep(2)
    print("[INFO] PostgreSQL started")


def connstr(host: str, port: int, db: str = "project_db") -> str:
    if host.startswith("/"):
        return f"host={host} port={port} dbname={db}"
    return f"host={host} port={port} dbname={db}"


def setup_database(host: str, port: int) -> None:
    import psycopg

    conn = psycopg.connect(connstr(host, port, "postgres"))
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname='project_db'")
    if cur.fetchone() is None:
        cur.execute("CREATE DATABASE project_db")
        print("[INFO] Database 'project_db' created")
    else:
        print("[INFO] Database 'project_db' already exists")
    cur.close()
    conn.close()


def apply_all(host: str, port: int) -> None:
    import psycopg

    conn = psycopg.connect(connstr(host, port, "project_db"))
    cur = conn.cursor()

    # Drop old objects for clean recreation
    for sig in [
        "jsonb_array_avg(jsonb)",
        "extract_channel(jsonb, integer)",
        "float_count_combine(integer, integer)",
        "array_global_count(double precision)",
        "array_global_sum(double precision)",
        "array_global_max(double precision)",
        "array_global_min(double precision)",
        "float_count_state(integer, double precision)",
        "float_sum_state(double precision, double precision)",
        "float_max_state(double precision, double precision)",
        "float_min_state(double precision, double precision)",
        "jsonb_array_to_float8(jsonb)",
    ]:
        try:
            cur.execute(f"DROP AGGREGATE IF EXISTS {sig} CASCADE")
        except Exception:
            try:
                cur.execute(f"DROP FUNCTION IF EXISTS {sig} CASCADE")
            except Exception:
                pass

    conn.commit()

    # ---- Schema ----
    cur.execute("DROP TABLE IF EXISTS sensor_payloads CASCADE")
    cur.execute("""
        CREATE TABLE sensor_payloads (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            payload    JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute("CREATE INDEX idx_sensor_payloads_created_at ON sensor_payloads (created_at DESC)")
    cur.execute("CREATE INDEX idx_sensor_payloads_gin ON sensor_payloads USING GIN (payload jsonb_path_ops)")
    print("  OK  schema")

    # ---- Sample data ----
    cur.execute("""
        INSERT INTO sensor_payloads (payload)
        SELECT jsonb_agg(
            (round((random() * 100.0 + sin(i * 0.01 + s.idx * 0.001) * 5.0
                     + random() * 2.0 - 1.0)::numeric, 6))::float8
            ORDER BY i
        ) AS payload
        FROM generate_series(1, 10) AS s(idx)
        CROSS JOIN generate_series(1, 1028) AS i
        GROUP BY s.idx
    """)
    print("  OK  sample data (10 rows x 1028 channels)")

    # ---- Helper: JSONB array → FLOAT8 column ----
    cur.execute("""
        CREATE OR REPLACE FUNCTION jsonb_array_to_float8(j JSONB)
        RETURNS TABLE(value FLOAT8)
        LANGUAGE SQL IMMUTABLE PARALLEL SAFE
        AS $$ SELECT (jsonb_array_elements_text(j)::FLOAT8) $$
    """)

    # ---- State functions ----
    cur.execute("""
        CREATE OR REPLACE FUNCTION float_min_state(state FLOAT8, incoming FLOAT8)
        RETURNS FLOAT8 LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
        AS $$ BEGIN
            IF state IS NULL THEN RETURN incoming;
            ELSIF incoming < state THEN RETURN incoming;
            ELSE RETURN state; END IF;
        END; $$
    """)
    cur.execute("""
        CREATE OR REPLACE FUNCTION float_max_state(state FLOAT8, incoming FLOAT8)
        RETURNS FLOAT8 LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
        AS $$ BEGIN
            IF state IS NULL THEN RETURN incoming;
            ELSIF incoming > state THEN RETURN incoming;
            ELSE RETURN state; END IF;
        END; $$
    """)
    cur.execute("""
        CREATE OR REPLACE FUNCTION float_sum_state(state FLOAT8, incoming FLOAT8)
        RETURNS FLOAT8 LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
        AS $$ BEGIN
            IF state IS NULL THEN RETURN incoming;
            ELSE RETURN state + incoming; END IF;
        END; $$
    """)
    cur.execute("""
        CREATE OR REPLACE FUNCTION float_count_state(state INT, incoming FLOAT8)
        RETURNS INT LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
        AS $$ BEGIN RETURN COALESCE(state, 0) + 1; END; $$
    """)
    cur.execute("""
        CREATE OR REPLACE FUNCTION float_count_combine(s1 INT, s2 INT)
        RETURNS INT LANGUAGE SQL IMMUTABLE PARALLEL SAFE
        AS $$ SELECT COALESCE(s1, 0) + COALESCE(s2, 0) $$
    """)
    print("  OK  state functions")

    # ---- Custom aggregates ----
    cur.execute("CREATE AGGREGATE array_global_min(FLOAT8) (sfunc = float_min_state, stype = FLOAT8, PARALLEL = SAFE, COMBINEFUNC = float_min_state)")
    cur.execute("CREATE AGGREGATE array_global_max(FLOAT8) (sfunc = float_max_state, stype = FLOAT8, PARALLEL = SAFE, COMBINEFUNC = float_max_state)")
    cur.execute("CREATE AGGREGATE array_global_sum(FLOAT8) (sfunc = float_sum_state, stype = FLOAT8, PARALLEL = SAFE, COMBINEFUNC = float_sum_state)")
    cur.execute("CREATE AGGREGATE array_global_count(FLOAT8) (sfunc = float_count_state, stype = INT, PARALLEL = SAFE, COMBINEFUNC = float_count_combine)")
    print("  OK  custom aggregates")

    # ---- Convenience functions ----
    cur.execute("""
        CREATE OR REPLACE FUNCTION extract_channel(j JSONB, idx INT)
        RETURNS FLOAT8 LANGUAGE SQL IMMUTABLE PARALLEL SAFE
        AS $$ SELECT (j->>idx)::FLOAT8 $$
    """)
    cur.execute("""
        CREATE OR REPLACE FUNCTION jsonb_array_avg(j JSONB)
        RETURNS FLOAT8 LANGUAGE SQL IMMUTABLE PARALLEL SAFE
        AS $$ SELECT avg(value) FROM jsonb_array_to_float8(j) $$
    """)
    print("  OK  helper functions")

    conn.commit()
    cur.close()
    conn.close()
    print("[INFO] All schema, data, and aggregates applied")


def verify(host: str, port: int) -> None:
    import psycopg

    conn = psycopg.connect(connstr(host, port, "project_db"))
    cur = conn.cursor()

    cur.execute("SELECT count(*) FROM sensor_payloads")
    rows = cur.fetchone()[0]

    cur.execute("""
        SELECT array_global_min(v), array_global_max(v), array_global_count(v)
        FROM sensor_payloads, LATERAL jsonb_array_to_float8(payload) AS v
    """)
    gmin, gmax, gcnt = cur.fetchone()

    print(f"\n{'=' * 50}")
    print("  Verification")
    print(f"{'=' * 50}")
    print(f"  Rows in table:          {rows}")
    print(f"  Total float values:     {gcnt:,}")
    print(f"  Global min:             {gmin:.6f}")
    print(f"  Global max:             {gmax:.6f}")

    cur.execute("SELECT id, created_at FROM sensor_payloads LIMIT 2")
    for oid, ts in cur.fetchall():
        print(f"  Sample row:             {oid}  @ {ts}")

    cur.close()
    conn.close()
    print(f"{'=' * 50}")
    print("[INFO] Setup complete!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up project_db for high-dimensional sensor data")
    parser.add_argument("--pgdata", default="/tmp/pgdata", help="PostgreSQL data directory")
    parser.add_argument("--host", default="/tmp", help="PostgreSQL host / socket directory")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL port")
    parser.add_argument("--no-start", action="store_true", help="Skip starting PostgreSQL")
    args = parser.parse_args()

    if not args.no_start:
        start_postgres(Path(args.pgdata))

    import psycopg
    setup_database(args.host, args.port)
    apply_all(args.host, args.port)
    verify(args.host, args.port)


if __name__ == "__main__":
    main()
