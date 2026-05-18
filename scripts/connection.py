"""Database connection utilities.

Usage:
    from scripts.connection import get_conn, connstr
    conn = get_conn()
    conn = get_conn(host="/tmp", port=5432, dbname="project_db")
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import psycopg.conninfo


def connstr(host: str = "/tmp", port: int = 5432, dbname: str = "project_db") -> str:
    """Build a libpq connection string.

    Detects Unix socket (path starting with /) vs. TCP hostname.
    """
    if host.startswith("/"):
        return f"host={host} port={port} dbname={dbname}"
    return f"host={host} port={port} dbname={dbname}"


def get_conn(
    host: str = "/tmp",
    port: int = 5432,
    dbname: str = "project_db",
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


def pgdata_dir() -> Path | None:
    """Return the PGDATA directory by probing pg_ctl or the running server."""
    import shutil
    import subprocess

    # Try pg_ctl
    pg_ctl = shutil.which("pg_ctl")
    if pg_ctl:
        result = subprocess.run(
            [pg_ctl, "status", "-D", "/tmp/pgdata"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return Path("/tmp/pgdata")

    # Try querying the server
    try:
        conn = psycopg.connect(connstr(dbname="postgres"))
        cur = conn.execute("SHOW data_directory")
        val = cur.fetchone()[0]
        conn.close()
        return Path(val)
    except Exception:
        pass

    return None
