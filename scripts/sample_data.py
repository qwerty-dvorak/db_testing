"""Sample sensor data generation.

Generates synthetic 1024-channel sensor payloads with:
- Random baseline (0-100)
- Sinusoidal drift across channels and rows
- White noise (±1)

Usage:
    from scripts.connection import get_conn
    from scripts.sample_data import generate_samples

    conn = get_conn()
    generate_samples(conn, n_rows=100)
"""

from __future__ import annotations

import time

import psycopg

CHANNEL_COUNT = 1024

CREATE_TEMP_SEED_SQL = """
CREATE TEMP TABLE IF NOT EXISTS sensor_seed_values (
    reading_id  UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    row_idx     INT NOT NULL,
    channel_idx INT NOT NULL,
    value       FLOAT8 NOT NULL
) ON COMMIT PRESERVE ROWS
"""

TRUNCATE_TEMP_SEED_SQL = "TRUNCATE sensor_seed_values"

INSERT_TEMP_SEED_SQL = """
WITH readings AS (
    SELECT
        idx AS row_idx,
        gen_random_uuid() AS reading_id,
        clock_timestamp() AS created_at
    FROM generate_series(1, %(n_rows)s) AS s(idx)
)
INSERT INTO sensor_seed_values (reading_id, created_at, row_idx, channel_idx, value)
SELECT
    r.reading_id,
    r.created_at,
    r.row_idx,
    ch.channel_idx,
    (
        round(
            (
                random() * 100.0
                + sin((ch.channel_idx + 1) * 0.01 + r.row_idx * 0.001) * 5.0
                + random() * 2.0 - 1.0
            )::numeric,
            6
        )
    )::float8 AS value
FROM readings AS r
CROSS JOIN generate_series(0, %(channels)s - 1) AS ch(channel_idx)
"""

INSERT_JSONB_ARRAY_SQL = """
INSERT INTO sensor_payloads (id, payload, created_at)
SELECT
    reading_id,
    jsonb_agg(value ORDER BY channel_idx) AS payload,
    created_at
FROM sensor_seed_values
GROUP BY reading_id, created_at
"""

INSERT_JSONB_OBJECT_SQL = """
INSERT INTO sensor_payloads_json_object (id, payload, created_at)
SELECT
    reading_id,
    jsonb_object_agg(
        'ch' || lpad((channel_idx + 1)::text, 4, '0'),
        value
        ORDER BY channel_idx
    ) AS payload,
    created_at
FROM sensor_seed_values
GROUP BY reading_id, created_at
"""

INSERT_ARRAY_SQL = """
INSERT INTO sensor_payloads_array (id, payload, created_at)
SELECT
    reading_id,
    array_agg(value ORDER BY channel_idx) AS payload,
    created_at
FROM sensor_seed_values
GROUP BY reading_id, created_at
"""


def _wide_insert_sql(channels: int = CHANNEL_COUNT) -> str:
    names = ", ".join(f"ch{i:04d}" for i in range(1, channels + 1))
    values = ",\n    ".join(
        f"max(value) FILTER (WHERE channel_idx = {i - 1}) AS ch{i:04d}"
        for i in range(1, channels + 1)
    )
    return f"""
INSERT INTO sensor_payloads_wide (id, created_at, {names})
SELECT
    reading_id,
    created_at,
    {values}
FROM sensor_seed_values
GROUP BY reading_id, created_at
"""


def _wide_sync_sql(channels: int = CHANNEL_COUNT) -> str:
    names = ", ".join(f"ch{i:04d}" for i in range(1, channels + 1))
    values = ", ".join(
        f"(src.payload->>{i - 1})::float8 AS ch{i:04d}"
        for i in range(1, channels + 1)
    )
    return f"""
INSERT INTO sensor_payloads_wide (id, created_at, {names})
SELECT src.id, src.created_at, {values}
FROM sensor_payloads AS src
WHERE NOT EXISTS (
    SELECT 1 FROM sensor_payloads_wide AS dst WHERE dst.id = src.id
)
"""


SYNC_JSONB_OBJECT_SQL = """
INSERT INTO sensor_payloads_json_object (id, payload, created_at)
SELECT
    src.id,
    jsonb_object_agg(
        'ch' || lpad(ord::text, 4, '0'),
        value
        ORDER BY ord
    ) AS payload,
    src.created_at
FROM sensor_payloads AS src
CROSS JOIN LATERAL jsonb_array_elements(src.payload) WITH ORDINALITY AS e(value, ord)
WHERE NOT EXISTS (
    SELECT 1 FROM sensor_payloads_json_object AS dst WHERE dst.id = src.id
)
GROUP BY src.id, src.created_at
"""

SYNC_ARRAY_SQL = """
INSERT INTO sensor_payloads_array (id, payload, created_at)
SELECT
    src.id,
    array_agg(value::float8 ORDER BY ord) AS payload,
    src.created_at
FROM sensor_payloads AS src
CROSS JOIN LATERAL jsonb_array_elements_text(src.payload)
    WITH ORDINALITY AS e(value, ord)
WHERE NOT EXISTS (
    SELECT 1 FROM sensor_payloads_array AS dst WHERE dst.id = src.id
)
GROUP BY src.id, src.created_at
"""


def _require_supported_channels(channels: int) -> None:
    if channels != CHANNEL_COUNT:
        raise ValueError(
            f"the four-layout schema is fixed at {CHANNEL_COUNT} channels; "
            f"got {channels}"
        )


def _timed_execute(
    conn: psycopg.Connection,
    label: str,
    sql: str,
    params: dict[str, int] | None = None,
    verbose: bool = True,
) -> float:
    t0 = time.perf_counter()
    conn.execute(sql, params or {})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if verbose:
        print(f"    {label:<32s} {elapsed_ms:>10.1f} ms")
    return elapsed_ms


def _insert_batch(
    conn: psycopg.Connection,
    batch: int,
    channels: int,
    verbose: bool,
) -> None:
    _timed_execute(conn, "prepare temp seed table", CREATE_TEMP_SEED_SQL, verbose=verbose)
    _timed_execute(conn, "clear temp seed table", TRUNCATE_TEMP_SEED_SQL, verbose=verbose)
    _timed_execute(
        conn,
        f"generate {batch:,} x {channels:,} values",
        INSERT_TEMP_SEED_SQL,
        {"n_rows": batch, "channels": channels},
        verbose,
    )
    _timed_execute(conn, "insert JSONB array rows", INSERT_JSONB_ARRAY_SQL, verbose=verbose)
    _timed_execute(
        conn,
        "insert JSONB key-value rows",
        INSERT_JSONB_OBJECT_SQL,
        verbose=verbose,
    )
    _timed_execute(conn, "insert float8[] rows", INSERT_ARRAY_SQL, verbose=verbose)
    _timed_execute(conn, "insert wide rows", _wide_insert_sql(channels), verbose=verbose)


def sync_layouts_from_jsonb(
    conn: psycopg.Connection,
    channels: int = CHANNEL_COUNT,
    verbose: bool = True,
) -> None:
    """Backfill missing non-array layouts from existing JSONB-array rows."""
    _require_supported_channels(channels)
    if verbose:
        print("[sync] Backfilling missing layout rows from sensor_payloads ...")
    _timed_execute(
        conn,
        "sync JSONB key-value rows",
        SYNC_JSONB_OBJECT_SQL,
        verbose=verbose,
    )
    _timed_execute(conn, "sync float8[] rows", SYNC_ARRAY_SQL, verbose=verbose)
    _timed_execute(conn, "sync wide rows", _wide_sync_sql(channels), verbose=verbose)
    t0 = time.perf_counter()
    conn.commit()
    commit_ms = (time.perf_counter() - t0) * 1000
    if verbose:
        print(f"    sync commit{'':<21s} {commit_ms:>10.1f} ms")


def generate_samples(
    conn: psycopg.Connection,
    n_rows: int = 100,
    channels: int = 1024,
    batch_size: int = 100,
    verbose: bool = True,
) -> int:
    """Insert synthetic sensor payloads.

    Args:
        conn: Active psycopg connection.
        n_rows: Number of sensor payloads to insert.
        channels: Number of channels per payload.
        batch_size: Rows per INSERT statement (default 100).
        verbose: Print progress.

    Returns:
        Total rows inserted.
    """
    _require_supported_channels(channels)
    inserted = 0
    remaining = n_rows

    while remaining > 0:
        batch = min(batch_size, remaining)
        if verbose:
            print(f"  Batch {inserted + 1:,}-{inserted + batch:,}:")
        _insert_batch(conn, batch, channels, verbose)
        inserted += batch
        remaining -= batch
        if verbose:
            print(f"\r  Inserted {inserted} / {n_rows} rows ...", end="", flush=True)

    t0 = time.perf_counter()
    conn.commit()
    commit_ms = (time.perf_counter() - t0) * 1000
    if verbose:
        print(f"\n  Commit{'':<27s} {commit_ms:>10.1f} ms")
        print(f"\r  Inserted {inserted} / {n_rows} rows  [done]")
    return inserted


def generate_bulk(
    conn: psycopg.Connection,
    n_rows: int = 1_000_000,
    channels: int = 1024,
    batch_size: int = 10_000,
    verbose: bool = True,
) -> int:
    """High-volume data generation using large server-side INSERT batches.

    WARNING: Generating 1M rows with 1024 channels each will produce
    ~1.024B float values. This takes minutes and consumes gigabytes
    of disk space.
    """
    _require_supported_channels(channels)
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    if verbose:
        print(f"Generating {n_rows:,} sensor payloads ({channels} channels each) ...")
        print(f"  Bulk batch size: {batch_size:,} rows")

    inserted = 0
    remaining = n_rows

    while remaining > 0:
        batch = min(batch_size, remaining)
        if verbose:
            print(f"  Batch {inserted + 1:,}-{inserted + batch:,}:")
        _insert_batch(conn, batch, channels, verbose)
        inserted += batch
        remaining -= batch
        if verbose:
            print(
                f"\r  Inserted {inserted:,} / {n_rows:,} rows ...",
                end="",
                flush=True,
            )

    t0 = time.perf_counter()
    conn.commit()
    commit_ms = (time.perf_counter() - t0) * 1000

    if verbose:
        print(f"\n  Commit{'':<27s} {commit_ms:>10.1f} ms")
        print(f"\r  Inserted {n_rows:,} rows  [done]")
    return n_rows
