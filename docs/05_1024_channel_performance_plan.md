# Layout Reference

## JSONB Array

```sql
CREATE TABLE sensor_payloads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

All-channel min/max:

```sql
SELECT ord::int - 1 AS channel_idx, min(value::float8), max(value::float8)
FROM sensor_payloads
CROSS JOIN LATERAL jsonb_array_elements_text(payload)
    WITH ORDINALITY AS e(value, ord)
GROUP BY ord
ORDER BY ord;
```

## JSONB Object

```sql
CREATE TABLE sensor_payloads_json_object (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

Payload keys are `ch0001` through `ch1024`.

## Native Array

```sql
CREATE TABLE sensor_payloads_array (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    payload real[] NOT NULL CHECK (array_length(payload, 1) = 1024),
    created_at timestamptz NOT NULL DEFAULT now()
);
```

## Wide Table

```sql
CREATE TABLE sensor_payloads_wide (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    ch0001 real NOT NULL,
    ch0002 real NOT NULL
    -- through ch1024
);
```

The wide layout intentionally uses `real`; a 1024-column `float8` table exceeds
PostgreSQL row-size limits.

## Current Recommendation

Use the CLI benchmark before choosing a layout:

```bash
uv run python main.py benchmark --iterations 5 --warmup 2
```

In broad terms:

- JSONB array is flexible and compact for APIs, but slow for repeated scans.
- JSONB object is useful only when channel names must live inside each row.
- `real[]` is compact and usually strong for all-channel scans.
- wide rows are useful for direct fixed-channel access, with rigid DDL.
