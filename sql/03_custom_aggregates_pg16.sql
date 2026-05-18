-- ============================================================================
-- 03_custom_aggregates_pg16.sql
-- PostgreSQL 16-compatible custom aggregate functions
--
-- All features used here (PARALLEL SAFE, COMBINEFUNC, IMMUTABLE,
-- SQL/PLPGSQL functions) are available since PG 9.6+.
-- ============================================================================

-- -------------------------------------------------------------------------
-- Helper: extract all floats from a JSONB array into a FLOAT8 column
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION jsonb_array_to_float8(j JSONB)
RETURNS TABLE(value FLOAT8)
LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $$ SELECT (jsonb_array_elements_text(j)::FLOAT8) $$;

-- -------------------------------------------------------------------------
-- State transition functions (constant memory per worker)
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION float_min_state(state FLOAT8, incoming FLOAT8)
RETURNS FLOAT8 LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
AS $$ BEGIN
    IF state IS NULL THEN RETURN incoming;
    ELSIF incoming < state THEN RETURN incoming;
    ELSE RETURN state; END IF;
END; $$;

CREATE OR REPLACE FUNCTION float_max_state(state FLOAT8, incoming FLOAT8)
RETURNS FLOAT8 LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
AS $$ BEGIN
    IF state IS NULL THEN RETURN incoming;
    ELSIF incoming > state THEN RETURN incoming;
    ELSE RETURN state; END IF;
END; $$;

CREATE OR REPLACE FUNCTION float_sum_state(state FLOAT8, incoming FLOAT8)
RETURNS FLOAT8 LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
AS $$ BEGIN
    IF state IS NULL THEN RETURN incoming;
    ELSE RETURN state + incoming; END IF;
END; $$;

CREATE OR REPLACE FUNCTION float_count_state(state INT, incoming FLOAT8)
RETURNS INT LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE
AS $$ BEGIN RETURN COALESCE(state, 0) + 1; END; $$;

CREATE OR REPLACE FUNCTION float_count_combine(s1 INT, s2 INT)
RETURNS INT LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $$ SELECT COALESCE(s1, 0) + COALESCE(s2, 0) $$;

-- -------------------------------------------------------------------------
-- Custom aggregates (IF NOT EXISTS not supported before PG 15;
-- use DROP AGGREGATE IF EXISTS first if re-running)
-- -------------------------------------------------------------------------
CREATE AGGREGATE array_global_min(FLOAT8) (
    sfunc = float_min_state,
    stype = FLOAT8,
    PARALLEL = SAFE,
    COMBINEFUNC = float_min_state
);

CREATE AGGREGATE array_global_max(FLOAT8) (
    sfunc = float_max_state,
    stype = FLOAT8,
    PARALLEL = SAFE,
    COMBINEFUNC = float_max_state
);

CREATE AGGREGATE array_global_sum(FLOAT8) (
    sfunc = float_sum_state,
    stype = FLOAT8,
    PARALLEL = SAFE,
    COMBINEFUNC = float_sum_state
);

CREATE AGGREGATE array_global_count(FLOAT8) (
    sfunc = float_count_state,
    stype = INT,
    PARALLEL = SAFE,
    COMBINEFUNC = float_count_combine
);

-- -------------------------------------------------------------------------
-- Convenience / helper functions
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION extract_channel(j JSONB, idx INT)
RETURNS FLOAT8 LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $$ SELECT (j->>idx)::FLOAT8 $$;

CREATE OR REPLACE FUNCTION jsonb_array_avg(j JSONB)
RETURNS FLOAT8 LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $$ SELECT avg(value) FROM jsonb_array_to_float8(j) $$;
