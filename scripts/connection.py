"""Database connection utilities.

Usage:
    from scripts.connection import get_conn
    conn = get_conn()
    conn = get_conn(host="/tmp", port=5432, dbname="project_db")
"""

from __future__ import annotations

import os

import psycopg


def connstr(
    host: str | None = None,
    port: int | None = None,
    dbname: str | None = None,
) -> str:
    """Build a libpq connection string from args or PG* environment vars."""
    host = host or os.getenv("PGHOST", "/tmp")
    port = port or int(os.getenv("PGPORT", "5432"))
    dbname = dbname or os.getenv("PGDATABASE", "project_db")
    return f"host={host} port={port} dbname={dbname}"


def get_conn(
    host: str | None = None,
    port: int | None = None,
    dbname: str | None = None,
    autocommit: bool = False,
) -> psycopg.Connection:
    """Return a psycopg connection to the target database.

    Args:
        host: Unix socket directory (e.g. /tmp) or TCP hostname.
        port: PostgreSQL port (default 5432).
        dbname: Database name (default project_db).
        autocommit: Enable autocommit mode.

    Returns:
        psycopg.Connection
    """
    conn = psycopg.connect(connstr(host, port, dbname))
    if autocommit:
        conn.autocommit = True
    return conn


def server_version(conn: psycopg.Connection) -> int:
    """Return the server version as an integer (e.g. 160004 for 16.4)."""
    cur = conn.execute("SELECT current_setting('server_version_num')::int")
    return cur.fetchone()[0]
