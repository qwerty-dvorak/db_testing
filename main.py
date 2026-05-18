#!/usr/bin/env python3
"""
db_testing — High-dimensional sensor data benchmarking toolkit.

Usage:
    uv run python main.py --help
    uv run python main.py status
    uv run python main.py query "SELECT count(*) FROM sensor_payloads"
    uv run python main.py generate --rows 100
    uv run python main.py benchmark --iterations 5
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def _find_psql() -> str:
    for p in shutil_which_candidates("psql") or shutil_which_candidates("pgcli"):
        if p:
            return p
    msg = "Cannot find psql or pgcli. Install PostgreSQL client tools."
    raise RuntimeError(msg)


def shutil_which_candidates(name: str) -> list[str]:
    candidates = [
        "/usr/lib/psql18/bin",
        "/usr/lib/postgresql/*/bin",
        "/usr/pgsql/*/bin",
        "/opt/homebrew/opt/postgresql@*/bin",
    ]
    results: list[str] = []
    for base in candidates:
        for p in Path("/").glob(base.lstrip("/")):
            candidate = p / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                results.append(str(candidate))
    import shutil
    if resolved := shutil.which(name):
        results.append(resolved)
    return results


def run_sql(sql: str, psql: str, host: str = "/tmp", port: int = 5432, db: str = "project_db") -> str:
    result = subprocess.run(
        [psql, "-h", host, "-p", str(port), "-d", db, "-c", sql],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() or result.stderr.strip()


def cmd_status(psql: str) -> None:
    print("=== Database Status ===")
    print(run_sql("SELECT current_database(), version(), now()", psql))
    print()
    print(run_sql("SELECT count(*) AS total_rows FROM sensor_payloads", psql))
    print()
    print(run_sql("SELECT pg_size_pretty(pg_total_relation_size('sensor_payloads')) AS total_size", psql))
    print()
    print(run_sql("SELECT pg_size_pretty(pg_table_size('sensor_payloads')) AS table_size", psql))
    print()
    print(run_sql("SELECT pg_size_pretty(pg_indexes_size('sensor_payloads')) AS index_size", psql))


def cmd_query(sql: str, psql: str) -> None:
    print(run_sql(sql, psql))


def cmd_generate(rows: int, psql: str) -> None:
    print(f"Generating {rows} sensor payloads (1028 channels each) ...")
    start = time.perf_counter()
    sql = f"""
    INSERT INTO sensor_payloads (payload)
    SELECT
        jsonb_agg((random() * 100.0)::float8 ORDER BY i) AS payload
    FROM generate_series(1, {rows}) AS s(idx)
    CROSS JOIN generate_series(1, 1028) AS i
    GROUP BY s.idx;
    """
    out = run_sql(sql, psql)
    elapsed = time.perf_counter() - start
    print(f"Inserted {rows} rows in {elapsed:.2f}s ({rows / elapsed:.0f} rows/s)")
    if out:
        print(out)


def cmd_benchmark(iterations: int, psql: str) -> None:
    queries = [
        ("Count rows", "SELECT count(*) FROM sensor_payloads"),
        ("Global min/max (LATERAL unnest)",
         "SELECT array_global_min(v), array_global_max(v) "
         "FROM sensor_payloads, LATERAL jsonb_array_to_float8(payload) AS v"),
        ("Channel 512 avg",
         "SELECT avg(extract_channel(payload, 511)) FROM sensor_payloads"),
    ]

    print(f"Running {iterations} iterations per query (warming caches)...\n")
    for label, sql in queries:
        times: list[float] = []
        for i in range(iterations):
            t0 = time.perf_counter()
            run_sql(sql, psql)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
        avg = sum(times) / len(times)
        print(f"  {label:30s}  avg {avg*1000:7.2f} ms  "
              f"min {min(times)*1000:7.2f} ms  "
              f"max {max(times)*1000:7.2f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(description="High-dimensional sensor data benchmarking toolkit")
    parser.add_argument("--host", default="/tmp", help="PostgreSQL host/socket dir")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL port")
    parser.add_argument("--db", default="project_db", help="Database name")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show database status and table info")
    q = sub.add_parser("query", help="Run an arbitrary SQL query")
    q.add_argument("sql", help="SQL query string")

    g = sub.add_parser("generate", help="Generate test sensor data")
    g.add_argument("--rows", type=int, default=100, help="Number of rows to insert")

    b = sub.add_parser("benchmark", help="Run benchmark suite")
    b.add_argument("--iterations", type=int, default=5, help="Number of iterations per query")

    args = parser.parse_args()

    psql = _find_psql()
    os.environ["PGHOST"] = args.host
    os.environ["PGPORT"] = str(args.port)
    os.environ["PGDATABASE"] = args.db

    if args.command == "status":
        cmd_status(psql)
    elif args.command == "query":
        cmd_query(args.sql, psql)
    elif args.command == "generate":
        cmd_generate(args.rows, psql)
    elif args.command == "benchmark":
        cmd_benchmark(args.iterations, psql)


if __name__ == "__main__":
    main()
