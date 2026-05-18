-- ============================================================================
-- 02_generate_sample.sql
-- Generates sample 1028-channel sensor payloads for testing
-- ============================================================================

-- Generate 100 rows of sample data with realistic-looking float arrays
INSERT INTO sensor_payloads (payload)
SELECT
    jsonb_agg(
        round(
            (random() * 100.0)::numeric  -- baseline 0-100
            + (sin(i * 0.01 + s.idx * 0.001) * 5.0)  -- sinusoidal drift
            + (random() * 2.0 - 1.0),    -- white noise ±1
            6
        )::float8
        ORDER BY i
    ) AS payload
FROM generate_series(1, 10) AS s(idx)
CROSS JOIN generate_series(1, 1028) AS i
GROUP BY s.idx;
