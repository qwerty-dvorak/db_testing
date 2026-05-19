"""Database verification utilities.

Usage:
    from scripts.connection import get_conn
    from scripts.verify import verify_all, print_report

    conn = get_conn()
    report = verify_all(conn)
    print_report(report)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg


@dataclass
class VerificationReport:
    """Structured output from verify_all()."""

    table_exists: bool = False
    row_count: int = 0
    total_values: int = 0
    global_min: float = 0.0
    global_max: float = 0.0
    global_sum: float = 0.0
    table_size: str = "unknown"
    index_count: int = 0
    aggregates_ok: bool = False
    layout_counts: dict[str, int] = field(default_factory=dict)
    layout_sizes: dict[str, str] = field(default_factory=dict)
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def verify_all(conn: psycopg.Connection) -> VerificationReport:
    """Run all verification queries and return a report."""
    report = VerificationReport()

    try:
        # Table existence
        cur = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'sensor_payloads'",
        )
        report.table_exists = cur.fetchone() is not None
    except Exception as e:
        report.errors.append(f"table check: {e}")

    if not report.table_exists:
        return report

    try:
        cur = conn.execute("SELECT count(*) FROM sensor_payloads")
        report.row_count = cur.fetchone()[0]
    except Exception as e:
        report.errors.append(f"row count: {e}")

    try:
        cur = conn.execute(
            "SELECT pg_size_pretty(pg_total_relation_size('sensor_payloads'))",
        )
        report.table_size = cur.fetchone()[0]
    except Exception as e:
        report.errors.append(f"table size: {e}")

    try:
        cur = conn.execute(
            "SELECT count(*) FROM pg_indexes WHERE tablename = 'sensor_payloads'",
        )
        report.index_count = cur.fetchone()[0]
    except Exception as e:
        report.errors.append(f"index count: {e}")

    for table in [
        "sensor_payloads",
        "sensor_payloads_json_object",
        "sensor_payloads_array",
        "sensor_payloads_wide",
    ]:
        try:
            cur = conn.execute(f"SELECT count(*) FROM {table}")
            report.layout_counts[table] = int(cur.fetchone()[0])
            cur = conn.execute(
                "SELECT pg_size_pretty(pg_total_relation_size(%s::regclass))",
                (table,),
            )
            report.layout_sizes[table] = str(cur.fetchone()[0])
        except Exception as e:
            report.errors.append(f"{table} layout check: {e}")

    if report.layout_counts:
        distinct_counts = set(report.layout_counts.values())
        if len(distinct_counts) > 1:
            report.errors.append(f"layout row counts differ: {report.layout_counts}")

    # Aggregates
    try:
        cur = conn.execute(
            "SELECT 1 FROM pg_proc WHERE proname = 'array_global_min'",
        )
        report.aggregates_ok = cur.fetchone() is not None
    except Exception as e:
        report.errors.append(f"aggregate check: {e}")

    if report.aggregates_ok and report.row_count > 0:
        try:
            cur = conn.execute("""
                SELECT
                    array_global_min(v),
                    array_global_max(v),
                    array_global_sum(v),
                    array_global_count(v)
                FROM sensor_payloads,
                LATERAL jsonb_array_to_float8(payload) AS v
            """)
            r = cur.fetchone()
            report.global_min = float(r[0])
            report.global_max = float(r[1])
            report.global_sum = float(r[2])
            report.total_values = int(r[3])
        except Exception as e:
            report.errors.append(f"aggregate query: {e}")

    try:
        cur = conn.execute("""
            SELECT id, created_at,
                   (payload->>0)::float8 AS channel_0
            FROM sensor_payloads LIMIT 3
        """)
        for row in cur.fetchall():
            report.sample_rows.append({
                "id": str(row[0]),
                "created_at": str(row[1]),
                "channel_0": float(row[2]),
            })
    except Exception as e:
        report.errors.append(f"sample rows: {e}")

    return report


def print_report(report: VerificationReport) -> None:
    """Print a formatted verification report."""
    line = "=" * 52
    print(f"\n{line}")
    print("  Verification Report")
    print(line)

    if not report.table_exists:
        print("  [WARN] sensor_payloads table does not exist")
        return

    print(f"  Table exists:          {report.table_exists}")
    print(f"  Row count:             {report.row_count:,}")
    print(f"  Total float values:    {report.total_values:,}")
    print(f"  Table size:            {report.table_size}")
    print(f"  Indexes:               {report.index_count}")
    print(f"  Global min:            {report.global_min:.6f}")
    print(f"  Global max:            {report.global_max:.6f}")
    print(f"  Aggregates installed:  {report.aggregates_ok}")

    if report.layout_counts:
        print("  Layouts:")
        for table, rows in report.layout_counts.items():
            size = report.layout_sizes.get(table, "unknown")
            print(f"    {table:28s} rows={rows:>10,} size={size}")

    if report.sample_rows:
        print(f"  Sample rows:")
        for s in report.sample_rows:
            print(f"    {s['id'][:8]}... | {s['created_at']} | ch0={s['channel_0']:.4f}")

    if report.errors:
        print(f"  Errors ({len(report.errors)}):")
        for e in report.errors:
            print(f"    - {e}")

    print(line)
