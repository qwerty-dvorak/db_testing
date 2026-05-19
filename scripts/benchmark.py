"""Real-time benchmark suite for four 1024-channel storage layouts.

Compares:
- JSONB array: sensor_payloads
- JSONB key-value object: sensor_payloads_json_object
- Native float8[]: sensor_payloads_array
- Wide table: sensor_payloads_wide

All analytical work is done inside the timed query. There is no separate
analytics build step.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg


CHANNEL_COUNT = 1024
DEFAULT_CHANNEL_INDEX = 511
DEFAULT_THRESHOLD = 50.0


@dataclass(frozen=True)
class BenchmarkQuery:
    """A single SQL benchmark for one physical layout."""

    layout: str
    metric: str
    sql: str
    params: tuple[Any, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.layout}: {self.metric}"


@dataclass
class BenchmarkResult:
    """Timing results for a single benchmark query."""

    layout: str
    metric: str
    sql: str
    params: tuple[Any, ...] = ()
    warmup_ms: list[float] = field(default_factory=list)
    times_ms: list[float] = field(default_factory=list)
    rows_returned: int = 0
    first_row: tuple[Any, ...] | None = None
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

    @property
    def median_ms(self) -> float:
        return statistics.median(self.times_ms) if self.times_ms else 0.0

    @property
    def stdev_ms(self) -> float:
        return statistics.stdev(self.times_ms) if len(self.times_ms) > 1 else 0.0

    @property
    def total_ms(self) -> float:
        return sum(self.warmup_ms) + sum(self.times_ms)


def _wide_all_channel_minmax_sql(channels: int = CHANNEL_COUNT) -> str:
    aggregates = ",\n        ".join(
        f"min(ch{i:04d}) AS min_ch{i:04d}, max(ch{i:04d}) AS max_ch{i:04d}"
        for i in range(1, channels + 1)
    )
    values = ",\n        ".join(
        f"({i - 1}, agg.min_ch{i:04d}, agg.max_ch{i:04d})"
        for i in range(1, channels + 1)
    )
    return f"""
    WITH agg AS (
        SELECT
        {aggregates}
        FROM sensor_payloads_wide
    )
    SELECT channel_idx, min_value, max_value
    FROM agg
    CROSS JOIN LATERAL (
        VALUES
        {values}
    ) AS v(channel_idx, min_value, max_value)
    ORDER BY channel_idx
    """


def _wide_threshold_sql(channels: int = CHANNEL_COUNT) -> str:
    aggregates = ",\n        ".join(
        f"count(*) FILTER (WHERE ch{i:04d} > %s) AS cnt_ch{i:04d}"
        for i in range(1, channels + 1)
    )
    values = ",\n        ".join(
        f"({i - 1}, agg.cnt_ch{i:04d})"
        for i in range(1, channels + 1)
    )
    return f"""
    WITH agg AS (
        SELECT
        {aggregates}
        FROM sensor_payloads_wide
    )
    SELECT channel_idx, count_above_threshold
    FROM agg
    CROSS JOIN LATERAL (
        VALUES
        {values}
    ) AS v(channel_idx, count_above_threshold)
    ORDER BY channel_idx
    """


def build_benchmark_queries(
    channel_index: int = DEFAULT_CHANNEL_INDEX,
    threshold: float = DEFAULT_THRESHOLD,
    channels: int = CHANNEL_COUNT,
) -> list[BenchmarkQuery]:
    """Build real-time comparison queries for every layout."""
    if not 0 <= channel_index < channels:
        raise ValueError(f"channel_index must be between 0 and {channels - 1}")

    channel_ordinal = channel_index + 1
    channel_key = f"ch{channel_ordinal:04d}"
    wide_column = f"ch{channel_ordinal:04d}"
    threshold_params = tuple(threshold for _ in range(channels))

    return [
        BenchmarkQuery(
            "JSONB array",
            "count rows",
            "SELECT count(*) FROM sensor_payloads",
        ),
        BenchmarkQuery(
            "JSONB object",
            "count rows",
            "SELECT count(*) FROM sensor_payloads_json_object",
        ),
        BenchmarkQuery(
            "float8[]",
            "count rows",
            "SELECT count(*) FROM sensor_payloads_array",
        ),
        BenchmarkQuery(
            "wide",
            "count rows",
            "SELECT count(*) FROM sensor_payloads_wide",
        ),
        BenchmarkQuery(
            "JSONB array",
            f"channel {channel_ordinal} min/max/avg",
            """
            SELECT
                min((payload->>%s)::float8),
                max((payload->>%s)::float8),
                avg((payload->>%s)::float8)
            FROM sensor_payloads
            """,
            (channel_index, channel_index, channel_index),
        ),
        BenchmarkQuery(
            "JSONB object",
            f"channel {channel_ordinal} min/max/avg",
            """
            SELECT
                min((payload->>%s)::float8),
                max((payload->>%s)::float8),
                avg((payload->>%s)::float8)
            FROM sensor_payloads_json_object
            """,
            (channel_key, channel_key, channel_key),
        ),
        BenchmarkQuery(
            "float8[]",
            f"channel {channel_ordinal} min/max/avg",
            """
            SELECT min(payload[%s]), max(payload[%s]), avg(payload[%s])
            FROM sensor_payloads_array
            """,
            (channel_ordinal, channel_ordinal, channel_ordinal),
        ),
        BenchmarkQuery(
            "wide",
            f"channel {channel_ordinal} min/max/avg",
            f"""
            SELECT min({wide_column}), max({wide_column}), avg({wide_column})
            FROM sensor_payloads_wide
            """,
        ),
        BenchmarkQuery(
            "JSONB array",
            "all-channel min/max",
            """
            SELECT
                ord::int - 1 AS channel_idx,
                min(value::float8) AS min_value,
                max(value::float8) AS max_value
            FROM sensor_payloads
            CROSS JOIN LATERAL jsonb_array_elements_text(payload)
                WITH ORDINALITY AS e(value, ord)
            GROUP BY ord
            ORDER BY ord
            """,
        ),
        BenchmarkQuery(
            "JSONB object",
            "all-channel min/max",
            """
            SELECT
                right(key, 4)::int - 1 AS channel_idx,
                min(value::float8) AS min_value,
                max(value::float8) AS max_value
            FROM sensor_payloads_json_object
            CROSS JOIN LATERAL jsonb_each_text(payload) AS e(key, value)
            GROUP BY key
            ORDER BY channel_idx
            """,
        ),
        BenchmarkQuery(
            "float8[]",
            "all-channel min/max",
            """
            SELECT
                ord::int - 1 AS channel_idx,
                min(value) AS min_value,
                max(value) AS max_value
            FROM sensor_payloads_array
            CROSS JOIN LATERAL unnest(payload) WITH ORDINALITY AS u(value, ord)
            GROUP BY ord
            ORDER BY ord
            """,
        ),
        BenchmarkQuery(
            "wide",
            "all-channel min/max",
            _wide_all_channel_minmax_sql(channels),
        ),
        BenchmarkQuery(
            "JSONB array",
            f"all-channel count > {threshold:g}",
            """
            SELECT
                ord::int - 1 AS channel_idx,
                count(*) FILTER (WHERE value::float8 > %s) AS count_above_threshold
            FROM sensor_payloads
            CROSS JOIN LATERAL jsonb_array_elements_text(payload)
                WITH ORDINALITY AS e(value, ord)
            GROUP BY ord
            ORDER BY ord
            """,
            (threshold,),
        ),
        BenchmarkQuery(
            "JSONB object",
            f"all-channel count > {threshold:g}",
            """
            SELECT
                right(key, 4)::int - 1 AS channel_idx,
                count(*) FILTER (WHERE value::float8 > %s) AS count_above_threshold
            FROM sensor_payloads_json_object
            CROSS JOIN LATERAL jsonb_each_text(payload) AS e(key, value)
            GROUP BY key
            ORDER BY channel_idx
            """,
            (threshold,),
        ),
        BenchmarkQuery(
            "float8[]",
            f"all-channel count > {threshold:g}",
            """
            SELECT
                ord::int - 1 AS channel_idx,
                count(*) FILTER (WHERE value > %s) AS count_above_threshold
            FROM sensor_payloads_array
            CROSS JOIN LATERAL unnest(payload) WITH ORDINALITY AS u(value, ord)
            GROUP BY ord
            ORDER BY ord
            """,
            (threshold,),
        ),
        BenchmarkQuery(
            "wide",
            f"all-channel count > {threshold:g}",
            _wide_threshold_sql(channels),
            threshold_params,
        ),
    ]


def _execute_fetch(
    conn: psycopg.Connection,
    sql: str,
    params: tuple[Any, ...],
) -> tuple[float, list[tuple[Any, ...]]]:
    t0 = time.perf_counter()
    cur = conn.execute(sql, params)
    rows = cur.fetchall()
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return elapsed_ms, rows


def run_benchmark(
    conn: psycopg.Connection,
    query: BenchmarkQuery,
    iterations: int = 5,
    warmup: int = 2,
) -> BenchmarkResult:
    """Run one benchmark query multiple times and fetch all result rows."""
    result = BenchmarkResult(
        layout=query.layout,
        metric=query.metric,
        sql=query.sql.strip(),
        params=query.params,
    )

    for _ in range(warmup):
        try:
            elapsed_ms, rows = _execute_fetch(conn, query.sql, query.params)
            result.warmup_ms.append(elapsed_ms)
            result.rows_returned = len(rows)
            result.first_row = rows[0] if rows else None
        except Exception as e:
            result.error = str(e)
            return result

    for _ in range(iterations):
        try:
            elapsed_ms, rows = _execute_fetch(conn, query.sql, query.params)
            result.times_ms.append(elapsed_ms)
            result.rows_returned = len(rows)
            result.first_row = rows[0] if rows else None
        except Exception as e:
            result.error = str(e)
            return result

    return result


def run_benchmarks(
    conn: psycopg.Connection,
    iterations: int = 5,
    warmup: int = 2,
    channel_index: int = DEFAULT_CHANNEL_INDEX,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[BenchmarkResult]:
    """Run the full real-time layout comparison suite."""
    queries = build_benchmark_queries(channel_index=channel_index, threshold=threshold)
    results: list[BenchmarkResult] = []
    n = len(queries)

    print(
        f"Running {n} real-time benchmarks x {iterations} timed iterations "
        f"(warmup={warmup}, channel={channel_index + 1}, threshold={threshold:g}) ...\n"
    )

    suite_t0 = time.perf_counter()
    for i, query in enumerate(queries, 1):
        print(f"  [{i}/{n}] {query.label}")
        result = run_benchmark(conn, query, iterations, warmup)
        results.append(result)
        if result.error:
            print(f"      ERROR: {result.error}")
            continue

        warmup_text = ", ".join(f"{t:.1f}" for t in result.warmup_ms) or "none"
        run_text = ", ".join(f"{t:.1f}" for t in result.times_ms)
        print(f"      rows returned: {result.rows_returned:,}")
        print(f"      warmup ms:     {warmup_text}")
        print(f"      timed ms:      {run_text}")
        print(
            "      summary ms:    "
            f"avg={result.avg_ms:.1f} min={result.min_ms:.1f} "
            f"median={result.median_ms:.1f} max={result.max_ms:.1f} "
            f"stdev={result.stdev_ms:.1f} total={result.total_ms:.1f}"
        )

    suite_ms = (time.perf_counter() - suite_t0) * 1000
    print(f"\nBenchmark suite wall time: {suite_ms:.1f} ms")
    return results


def print_results(results: list[BenchmarkResult]) -> None:
    """Print a formatted summary of benchmark results."""
    line = "-" * 112
    print(f"\n{line}")
    print(
        f"  {'Layout':16s} {'Metric':30s} {'Rows':>8s} "
        f"{'Avg':>10s} {'Min':>10s} {'Median':>10s} {'Max':>10s} {'Stdev':>10s}"
    )
    print(line)
    for result in results:
        if result.error:
            print(f"  {result.layout:16s} {result.metric:30s} {'ERROR':>8s} {result.error}")
        else:
            print(
                f"  {result.layout:16s} {result.metric:30s} "
                f"{result.rows_returned:>8,d} "
                f"{result.avg_ms:>10.1f} {result.min_ms:>10.1f} "
                f"{result.median_ms:>10.1f} {result.max_ms:>10.1f} "
                f"{result.stdev_ms:>10.1f}"
            )
    print(line)
