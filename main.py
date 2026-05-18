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


def cmd_status(args: argparse.Namespace) -> None:
    conn = get_conn(args.host, args.port, args.db)
    print(f"Database: {args.db}")
    print(f"Version:  PostgreSQL {server_version(conn)}")
    print(f"Table:    {'exists' if table_exists(conn) else 'missing'}")
    print(f"Rows:     {row_count(conn):,}")
    print(f"Size:     {table_size(conn)}")
    print(f"Aggregates: {'installed' if aggregates_installed(conn) else 'missing'}")
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

    args = parser.parse_args()

    commands = {
        "status": cmd_status,
        "verify": cmd_verify,
        "query": cmd_query,
        "generate": cmd_generate,
        "benchmark": cmd_benchmark,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
