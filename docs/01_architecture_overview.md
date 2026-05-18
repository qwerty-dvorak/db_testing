# Architecture Overview — High-Dimensional Sensor Data in PostgreSQL

## Problem Statement

A single sensor payload consists of **1028 discrete floating-point channels** (4-byte `float4` or 8-byte `float8`). At a scale of **1 million rows**, the raw uncompressed data footprint alone approaches several gigabytes — before accounting for MVCC overhead, indexing, and transaction metadata.

## Storage Layouts Compared

### 1. JSONB Storage (Implemented Here)

The `sensor_payloads` table uses a **JSONB column** for the payload. JSONB stores data in a binary, tree-encoded format that:

- Eliminates re-parsing on every read (unlike plain `JSON`)
- Supports GIN indexing (`jsonb_path_ops`)
- Enables flexible schema evolution

**The TOAST bottleneck:** A 1028-element `float8` array consumes ~8.2 KB, immediately exceeding the 2 KB tuple threshold. PostgreSQL's TOAST (The Oversized-Attribute Storage Technique) transparently:

1. Compresses the JSONB payload
2. Moves it to an out-of-line side table
3. Stores only a pointer (OID) in the main 8 KB heap page

Every analytical query forces a **Decompress → Modify → Compress** cycle across potentially millions of rows.

### 2. Native PostgreSQL Arrays (`float8[]`)

| Property          | JSONB                     | Native Array              |
|-------------------|---------------------------|---------------------------|
| Type safety       | Dynamic (cast required)   | Strongly typed            |
| TOAST trigger     | Always (≥2 KB)            | Always (≥2 KB)            |
| Indexing          | GIN with `jsonb_path_ops` | GIN with array ops        |
| Planner stats     | Poor (opaque tree)        | Better (element histograms) |
| Write amplification| Low (single column)       | High under GIN (N entries per row) |

### 3. Normalised (EAV) Model

Transforms columns into rows: 1 payload → 1028 rows.

- **Pro:** Avoids TOAST entirely
- **Con:** 1 million payloads → 1.028 billion rows → ~23 GB of tuple header overhead alone

### 4. Wide Table Model

1028 discrete `float8` columns.

- **Pro:** No TOAST for single-channel queries; columnar I/O
- **Con:** Hard limit of 1600 columns; brittle schema; massive null bitmap overhead

## Physical Storage Architecture (PostgreSQL 18)

```
Heap Page (8 KB)
┌──────────────────────────────┐
│  PageHeaderData  (24 B)      │
│  ┌──────────────────────────┐│
│  │ Tuple 1:                 ││
│  │  │ id (UUID, 16 B)      ││
│  │  │ payload (varlena) ────│────→ TOAST table (compressed)
│  │  │ created_at (8 B)     ││
│  │  └──────────────────────┘│
│  │ Tuple 2: ...             │
│  └──────────────────────────┘
│  Special space               │
└──────────────────────────────┘
```

When `payload` exceeds 2 KB, it is compressed and stored in the `pg_toast` schema. The main tuple retains a 4-byte OID pointer.

## Memory Context Hierarchy

PostgreSQL manages memory in a hierarchical context tree:

```
TopMemoryContext
├── PostmasterContext
├── CacheMemoryContext        (catalog cache — persists across queries)
├── MessageContext
├── TopTransactionContext
│   └── TransactionContext
├── PortalContext
│   └── ExecutorState         (per-query execution)
│       ├── ExprContext
│       ├── TupleSort         (sort/aggregation ops — spills if > work_mem)
│       └── AggContext
└── ErrorContext
```

Key monitoring query (PostgreSQL 14+):

```sql
SELECT name, ident, type, parent, total_bytes, free_bytes, used_bytes
FROM pg_backend_memory_contexts
ORDER BY total_bytes DESC;
```

## Key Configuration Parameters

| Parameter       | Default | Recommended (this workload) | Rationale                          |
|-----------------|---------|-----------------------------|-------------------------------------|
| `work_mem`      | 4 MB    | 256–512 MB                  | Avoid external merge disk spills    |
| `shared_buffers`| 128 MB  | 25% of RAM                  | Cache frequently accessed pages     |
| `jit`           | on      | off (benchmarking)          | Eliminate JIT compilation overhead  |
| `maintenance_work_mem` | 64 MB | 1 GB                 | Speed up VACUUM and index creation  |
| `effective_cache_size` | 4 GB | 75% of RAM             | Help planner estimate index scans   |
