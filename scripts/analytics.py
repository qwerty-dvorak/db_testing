"""Postgres-only exact analytics layer for 1024-channel telemetry."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg


ROOT = Path(__file__).resolve().parents[1]
ANALYTICS_SQL = ROOT / "sql" / "06_channel_analytics.sql"


@dataclass
class AnalyticsBenchmark:
    label: str
    sql: str
    elapsed_ms: float
    rows: int


def install_analytics(conn: psycopg.Connection) -> None:
    """Install analytics tables, helper functions, and views."""
    conn.execute(ANALYTICS_SQL.read_text())
    conn.commit()


def analytics_installed(conn: psycopg.Connection) -> bool:
    """Return True when the analytics layer is installed."""
    cur = conn.execute(
        "SELECT 1 FROM pg_class WHERE relname = 'channel_bucket_stats'",
    )
    return cur.fetchone() is not None


def load_raw_from_jsonb(conn: psycopg.Connection, clear_existing: bool = True) -> int:
    """Load typed float8[] raw readings from the existing JSONB baseline table."""
    cur = conn.execute(
        "SELECT load_sensor_readings_raw_from_jsonb(%s)",
        (clear_existing,),
    )
    inserted = int(cur.fetchone()[0])
    conn.commit()
    return inserted


def rebuild_analytics(
    conn: psycopg.Connection,
    bucket_size: str = "1 hour",
    block_size: int = 4096,
) -> None:
    """Rebuild bucket stats and sorted value blocks from typed raw readings."""
    conn.execute(
        "SELECT rebuild_channel_analytics(%s::interval, %s)",
        (bucket_size, block_size),
    )
    conn.commit()


def analytics_status(conn: psycopg.Connection) -> dict[str, Any]:
    """Return row counts and relation sizes for analytics tables."""
    cur = conn.execute("SELECT * FROM channel_analytics_status")
    row = cur.fetchone()
    if row is None:
        return {}
    cols = [desc.name for desc in cur.description]
    return dict(zip(cols, row))


def analytics_time_range(
    conn: psycopg.Connection,
    bucket_size: str = "1 hour",
) -> tuple[str, str] | None:
    """Return an inclusive/exclusive benchmark range as strings.

    Prefer aligned summary buckets so default benchmarks exercise the optimized
    path. Fall back to the exact raw data range when summaries are empty.
    """
    cur = conn.execute(
        """
        SELECT min(bucket_start), max(bucket_start) + %s::interval
        FROM channel_bucket_stats
        """,
        (bucket_size,),
    )
    start, end = cur.fetchone()
    if start is not None and end is not None:
        return str(start), str(end)

    cur = conn.execute(
        """
        SELECT min(created_at), max(created_at)
        FROM sensor_readings_raw
        """,
    )
    start, end = cur.fetchone()
    if start is None or end is None:
        return None
    # Make the upper bound exclusive while still including the max row.
    cur = conn.execute("SELECT (%s::timestamptz + interval '1 microsecond')", (end,))
    exclusive_end = cur.fetchone()[0]
    return str(start), str(exclusive_end)


def run_analytics_benchmarks(
    conn: psycopg.Connection,
    start_at: str | None = None,
    end_at: str | None = None,
    threshold: float = 50.0,
    bucket_size: str = "1 hour",
) -> list[AnalyticsBenchmark]:
    """Run exact summary-backed analytics benchmarks."""
    if start_at is None or end_at is None:
        detected = analytics_time_range(conn, bucket_size)
        if detected is None:
            return []
        start_at, end_at = detected

    queries = [
        (
            "Exact per-channel min/max",
            "SELECT * FROM channel_minmax_exact(%s, %s, %s::interval)",
            (start_at, end_at, bucket_size),
        ),
        (
            "Exact threshold counts",
            "SELECT * FROM channel_threshold_counts_exact(%s, %s, %s, %s::interval)",
            (start_at, end_at, threshold, bucket_size),
        ),
    ]

    results: list[AnalyticsBenchmark] = []
    for label, sql, params in queries:
        t0 = time.perf_counter()
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        results.append(
            AnalyticsBenchmark(
                label=label,
                sql=sql,
                elapsed_ms=elapsed_ms,
                rows=len(rows),
            ),
        )
    return results


def print_status(status: dict[str, Any]) -> None:
    """Print analytics status."""
    if not status:
        print("Analytics layer is not installed or has no status.")
        return

    print("Analytics Status")
    print("-" * 48)
    for key, value in status.items():
        print(f"{key:24s} {value}")


def print_analytics_benchmarks(results: list[AnalyticsBenchmark]) -> None:
    """Print analytics benchmark results."""
    if not results:
        print("No analytics rows available to benchmark.")
        return

    print("Analytics Benchmarks")
    print("-" * 72)
    print(f"{'Query':34s} {'Rows':>10s} {'Elapsed (ms)':>14s}")
    print("-" * 72)
    for result in results:
        print(f"{result.label:34s} {result.rows:>10d} {result.elapsed_ms:>14.1f}")
