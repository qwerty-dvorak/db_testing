#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.13"
# dependencies = ["psycopg>=3.2"]
# ///
"""
setup_db.py — Full database initialisation for project_db.

Delegates to scripts/ modules for all operations.
Connects via psycopg -- no psql binary required.

Usage:
    uv run python setup_db.py
    uv run python setup_db.py --pgdata /var/pgdata
    uv run python setup_db.py --no-start --rows 1000
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg

from scripts.connection import connstr, get_conn
from scripts.schema import create_table, drop_table
from scripts.aggregates import install_aggregates
from scripts.sample_data import generate_samples
from scripts.verify import verify_all, print_report


def find_pg_ctl() -> str | None:
    """Locate pg_ctl on the filesystem."""
    import shutil
    candidates = [
        "/usr/lib/psql18/bin", "/usr/lib/postgresql/*/bin",
        "/usr/pgsql/*/bin", "/opt/homebrew/opt/postgresql@*/bin",
    ]
    for base in candidates:
        for p in Path("/").glob(base.lstrip("/")):
            candidate = p / "pg_ctl"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return shutil.which("pg_ctl")


def start_postgres(pgdata: Path) -> None:
    """Initialise (if needed) and start a local PostgreSQL instance."""
    pg_ctl = find_pg_ctl()
    if pg_ctl is None:
        print("[WARN] pg_ctl not found -- assume PostgreSQL is already running")
        return

    status = subprocess.run(
        [pg_ctl, "-D", str(pgdata), "status"],
        capture_output=True, text=True,
    )
    if status.returncode == 0:
        print(f"[INFO] PostgreSQL already running (data: {pgdata})")
        return

    if not pgdata.exists():
        print(f"[INFO] Initialising data directory at {pgdata} ...")
        subprocess.run(
            [pg_ctl, "initdb", "-D", str(pgdata), "--no-locale", "--encoding=UTF8"],
            check=True,
        )

    print(f"[INFO] Starting PostgreSQL (data: {pgdata}) ...")
    subprocess.run(
        [pg_ctl, "-D", str(pgdata), "-l", str(pgdata / "logfile"), "start"],
        check=True,
    )
    time.sleep(2)
    print("[INFO] PostgreSQL started")


def create_database(host: str, port: int) -> None:
    """Create project_db if it does not exist."""
    conn = get_conn(host, port, "postgres", autocommit=True)
    cur = conn.execute("SELECT 1 FROM pg_database WHERE datname='project_db'")
    if cur.fetchone() is None:
        conn.execute("CREATE DATABASE project_db")
        print("[INFO] Database 'project_db' created")
    else:
        print("[INFO] Database 'project_db' already exists")
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up project_db for high-dimensional sensor data",
    )
    parser.add_argument(
        "--pgdata", default="/tmp/pgdata",
        help="PostgreSQL data directory (default: /tmp/pgdata)",
    )
    parser.add_argument(
        "--host", default="/tmp",
        help="PostgreSQL host / socket directory (default: /tmp)",
    )
    parser.add_argument(
        "--port", type=int, default=5432, help="PostgreSQL port (default: 5432)",
    )
    parser.add_argument(
        "--no-start", action="store_true",
        help="Skip starting PostgreSQL (assume already running)",
    )
    parser.add_argument(
        "--rows", type=int, default=100,
        help="Number of sample rows to insert (default: 100)",
    )
    args = parser.parse_args()

    if not args.no_start:
        start_postgres(Path(args.pgdata))

    create_database(args.host, args.port)

    conn = get_conn(args.host, args.port, "project_db")

    print("\n[1/4] Creating schema ...")
    drop_table(conn)
    create_table(conn)

    print("[2/4] Installing custom aggregates ...")
    install_aggregates(conn)

    print(f"[3/4] Generating {args.rows} sample rows ...")
    generate_samples(conn, n_rows=args.rows)

    print("[4/4] Verification ...")
    report = verify_all(conn)
    print_report(report)

    conn.close()


if __name__ == "__main__":
    main()
