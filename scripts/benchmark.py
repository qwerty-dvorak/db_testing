"""Real-time benchmark suite for four 1024-channel storage layouts.

Compares:
- JSONB array: sensor_payloads
- JSONB key-value object: sensor_payloads_json_object
- Native real[]: sensor_payloads_array
- Wide table: sensor_payloads_wide

All analytical work is done inside the timed query. There is no separate
precompute step.
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


@dataclass(frozen=True)
class BuildStep:
    """A timed setup step for an optimisation benchmark."""

    label: str
    sql: str
    params: tuple[Any, ...] = ()


@dataclass(frozen=True)
class OptimisationQuery:
    """A benchmark query plus any table/index build work it needs."""

    family: str
    variant: str
    sql: str
    params: tuple[Any, ...] = ()
    build_steps: tuple[BuildStep, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.family}: {self.variant}"


@dataclass
class OptimisationResult:
    """Timing results for one optimisation benchmark."""

    family: str
    variant: str
    sql: str
    params: tuple[Any, ...] = ()
    build_times_ms: list[tuple[str, float]] = field(default_factory=list)
    warmup_ms: list[float] = field(default_factory=list)
    times_ms: list[float] = field(default_factory=list)
    rows_returned: int = 0
    first_row: tuple[Any, ...] | None = None
    error: str | None = None

    @property
    def build_ms(self) -> float:
        return sum(elapsed for _, elapsed in self.build_times_ms)

    @property
    def table_build_ms(self) -> float:
        return sum(
            elapsed
            for label, elapsed in self.build_times_ms
            if label.startswith("build table")
        )

    @property
    def index_build_ms(self) -> float:
        return sum(
            elapsed
            for label, elapsed in self.build_times_ms
            if label.startswith("build index")
            or label.startswith("build expression index")
        )

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
    def total_query_ms(self) -> float:
        return sum(self.warmup_ms) + sum(self.times_ms)

    @property
    def total_including_build_ms(self) -> float:
        return self.build_ms + self.total_query_ms

    @property
    def count_value(self) -> int | None:
        if not self.first_row:
            return None
        value = self.first_row[0]
        return int(value) if isinstance(value, int) else None


def _wide_all_channel_minmax_sql(channels: int = CHANNEL_COUNT) -> str:
    values = ",\n        ".join(
        f"({i - 1}, ch{i:04d})"
        for i in range(1, channels + 1)
    )
    return f"""
    SELECT
        channel_idx,
        min(value) AS min_value,
        max(value) AS max_value
    FROM sensor_payloads_wide
    CROSS JOIN LATERAL (
        VALUES
        {values}
    ) AS v(channel_idx, value)
    GROUP BY channel_idx
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
            "real[]",
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
            "real[]",
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
            "real[]",
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
            "real[]",
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


def _channel_names(channel_index: int, channels: int = CHANNEL_COUNT) -> tuple[int, str]:
    if not 0 <= channel_index < channels:
        raise ValueError(f"channel_index must be between 0 and {channels - 1}")
    channel_ordinal = channel_index + 1
    return channel_ordinal, f"ch{channel_ordinal:04d}"


def _drop_optimisation_artifacts(
    conn: psycopg.Connection,
    channel_index: int = DEFAULT_CHANNEL_INDEX,
) -> None:
    """Remove benchmark-created objects so baselines are clean."""
    _, channel_key = _channel_names(channel_index)
    artifact_sql = [
        f"DROP TABLE IF EXISTS opt_channel_values_{channel_key} CASCADE",
        "DROP TABLE IF EXISTS opt_channel_values_all CASCADE",
        f"DROP INDEX IF EXISTS idx_bench_jsonb_array_{channel_key}",
        f"DROP INDEX IF EXISTS idx_bench_jsonb_object_{channel_key}",
        f"DROP INDEX IF EXISTS idx_bench_array_{channel_key}",
        f"DROP INDEX IF EXISTS idx_bench_wide_{channel_key}",
    ]
    for sql in artifact_sql:
        conn.execute(sql)
    conn.commit()


def build_optimisation_queries(
    channel_index: int = DEFAULT_CHANNEL_INDEX,
    threshold: float = DEFAULT_THRESHOLD,
    channels: int = CHANNEL_COUNT,
) -> list[OptimisationQuery]:
    """Build focused threshold benchmarks for documented optimisations."""
    channel_ordinal, channel_key = _channel_names(channel_index, channels)
    jsonb_array_threshold_sql = f"""
        SELECT count(*)
        FROM sensor_payloads
        WHERE ((payload ->> {channel_index})::float8) > %s
    """
    jsonb_object_threshold_sql = f"""
        SELECT count(*)
        FROM sensor_payloads_json_object
        WHERE ((payload ->> '{channel_key}')::float8) > %s
    """
    array_threshold_sql = f"""
        SELECT count(*)
        FROM sensor_payloads_array
        WHERE payload[{channel_ordinal}] > %s
    """
    wide_threshold_sql = f"""
        SELECT count(*)
        FROM sensor_payloads_wide
        WHERE {channel_key} > %s
    """

    return [
        OptimisationQuery(
            "JSONB array channel threshold",
            "baseline seq scan",
            jsonb_array_threshold_sql,
            (threshold,),
        ),
        OptimisationQuery(
            "JSONB object channel threshold",
            "baseline seq scan",
            jsonb_object_threshold_sql,
            (threshold,),
        ),
        OptimisationQuery(
            "real[] channel threshold",
            "baseline seq scan",
            array_threshold_sql,
            (threshold,),
        ),
        OptimisationQuery(
            "wide channel threshold",
            "baseline seq scan",
            wide_threshold_sql,
            (threshold,),
        ),
        OptimisationQuery(
            "JSONB array channel threshold",
            "expression index",
            jsonb_array_threshold_sql,
            (threshold,),
            (
                BuildStep(
                    "build expression index",
                    f"""
                    CREATE INDEX idx_bench_jsonb_array_{channel_key}
                    ON sensor_payloads (((payload ->> {channel_index})::float8))
                    """,
                ),
                BuildStep("analyze source table", "ANALYZE sensor_payloads"),
            ),
        ),
        OptimisationQuery(
            "JSONB object channel threshold",
            "expression index",
            jsonb_object_threshold_sql,
            (threshold,),
            (
                BuildStep(
                    "build expression index",
                    f"""
                    CREATE INDEX idx_bench_jsonb_object_{channel_key}
                    ON sensor_payloads_json_object
                        (((payload ->> '{channel_key}')::float8))
                    """,
                ),
                BuildStep(
                    "analyze source table",
                    "ANALYZE sensor_payloads_json_object",
                ),
            ),
        ),
        OptimisationQuery(
            "real[] channel threshold",
            "expression index",
            array_threshold_sql,
            (threshold,),
            (
                BuildStep(
                    "build expression index",
                    f"""
                    CREATE INDEX idx_bench_array_{channel_key}
                    ON sensor_payloads_array ((payload[{channel_ordinal}]))
                    """,
                ),
                BuildStep("analyze source table", "ANALYZE sensor_payloads_array"),
            ),
        ),
        OptimisationQuery(
            "wide channel threshold",
            "column index",
            wide_threshold_sql,
            (threshold,),
            (
                BuildStep(
                    "build index",
                    f"""
                    CREATE INDEX idx_bench_wide_{channel_key}
                    ON sensor_payloads_wide ({channel_key})
                    """,
                ),
                BuildStep("analyze source table", "ANALYZE sensor_payloads_wide"),
            ),
        ),
        OptimisationQuery(
            "real[] channel threshold",
            "derived hot-channel table + value index",
            f"""
            SELECT count(*)
            FROM opt_channel_values_{channel_key}
            WHERE value > %s
            """,
            (threshold,),
            (
                BuildStep(
                    "build table",
                    f"""
                    CREATE TABLE opt_channel_values_{channel_key} AS
                    SELECT
                        id AS reading_id,
                        created_at,
                        payload[{channel_ordinal}] AS value
                    FROM sensor_payloads_array
                    """,
                ),
                BuildStep(
                    "build index",
                    f"""
                    CREATE INDEX idx_opt_channel_values_{channel_key}_value
                    ON opt_channel_values_{channel_key} (value)
                    """,
                ),
                BuildStep(
                    "analyze derived table",
                    f"ANALYZE opt_channel_values_{channel_key}",
                ),
            ),
        ),
        OptimisationQuery(
            "real[] channel threshold",
            "derived all-channel table + channel/value index",
            """
            SELECT count(*)
            FROM opt_channel_values_all
            WHERE channel_idx = %s
              AND value > %s
            """,
            (channel_index, threshold),
            (
                BuildStep(
                    "build table",
                    """
                    CREATE TABLE opt_channel_values_all AS
                    SELECT
                        id AS reading_id,
                        created_at,
                        ord::int - 1 AS channel_idx,
                        value::real AS value
                    FROM sensor_payloads_array
                    CROSS JOIN LATERAL unnest(payload)
                        WITH ORDINALITY AS u(value, ord)
                    """,
                ),
                BuildStep(
                    "build index",
                    """
                    CREATE INDEX idx_opt_channel_values_all_channel_value
                    ON opt_channel_values_all (channel_idx, value)
                    """,
                ),
                BuildStep(
                    "analyze derived table",
                    "ANALYZE opt_channel_values_all",
                ),
            ),
        ),
        OptimisationQuery(
            "JSONB array all-channel threshold",
            "jsonb_array_elements_text",
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
        OptimisationQuery(
            "JSONB array all-channel threshold",
            "jsonb_array_elements",
            """
            SELECT
                ord::int - 1 AS channel_idx,
                count(*) FILTER (WHERE value::text::float8 > %s)
                    AS count_above_threshold
            FROM sensor_payloads
            CROSS JOIN LATERAL jsonb_array_elements(payload)
                WITH ORDINALITY AS e(value, ord)
            GROUP BY ord
            ORDER BY ord
            """,
            (threshold,),
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


def _execute_build_step(
    conn: psycopg.Connection,
    step: BuildStep,
) -> float:
    t0 = time.perf_counter()
    conn.execute(step.sql, step.params)
    conn.commit()
    return (time.perf_counter() - t0) * 1000


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
            conn.rollback()
            return result

    for _ in range(iterations):
        try:
            elapsed_ms, rows = _execute_fetch(conn, query.sql, query.params)
            result.times_ms.append(elapsed_ms)
            result.rows_returned = len(rows)
            result.first_row = rows[0] if rows else None
        except Exception as e:
            result.error = str(e)
            conn.rollback()
            return result

    return result


def run_optimisation_benchmark(
    conn: psycopg.Connection,
    query: OptimisationQuery,
    iterations: int = 5,
    warmup: int = 2,
) -> OptimisationResult:
    """Run one optimisation query, including timed build steps."""
    result = OptimisationResult(
        family=query.family,
        variant=query.variant,
        sql=query.sql.strip(),
        params=query.params,
    )

    for step in query.build_steps:
        try:
            elapsed_ms = _execute_build_step(conn, step)
            result.build_times_ms.append((step.label, elapsed_ms))
        except Exception as e:
            result.error = f"{step.label}: {e}"
            conn.rollback()
            return result

    for _ in range(warmup):
        try:
            elapsed_ms, rows = _execute_fetch(conn, query.sql, query.params)
            result.warmup_ms.append(elapsed_ms)
            result.rows_returned = len(rows)
            result.first_row = rows[0] if rows else None
        except Exception as e:
            result.error = str(e)
            conn.rollback()
            return result

    for _ in range(iterations):
        try:
            elapsed_ms, rows = _execute_fetch(conn, query.sql, query.params)
            result.times_ms.append(elapsed_ms)
            result.rows_returned = len(rows)
            result.first_row = rows[0] if rows else None
        except Exception as e:
            result.error = str(e)
            conn.rollback()
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


def run_optimisation_benchmarks(
    conn: psycopg.Connection,
    iterations: int = 5,
    warmup: int = 2,
    channel_index: int = DEFAULT_CHANNEL_INDEX,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[OptimisationResult]:
    """Run focused optimisation comparisons with setup cost included."""
    print("Cleaning benchmark-created optimisation artifacts ...")
    _drop_optimisation_artifacts(conn, channel_index)

    queries = build_optimisation_queries(
        channel_index=channel_index,
        threshold=threshold,
    )
    results: list[OptimisationResult] = []
    n = len(queries)

    print(
        f"Running {n} optimisation benchmarks x {iterations} timed iterations "
        f"(warmup={warmup}, channel={channel_index + 1}, "
        f"threshold={threshold:g}) ...\n"
    )

    suite_t0 = time.perf_counter()
    for i, query in enumerate(queries, 1):
        print(f"  [{i}/{n}] {query.label}")
        result = run_optimisation_benchmark(conn, query, iterations, warmup)
        results.append(result)
        if result.error:
            print(f"      ERROR: {result.error}")
            continue

        if result.build_times_ms:
            for label, elapsed_ms in result.build_times_ms:
                print(f"      {label:<24s} {elapsed_ms:>10.1f} ms")
        else:
            print("      build steps:          none")

        warmup_text = ", ".join(f"{t:.1f}" for t in result.warmup_ms) or "none"
        run_text = ", ".join(f"{t:.1f}" for t in result.times_ms)
        count_text = (
            f"{result.count_value:,}"
            if result.count_value is not None and result.rows_returned == 1
            else "n/a"
        )
        print(f"      rows returned:        {result.rows_returned:,}")
        print(f"      count result:         {count_text}")
        print(f"      warmup ms:            {warmup_text}")
        print(f"      timed ms:             {run_text}")
        print(
            "      summary ms:           "
            f"build={result.build_ms:.1f} query_avg={result.avg_ms:.1f} "
            f"query_min={result.min_ms:.1f} query_median={result.median_ms:.1f} "
            f"query_max={result.max_ms:.1f} "
            f"total_including_build={result.total_including_build_ms:.1f}"
        )

    suite_ms = (time.perf_counter() - suite_t0) * 1000
    print(f"\nOptimisation benchmark suite wall time: {suite_ms:.1f} ms")
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


def print_optimisation_results(results: list[OptimisationResult]) -> None:
    """Print a summary of optimisation benchmark results."""
    baseline_by_family: dict[str, OptimisationResult] = {}
    for result in results:
        if result.error:
            continue
        baseline_by_family.setdefault(result.family, result)

    line = "-" * 150
    print(f"\n{line}")
    print(
        f"  {'Family':36s} {'Variant':36s} {'Count':>10s} "
        f"{'Build':>10s} {'Table':>10s} {'Index':>10s} "
        f"{'Avg Query':>10s} {'Total+Build':>12s} {'Speedup':>9s}"
    )
    print(line)
    for result in results:
        if result.error:
            print(
                f"  {result.family:36s} {result.variant:36s} "
                f"{'ERROR':>10s} {result.error}"
            )
            continue

        baseline = baseline_by_family.get(result.family)
        if baseline and result.avg_ms > 0:
            speedup = baseline.avg_ms / result.avg_ms
            speedup_text = f"{speedup:.2f}x"
        else:
            speedup_text = "n/a"
        count_text = (
            f"{result.count_value:,}"
            if result.count_value is not None and result.rows_returned == 1
            else "n/a"
        )
        print(
            f"  {result.family:36s} {result.variant:36s} "
            f"{count_text:>10s} "
            f"{result.build_ms:>10.1f} {result.table_build_ms:>10.1f} "
            f"{result.index_build_ms:>10.1f} {result.avg_ms:>10.1f} "
            f"{result.total_including_build_ms:>12.1f} {speedup_text:>9s}"
        )
    print(line)
