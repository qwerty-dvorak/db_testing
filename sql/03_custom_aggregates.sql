-- ============================================================================
-- 03_custom_aggregates.sql
-- High-performance custom aggregate functions for JSONB array analytics
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Helper: extract all floats from a JSONB array into a double-precision column
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION jsonb_array_to_float8(j JSONB)
RETURNS TABLE(value FLOAT8)
AS $$
    SELECT (jsonb_array_elements_text(j)::FLOAT8)
$$ LANGUAGE SQL IMMUTABLE PARALLEL SAFE
RETURN NULL ON NULL INPUT;

-- ---------------------------------------------------------------------------
-- Custom state functions
-- ---------------------------------------------------------------------------

-- Minimum: retain only the smallest value seen so far
CREATE OR REPLACE FUNCTION float_min_state(state FLOAT8, incoming FLOAT8)
RETURNS FLOAT8 AS $$
BEGIN
    IF state IS NULL THEN
        RETURN incoming;
    ELSIF incoming < state THEN
        RETURN incoming;
    ELSE
        RETURN state;
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

-- Maximum: retain only the largest value seen so far
CREATE OR REPLACE FUNCTION float_max_state(state FLOAT8, incoming FLOAT8)
RETURNS FLOAT8 AS $$
BEGIN
    IF state IS NULL THEN
        RETURN incoming;
    ELSIF incoming > state THEN
        RETURN incoming;
    ELSE
        RETURN state;
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

-- Running sum (used by average)
CREATE OR REPLACE FUNCTION float_sum_state(state FLOAT8, incoming FLOAT8)
RETURNS FLOAT8 AS $$
BEGIN
    IF state IS NULL THEN
        RETURN incoming;
    ELSE
        RETURN state + incoming;
    END IF;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

-- Running count (used by average)
CREATE OR REPLACE FUNCTION float_count_state(state INT, incoming FLOAT8)
RETURNS INT AS $$
BEGIN
    RETURN COALESCE(state, 0) + 1;
END;
$$ LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE;

-- ---------------------------------------------------------------------------
-- Custom aggregates
-- ---------------------------------------------------------------------------

CREATE AGGREGATE array_global_min(FLOAT8) (
    sfunc     = float_min_state,
    stype     = FLOAT8,
    PARALLEL  = SAFE,
    COMBINEFUNC = float_min_state
);

CREATE AGGREGATE array_global_max(FLOAT8) (
    sfunc     = float_max_state,
    stype     = FLOAT8,
    PARALLEL  = SAFE,
    COMBINEFUNC = float_max_state
);

CREATE AGGREGATE array_global_sum(FLOAT8) (
    sfunc     = float_sum_state,
    stype     = FLOAT8,
    PARALLEL  = SAFE,
    COMBINEFUNC = float_sum_state
);

CREATE AGGREGATE array_global_count(FLOAT8) (
    sfunc     = float_count_state,
    stype     = INT,
    PARALLEL  = SAFE,
    COMBINEFUNC = float_count_state
);

-- ---------------------------------------------------------------------------
-- Convenience aggregate: average of all values in a JSONB array column
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION jsonb_array_avg(j JSONB)
RETURNS FLOAT8 AS $$
    SELECT avg(v) FROM jsonb_array_to_float8(j)
$$ LANGUAGE SQL IMMUTABLE PARALLEL SAFE
RETURN NULL ON NULL INPUT;

-- ---------------------------------------------------------------------------
-- Extract a single channel across all rows (useful for time-series queries)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION extract_channel(j JSONB, idx INT)
RETURNS FLOAT8 AS $$
    SELECT (j->>idx)::FLOAT8
$$ LANGUAGE SQL IMMUTABLE PARALLEL SAFE
RETURN NULL ON NULL INPUT;

-- ---------------------------------------------------------------------------
-- Verify aggregates work
-- ---------------------------------------------------------------------------
/*
-- Test queries:

-- Global min/max across all payloads
SELECT
    array_global_min(v),
    array_global_max(v),
    array_global_sum(v),
    array_global_count(v)
FROM sensor_payloads,
LATERAL jsonb_array_to_float8(payload) AS v;

-- Average of a specific channel (e.g. channel 512)
SELECT
    extract_channel(payload, 511)::TEXT   -- 0-indexed: channel 512
FROM sensor_payloads
LIMIT 5;

-- Min, max, avg of channel 0 across first 100 rows
SELECT
    min(extract_channel(payload, 0)),
    max(extract_channel(payload, 0)),
    avg(extract_channel(payload, 0))
FROM sensor_payloads;
*/
