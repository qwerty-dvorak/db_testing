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

import psycopg

INSERT_SAMPLE_SQL = """
INSERT INTO sensor_payloads (payload)
SELECT jsonb_agg(
    (round(
        (random() * 100.0
         + sin(i * 0.01 + s.idx * 0.001) * 5.0
         + random() * 2.0 - 1.0
        )::numeric,
        6
    ))::float8
    ORDER BY i
) AS payload
FROM generate_series(1, %(n_rows)s) AS s(idx)
CROSS JOIN generate_series(1, %(channels)s) AS i
GROUP BY s.idx
"""


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
    inserted = 0
    remaining = n_rows

    while remaining > 0:
        batch = min(batch_size, remaining)
        conn.execute(INSERT_SAMPLE_SQL, {"n_rows": batch, "channels": channels})
        inserted += batch
        remaining -= batch
        if verbose:
            print(f"\r  Inserted {inserted} / {n_rows} rows ...", end="", flush=True)

    conn.commit()
    if verbose:
        print(f"\r  Inserted {inserted} / {n_rows} rows  [done]")
    return inserted


def generate_bulk(
    conn: psycopg.Connection,
    n_rows: int = 1_000_000,
    channels: int = 1024,
    verbose: bool = True,
) -> int:
    """High-volume data generation using a single bulk INSERT.

    WARNING: Generating 1M rows with 1024 channels each will produce
    ~1.024B float values. This takes minutes and consumes gigabytes
    of disk space.
    """
    if verbose:
        print(f"Generating {n_rows:,} sensor payloads ({channels} channels each) ...")
        print("  This may take a long time ...")

    conn.execute(INSERT_SAMPLE_SQL, {"n_rows": min(n_rows, 1000), "channels": channels})
    conn.commit()

    if n_rows > 1000:
        # Repeat the insert to reach the desired count
        batches = n_rows // 1000
        for i in range(1, batches):
            conn.execute(INSERT_SAMPLE_SQL, {"n_rows": 1000, "channels": channels})
            conn.commit()
            if verbose:
                print(f"\r  Inserted {(i + 1) * 1000:,} / {n_rows:,} rows ...",
                      end="", flush=True)

        remainder = n_rows % 1000
        if remainder:
            conn.execute(INSERT_SAMPLE_SQL, {"n_rows": remainder, "channels": channels})
            conn.commit()

    if verbose:
        print(f"\r  Inserted {n_rows:,} rows  [done]")
    return n_rows
