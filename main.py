#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.13"
# dependencies = ["psycopg>=3.2"]
# ///
"""
db_testing — High-dimensional sensor data benchmarking toolkit.

Usage:
    uv run python main.py status
    uv run python main.py verify
    uv run python main.py generate --rows 1000
    uv run python main.py benchmark --iterations 5
    uv run python main.py query "SELECT count(*) FROM sensor_payloads"
"""

from __future__ import annotations

import argparse
import sys

from scripts.connection import get_conn, server_version
from scripts.schema import table_exists, row_count, table_size
from scripts.aggregates import verify_aggregates, aggregates_installed
from scripts.sample_data import generate_samples
from scripts.benchmark import run_benchmarks, print_results
from scripts.verify import verify_all, print_report
from scripts.analytics import (
    analytics_installed,
    analytics_status,
    install_analytics,
    load_raw_from_jsonb,
    print_analytics_benchmarks,
    print_status,
    rebuild_analytics,
    run_analytics_benchmarks,
)


def cmd_status(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    print(f"Database: {args.db}")
    print(f"Version:  PostgreSQL {server_version(conn)}")
    print(f"Table:    {'exists' if table_exists(conn) else 'missing'}")
    print(f"Rows:     {row_count(conn):,}")
    print(f"Size:     {table_size(conn)}")
    print(f"Aggregates: {'installed' if aggregates_installed(conn) else 'missing'}")
    print(f"Analytics:  {'installed' if analytics_installed(conn) else 'missing'}")
    conn.close()


def cmd_verify(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    report = verify_all(conn)
    print_report(report)
    conn.close()


def cmd_query(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    cur = conn.execute(args.sql)
    for row in cur.fetchall():
        print("\t".join(str(c) for c in row))
    conn.close()


def cmd_generate(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    generate_samples(conn, n_rows=args.rows, channels=args.channels)
    conn.close()
    print(f"Done. Total rows: {row_count(get_conn(args.host, args.port, args.db)):,}")


def cmd_benchmark(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    results = run_benchmarks(conn, iterations=args.iterations)
    print_results(results)
    conn.close()


def cmd_analytics_init(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    install_analytics(conn)
    print("Analytics layer installed.")
    conn.close()


def cmd_analytics_build(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    install_analytics(conn)
    inserted = load_raw_from_jsonb(conn, clear_existing=not args.append_raw)
    print(f"Loaded/updated raw array rows: {inserted:,}")
    rebuild_analytics(conn, bucket_size=args.bucket_size, block_size=args.block_size)
    print(
        "Rebuilt channel analytics "
        f"(bucket_size={args.bucket_size}, block_size={args.block_size})."
    )
    print_status(analytics_status(conn))
    conn.close()


def cmd_analytics_status(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    print_status(analytics_status(conn))
    conn.close()


def cmd_analytics_benchmark(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    results = run_analytics_benchmarks(
        conn,
        start_at=args.start,
        end_at=args.end,
        threshold=args.threshold,
        bucket_size=args.bucket_size,
    )
    print_analytics_benchmarks(results)
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="High-dimensional sensor data benchmarking toolkit",
    )
    parser.add_argument("--host", default="/tmp", help="PostgreSQL host / socket dir")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL port")
    parser.add_argument("--db", default="project_db", help="Database name")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show database and table status")
    sub.add_parser("verify", help="Run full verification report")

    q = sub.add_parser("query", help="Run an arbitrary SQL query")
    q.add_argument("sql", help="SQL query string")

    g = sub.add_parser("generate", help="Generate sample sensor data")
    g.add_argument("--rows", type=int, default=100, help="Number of rows to insert")
    g.add_argument("--channels", type=int, default=1024, help="Channels per row")

    b = sub.add_parser("benchmark", help="Run benchmark suite")
    b.add_argument("--iterations", type=int, default=5, help="Runs per query")

    sub.add_parser("analytics-init", help="Install analytics tables and functions")

    ab = sub.add_parser(
        "analytics-build",
        help="Load typed raw readings and rebuild exact analytics summaries",
    )
    ab.add_argument(
        "--bucket-size",
        default="1 hour",
        help="date_bin bucket interval for summaries (default: 1 hour)",
    )
    ab.add_argument(
        "--block-size",
        type=int,
        default=4096,
        help="Sorted values per threshold block (default: 4096)",
    )
    ab.add_argument(
        "--append-raw",
        action="store_true",
        help="Do not clear sensor_readings_raw before loading from JSONB",
    )

    sub.add_parser("analytics-status", help="Show analytics table row counts and sizes")

    aq = sub.add_parser(
        "analytics-benchmark",
        help="Benchmark summary-backed min/max and threshold queries",
    )
    aq.add_argument("--start", help="Inclusive timestamptz lower bound")
    aq.add_argument("--end", help="Exclusive timestamptz upper bound")
    aq.add_argument("--threshold", type=float, default=50.0, help="Threshold value")
    aq.add_argument(
        "--bucket-size",
        default="1 hour",
        help="Summary bucket interval used during build (default: 1 hour)",
    )

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "verify": cmd_verify,
        "query": cmd_query,
        "generate": cmd_generate,
        "benchmark": cmd_benchmark,
        "analytics-init": cmd_analytics_init,
        "analytics-build": cmd_analytics_build,
        "analytics-status": cmd_analytics_status,
        "analytics-benchmark": cmd_analytics_benchmark,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
