-- ============================================================================
-- 06_channel_analytics.sql
-- Exact Postgres-only analytics layer for 1024-channel telemetry.
--
-- Design:
--   1. Keep raw readings in a typed float8[] table for rebuild/audit.
--   2. Store per-time-bucket min/max/sum/count per channel.
--   3. Store sorted value blocks per bucket/channel for exact ad-hoc
--      threshold counts without scanning all raw values.
-- ============================================================================

SET jit = off;

CREATE TABLE IF NOT EXISTS sensor_readings_raw (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload    float8[] NOT NULL CHECK (array_length(payload, 1) = 1024),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_raw_created_at_brin
    ON sensor_readings_raw USING BRIN (created_at);

CREATE TABLE IF NOT EXISTS channel_bucket_stats (
    bucket_start timestamptz NOT NULL,
    channel_idx  int2 NOT NULL CHECK (channel_idx BETWEEN 0 AND 1023),
    n            bigint NOT NULL,
    min_value    float8 NOT NULL,
    max_value    float8 NOT NULL,
    sum_value    float8 NOT NULL,
    PRIMARY KEY (bucket_start, channel_idx)
);

CREATE INDEX IF NOT EXISTS idx_channel_bucket_stats_channel_bucket
    ON channel_bucket_stats (channel_idx, bucket_start);

CREATE TABLE IF NOT EXISTS channel_value_blocks (
    bucket_start timestamptz NOT NULL,
    channel_idx  int2 NOT NULL CHECK (channel_idx BETWEEN 0 AND 1023),
    block_no     int NOT NULL,
    value_min    float8 NOT NULL,
    value_max    float8 NOT NULL,
    n            int NOT NULL,
    sorted_values float8[] NOT NULL,
    PRIMARY KEY (bucket_start, channel_idx, block_no)
);

CREATE INDEX IF NOT EXISTS idx_channel_value_blocks_bucket_channel_max
    ON channel_value_blocks (bucket_start, channel_idx, value_max);

CREATE INDEX IF NOT EXISTS idx_channel_value_blocks_bucket_channel_min
    ON channel_value_blocks (bucket_start, channel_idx, value_min);

COMMENT ON TABLE sensor_readings_raw IS
    'Typed raw 1024-channel readings used as the rebuild source for analytics summaries';
COMMENT ON TABLE channel_bucket_stats IS
    'Per-time-bucket per-channel exact count, min, max, and sum';
COMMENT ON TABLE channel_value_blocks IS
    'Sorted value blocks for exact ad-hoc threshold counts by channel and time bucket';

-- Return count of array entries <= threshold. Arrays must be sorted ascending.
CREATE OR REPLACE FUNCTION float8_count_le(sorted_values float8[], threshold float8)
RETURNS int
LANGUAGE plpgsql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
DECLARE
    lo int := 1;
    hi int := COALESCE(array_length(sorted_values, 1), 0) + 1;
    mid int;
BEGIN
    WHILE lo < hi LOOP
        mid := (lo + hi) / 2;
        IF sorted_values[mid] <= threshold THEN
            lo := mid + 1;
        ELSE
            hi := mid;
        END IF;
    END LOOP;

    RETURN lo - 1;
END;
$$;

-- Convert the existing JSONB-array baseline table into typed raw readings.
CREATE OR REPLACE FUNCTION load_sensor_readings_raw_from_jsonb(clear_existing boolean DEFAULT true)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    inserted_count bigint;
BEGIN
    IF clear_existing THEN
        TRUNCATE sensor_readings_raw;
    END IF;

    INSERT INTO sensor_readings_raw (id, payload, created_at)
    SELECT
        id,
        array_agg(value::float8 ORDER BY ord),
        created_at
    FROM sensor_payloads
    CROSS JOIN LATERAL jsonb_array_elements_text(payload) WITH ORDINALITY AS e(value, ord)
    WHERE ord <= 1024
    GROUP BY id, created_at
    ON CONFLICT (id) DO UPDATE
        SET payload = EXCLUDED.payload,
            created_at = EXCLUDED.created_at;

    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    ANALYZE sensor_readings_raw;
    RETURN inserted_count;
END;
$$;

-- Rebuild all exact summaries from sensor_readings_raw.
CREATE OR REPLACE FUNCTION rebuild_channel_analytics(
    bucket_size interval DEFAULT interval '1 hour',
    block_size int DEFAULT 4096
)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF block_size < 2 THEN
        RAISE EXCEPTION 'block_size must be >= 2';
    END IF;

    TRUNCATE channel_bucket_stats, channel_value_blocks;

    INSERT INTO channel_bucket_stats (
        bucket_start,
        channel_idx,
        n,
        min_value,
        max_value,
        sum_value
    )
    SELECT
        date_bin(bucket_size, created_at, '2000-01-01 00:00:00+00'::timestamptz),
        ord::int - 1,
        count(*),
        min(value),
        max(value),
        sum(value)
    FROM sensor_readings_raw
    CROSS JOIN LATERAL unnest(payload) WITH ORDINALITY AS u(value, ord)
    GROUP BY 1, 2;

    INSERT INTO channel_value_blocks (
        bucket_start,
        channel_idx,
        block_no,
        value_min,
        value_max,
        n,
        sorted_values
    )
    WITH exploded AS (
        SELECT
            date_bin(bucket_size, created_at, '2000-01-01 00:00:00+00'::timestamptz) AS bucket_start,
            ord::int - 1 AS channel_idx,
            value
        FROM sensor_readings_raw
        CROSS JOIN LATERAL unnest(payload) WITH ORDINALITY AS u(value, ord)
    ),
    ranked AS (
        SELECT
            bucket_start,
            channel_idx,
            value,
            row_number() OVER (
                PARTITION BY bucket_start, channel_idx
                ORDER BY value
            ) AS rn
        FROM exploded
    ),
    blocked AS (
        SELECT
            bucket_start,
            channel_idx,
            ((rn - 1) / block_size)::int AS block_no,
            value
        FROM ranked
    )
    SELECT
        bucket_start,
        channel_idx,
        block_no,
        min(value),
        max(value),
        count(*)::int,
        array_agg(value ORDER BY value)
    FROM blocked
    GROUP BY bucket_start, channel_idx, block_no;

    ANALYZE channel_bucket_stats;
    ANALYZE channel_value_blocks;
END;
$$;

-- Exact min/max for arbitrary time ranges. Full buckets come from summaries;
-- partial boundary fragments fall back to raw readings.
CREATE OR REPLACE FUNCTION channel_minmax_exact(
    start_at timestamptz,
    end_at timestamptz,
    bucket_size interval DEFAULT interval '1 hour'
)
RETURNS TABLE (
    channel_idx int,
    min_value float8,
    max_value float8,
    rows_seen bigint
)
LANGUAGE SQL
STABLE
PARALLEL SAFE
AS $$
WITH bounds AS (
    SELECT
        CASE
            WHEN date_bin(bucket_size, start_at, '2000-01-01 00:00:00+00'::timestamptz) = start_at
                THEN start_at
            ELSE date_bin(bucket_size, start_at, '2000-01-01 00:00:00+00'::timestamptz) + bucket_size
        END AS first_full_bucket,
        date_bin(bucket_size, end_at, '2000-01-01 00:00:00+00'::timestamptz) AS end_full_bucket
),
summary_values AS (
    SELECT
        s.channel_idx::int,
        s.n AS rows_seen,
        s.min_value,
        s.max_value
    FROM channel_bucket_stats s
    CROSS JOIN bounds b
    WHERE s.bucket_start >= b.first_full_bucket
      AND s.bucket_start < b.end_full_bucket
),
partial_values AS (
    SELECT
        ord::int - 1 AS channel_idx,
        count(*) AS rows_seen,
        min(value) AS min_value,
        max(value) AS max_value
    FROM sensor_readings_raw r
    CROSS JOIN bounds b
    CROSS JOIN LATERAL unnest(r.payload) WITH ORDINALITY AS u(value, ord)
    WHERE r.created_at >= start_at
      AND r.created_at < end_at
      AND NOT (
          r.created_at >= b.first_full_bucket
          AND r.created_at < b.end_full_bucket
      )
    GROUP BY ord
)
SELECT
    combined.channel_idx,
    min(combined.min_value) AS min_value,
    max(combined.max_value) AS max_value,
    sum(combined.rows_seen)::bigint AS rows_seen
FROM (
    SELECT * FROM summary_values
    UNION ALL
    SELECT * FROM partial_values
) AS combined
GROUP BY combined.channel_idx
ORDER BY combined.channel_idx;
$$;

-- Exact count of values strictly greater than threshold for arbitrary time
-- ranges. Full buckets use sorted blocks; boundary fragments scan raw arrays.
CREATE OR REPLACE FUNCTION channel_threshold_counts_exact(
    start_at timestamptz,
    end_at timestamptz,
    threshold float8,
    bucket_size interval DEFAULT interval '1 hour'
)
RETURNS TABLE (
    channel_idx int,
    rows_above bigint
)
LANGUAGE SQL
STABLE
PARALLEL SAFE
AS $$
WITH bounds AS (
    SELECT
        CASE
            WHEN date_bin(bucket_size, start_at, '2000-01-01 00:00:00+00'::timestamptz) = start_at
                THEN start_at
            ELSE date_bin(bucket_size, start_at, '2000-01-01 00:00:00+00'::timestamptz) + bucket_size
        END AS first_full_bucket,
        date_bin(bucket_size, end_at, '2000-01-01 00:00:00+00'::timestamptz) AS end_full_bucket
),
block_counts AS (
    SELECT
        b.channel_idx::int,
        sum(
            CASE
                WHEN threshold < b.value_min THEN b.n
                WHEN threshold >= b.value_max THEN 0
                ELSE b.n - float8_count_le(b.sorted_values, threshold)
            END
        )::bigint AS rows_above
    FROM channel_value_blocks b
    CROSS JOIN bounds x
    WHERE b.bucket_start >= x.first_full_bucket
      AND b.bucket_start < x.end_full_bucket
      AND b.value_max > threshold
    GROUP BY b.channel_idx
),
partial_counts AS (
    SELECT
        ord::int - 1 AS channel_idx,
        count(*) FILTER (WHERE value > threshold)::bigint AS rows_above
    FROM sensor_readings_raw r
    CROSS JOIN bounds b
    CROSS JOIN LATERAL unnest(r.payload) WITH ORDINALITY AS u(value, ord)
    WHERE r.created_at >= start_at
      AND r.created_at < end_at
      AND NOT (
          r.created_at >= b.first_full_bucket
          AND r.created_at < b.end_full_bucket
      )
    GROUP BY ord
)
SELECT
    channels.channel_idx,
    COALESCE(sum(combined.rows_above), 0)::bigint AS rows_above
FROM generate_series(0, 1023) AS channels(channel_idx)
LEFT JOIN (
    SELECT * FROM block_counts
    UNION ALL
    SELECT * FROM partial_counts
) AS combined USING (channel_idx)
GROUP BY channels.channel_idx
ORDER BY channels.channel_idx;
$$;

-- Small status view for CLI/reporting.
CREATE OR REPLACE VIEW channel_analytics_status AS
SELECT
    (SELECT count(*) FROM sensor_readings_raw) AS raw_rows,
    (SELECT count(*) FROM channel_bucket_stats) AS bucket_stat_rows,
    (SELECT count(*) FROM channel_value_blocks) AS value_block_rows,
    pg_size_pretty(pg_total_relation_size('sensor_readings_raw')) AS raw_size,
    pg_size_pretty(pg_total_relation_size('channel_bucket_stats')) AS bucket_stats_size,
    pg_size_pretty(pg_total_relation_size('channel_value_blocks')) AS value_blocks_size;
