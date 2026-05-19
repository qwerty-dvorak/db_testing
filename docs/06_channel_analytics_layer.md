# Historical Analytics Layer

This project previously included a derived channel analytics layer with
precomputed bucket summaries and sorted value blocks. That separate build step
has been removed from the runtime CLI because current benchmarking must measure
real-time query work directly.

Use the current benchmark command instead:

```bash
uv run python main.py benchmark --iterations 5 --warmup 2 --threshold 50
```

The benchmark compares four physical tables populated with the same readings:

| Table | Layout |
|-------|--------|
| `sensor_payloads` | JSONB array |
| `sensor_payloads_json_object` | JSONB key-value object |
| `sensor_payloads_array` | Native `real[]` |
| `sensor_payloads_wide` | 1024 typed columns |

All min/max and threshold-count analysis is performed inside the timed queries.
No summary table build time is hidden outside the benchmark.
