"""Benchmark suite for JSONB sensor data queries.

Measures wall-clock time for key query patterns:
- Row count (sequential scan)
- Full unnest of all payloads
- Global min/max aggregation
- Per-channel min/max aggregation
- Single-channel extraction

Usage:
    from scripts.connection import get_conn
    from scripts.benchmark import run_benchmarks, print_results

    conn = get_conn()
    results = run_benchmarks(conn, iterations=5)
    print_results(results)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import psycopg


@dataclass
class BenchmarkResult:
    """Timing results for a single benchmark query."""

    label: str
    sql: str
    times_ms: list[float] = field(default_factory=list)
    error: str | None = None

    @property
    def avg_ms(self) -> float:
        return sum(self.times_ms) / len(self.times_ms) if self.times_ms else 0.0

    @property
    def min_ms(self) -> float:
        return min(self.times_ms) if self.times_ms else 0.0

    @property
    def max_ms(self) -> float:
        return max(self.times_ms) if self.times_ms else 0.0


BENCHMARK_QUERIES: list[tuple[str, str]] = [
    (
        "Count rows",
        "SELECT count(*) FROM sensor_payloads",
    ),
    (
        "Global min/max (LATERAL unnest)",
        """
        SELECT array_global_min(v), array_global_max(v)
        FROM sensor_payloads,
        LATERAL jsonb_array_to_float8(payload) AS v
        """,
    ),
    (
        "Per-channel min/max (JSONB ordinality)",
        """
        SELECT
            channel_idx,
            min(value) AS min_value,
            max(value) AS max_value
        FROM sensor_payloads
        CROSS JOIN LATERAL (
            SELECT ord::int - 1 AS channel_idx, value::float8 AS value
            FROM jsonb_array_elements_text(payload) WITH ORDINALITY AS e(value, ord)
            WHERE ord <= 1024
        ) AS channels
        GROUP BY channel_idx
        ORDER BY channel_idx
        """,
    ),
    (
        "Channel 512 min/max/avg",
        """
        SELECT
            min(extract_channel(payload, 511)),
            max(extract_channel(payload, 511)),
            avg(extract_channel(payload, 511))
        FROM sensor_payloads
        """,
    ),
    (
        "Full unnest (all channels)",
        """
        SELECT count(*)
        FROM sensor_payloads,
        LATERAL jsonb_array_to_float8(payload) AS v
        """,
    ),
    (
        "Per-row avg (jsonb_array_avg)",
        """
        SELECT jsonb_array_avg(payload)
        FROM sensor_payloads
        """,
    ),
]


def run_benchmark(
    conn: psycopg.Connection,
    label: str,
    sql: str,
    iterations: int = 5,
    warmup: int = 2,
) -> BenchmarkResult:
    """Run a single benchmark query multiple times.

    Args:
        conn: Active database connection.
        label: Human-readable label.
        sql: SQL query to execute.
        iterations: Number of timed runs (after warmup).
        warmup: Number of untimed warmup runs.

    Returns:
        BenchmarkResult with per-iteration timings.
    """
    result = BenchmarkResult(label=label, sql=sql.strip())

    # Warmup
    for _ in range(warmup):
        try:
            conn.execute(sql)
        except Exception as e:
            result.error = str(e)
            return result

    # Timed runs
    for _ in range(iterations):
        try:
            t0 = time.perf_counter()
            conn.execute(sql)
            elapsed = (time.perf_counter() - t0) * 1000  # ms
            result.times_ms.append(elapsed)
        except Exception as e:
            result.error = str(e)
            return result

    return result


def run_benchmarks(
    conn: psycopg.Connection,
    iterations: int = 5,
    warmup: int = 2,
) -> list[BenchmarkResult]:
    """Run the full benchmark suite.

    Args:
        conn: Active database connection.
        iterations: Number of timed runs per query.
        warmup: Number of untimed warmup runs per query.

    Returns:
        List of BenchmarkResult objects.
    """
    results: list[BenchmarkResult] = []
    n = len(BENCHMARK_QUERIES)

    print(f"Running {n} benchmarks x {iterations} iterations ...\n")

    for i, (label, sql) in enumerate(BENCHMARK_QUERIES, 1):
        print(f"  [{i}/{n}] {label} ...", end=" ", flush=True)
        r = run_benchmark(conn, label, sql, iterations, warmup)
        results.append(r)
        if r.error:
            print(f"ERROR: {r.error}")
        else:
            print(f"avg={r.avg_ms:.1f} ms  (min={r.min_ms:.1f}  max={r.max_ms:.1f})")

    return results


def print_results(results: list[BenchmarkResult]) -> None:
    """Print a formatted summary of benchmark results."""
    line = "-" * 72
    print(f"\n{line}")
    print(f"  {'Query':30s} {'Avg (ms)':>10s} {'Min (ms)':>10s} {'Max (ms)':>10s}")
    print(line)
    for r in results:
        if r.error:
            print(f"  {r.label:30s} {'ERROR':>10s}")
        else:
            print(f"  {r.label:30s} {r.avg_ms:>10.1f} {r.min_ms:>10.1f} {r.max_ms:>10.1f}")
    print(line)
