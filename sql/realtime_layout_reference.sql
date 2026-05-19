-- Reference SQL for the current four-layout benchmark schema.
-- The Python CLI owns schema creation, seeding, and benchmark execution.

-- JSONB array
CREATE TABLE sensor_payloads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- JSONB object with keys ch0001 ... ch1024
CREATE TABLE sensor_payloads_json_object (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Native typed array
CREATE TABLE sensor_payloads_array (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload real[] NOT NULL CHECK (array_length(payload, 1) = 1024),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Wide table shape. Generate columns ch0001 real through ch1024 real.
-- 1024 float8 columns do not fit PostgreSQL's heap-row size limit.
CREATE TABLE sensor_payloads_wide (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    ch0001 real NOT NULL,
    ch0002 real NOT NULL
    -- ...
);

-- Representative all-channel min/max query for the native array layout.
SELECT
    ord::int - 1 AS channel_idx,
    min(value) AS min_value,
    max(value) AS max_value
FROM sensor_payloads_array
CROSS JOIN LATERAL unnest(payload) WITH ORDINALITY AS u(value, ord)
GROUP BY ord
ORDER BY ord;
