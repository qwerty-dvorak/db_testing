-- ============================================================================
-- 02_generate_sample_pg16.sql
-- PostgreSQL 16-compatible sample data generator
--
-- Generates N sensor payloads with 1024-channel arrays.
-- Compatible with PG 16 and PG 18.
-- ============================================================================

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
FROM generate_series(1, 10) AS s(idx)
CROSS JOIN generate_series(1, 1024) AS i
GROUP BY s.idx;
