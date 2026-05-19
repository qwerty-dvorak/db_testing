#!/usr/bin/env -S uv run python
# /// script
# requires-python = ">=3.10"
# dependencies = ["psycopg>=3.2"]
# ///
"""
db_testing — High-dimensional sensor data benchmarking toolkit.

Usage:
    uv run python main.py status
    uv run python main.py verify
    uv run python main.py generate --rows 1000
    uv run python main.py benchmark --iterations 5
    uv run python main.py benchmark-optimisations --iterations 3
    uv run python main.py query "SELECT count(*) FROM sensor_payloads"
"""

from __future__ import annotations

import argparse
import os

from scripts.connection import get_conn, server_version
from scripts.schema import layout_stats, table_exists, row_count, table_size
from scripts.sample_data import generate_bulk, generate_samples
from scripts.benchmark import (
    print_optimisation_results,
    print_results,
    run_benchmarks,
    run_optimisation_benchmarks,
)
from scripts.verify import verify_all, print_report


def cmd_status(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    print(f"Database: {args.db}")
    print(f"Version:  PostgreSQL {server_version(conn)}")
    print(f"Schema:   {'complete' if table_exists(conn) else 'missing'}")
    print(f"Rows:     {row_count(conn):,}")
    print(f"Size:     {table_size(conn)}")
    print("Layouts:")
    try:
        for stat in layout_stats(conn):
            print(
                f"  {stat['table']:28s} "
                f"rows={stat['rows']:>10,} size={stat['size']}"
            )
    except Exception as e:
        print(f"  unavailable: {e}")
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
    if args.bulk:
        generate_bulk(
            conn,
            n_rows=args.rows,
            channels=args.channels,
            batch_size=args.batch_size,
        )
    else:
        generate_samples(
            conn,
            n_rows=args.rows,
            channels=args.channels,
            batch_size=args.batch_size,
        )
    conn.close()
    conn = get_conn(args.host, args.port, args.db)
    total_rows = row_count(conn)
    conn.close()
    print(f"Done. Total rows: {total_rows:,}")


def cmd_benchmark(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    results = run_benchmarks(
        conn,
        iterations=args.iterations,
        warmup=args.warmup,
        channel_index=args.channel - 1,
        threshold=args.threshold,
    )
    print_results(results)
    conn.close()


def cmd_benchmark_optimisations(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    results = run_optimisation_benchmarks(
        conn,
        iterations=args.iterations,
        warmup=args.warmup,
        channel_index=args.channel - 1,
        threshold=args.threshold,
    )
    print_optimisation_results(results)
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="High-dimensional sensor data benchmarking toolkit",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("PGHOST", "/tmp"),
        help="PostgreSQL host / socket dir",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PGPORT", "5432")),
        help="PostgreSQL port",
    )
    parser.add_argument(
        "--db",
        default=os.getenv("PGDATABASE", "project_db"),
        help="Database name",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show database and table status")
    sub.add_parser("verify", help="Run full verification report")

    q = sub.add_parser("query", help="Run an arbitrary SQL query")
    q.add_argument("sql", help="SQL query string")

    g = sub.add_parser("generate", help="Generate sample sensor data")
    g.add_argument("--rows", type=int, default=100, help="Number of rows to insert")
    g.add_argument("--channels", type=int, default=1024, help="Channels per row")
    g.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Rows per server-side INSERT batch",
    )
    g.add_argument(
        "--bulk",
        action="store_true",
        help="Use large server-side INSERT batches for seeding larger datasets",
    )

    b = sub.add_parser("benchmark", help="Run benchmark suite")
    b.add_argument("--iterations", type=int, default=5, help="Runs per query")
    b.add_argument("--warmup", type=int, default=2, help="Warmup runs per query")
    b.add_argument(
        "--channel",
        type=int,
        default=512,
        help="1-based channel number for single-channel benchmarks",
    )
    b.add_argument(
        "--threshold",
        type=float,
        default=50.0,
        help="Threshold for per-channel count benchmarks",
    )

    bo = sub.add_parser(
        "benchmark-optimisations",
        aliases=["benchmark-optimizations"],
        help="Run threshold optimisation benchmarks with build time included",
    )
    bo.add_argument("--iterations", type=int, default=5, help="Runs per query")
    bo.add_argument("--warmup", type=int, default=2, help="Warmup runs per query")
    bo.add_argument(
        "--channel",
        type=int,
        default=512,
        help="1-based channel number for threshold benchmarks",
    )
    bo.add_argument(
        "--threshold",
        type=float,
        default=50.0,
        help="Threshold for channel count benchmarks",
    )

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "verify": cmd_verify,
        "query": cmd_query,
        "generate": cmd_generate,
        "benchmark": cmd_benchmark,
        "benchmark-optimisations": cmd_benchmark_optimisations,
        "benchmark-optimizations": cmd_benchmark_optimisations,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
