# Circuit Signal — Containerized Platform

## Overview

Graph-aware time-series signal discovery platform. Ingests transactional data (CSV/Parquet), profiles columns (TDV classification), normalizes entities, segments by dimension, runs STL/MSTL decomposition + anomaly detection, and registers signals with vector embeddings for similarity search.

**Domain context:** Built for retail POS data analysis. Deviations represent advertising/buying opportunities. Signals represent the behavioral fingerprint of a product, store, or category over time.

## Architecture

```
Upload → API → MinIO (files) + PostgreSQL (metadata)
                    ↓
         Worker (ARQ/Redis queue)
                    ↓
  Stage 1-2: Profile (TDV) + Normalize entities
  Stage 3:   Build manifest (scenarios, segments)
  Stage 4:   Load → Clean → Segment → Baseline + Deviations (parallel)
  Stage 5:   Upload results to MinIO
  Stage 6:   Register signals + deviations in PostgreSQL (with embeddings)
                    ↓
         API serves signals via REST + pgvector similarity
         MCP Gateway exposes tools for Claude
         Web frontend for exploration
```

## Package Structure

Monorepo with 5 packages under `packages/`. All Python packages use `hatchling` build system with `src/` layout.

| Package | Install Name | Description |
|---------|-------------|-------------|
| `packages/core` | `circuit-core` | Analytical engine: data loading (DuckDB), TDV profiling, entity normalization, batch runner, signal analysis (STL/MSTL, z-scores, change points), signal registry (embeddings, descriptions) |
| `packages/api` | `circuit-api` | FastAPI REST gateway, SQLAlchemy ORM, pgvector queries, MinIO storage, WebSocket progress |
| `packages/worker` | `circuit-worker` | ARQ background tasks: profiling + analysis pipeline execution |
| `packages/mcp_gateway` | `circuit-mcp-gateway` | FastMCP SSE server exposing signal query tools for Claude |
| `packages/web` | — | React 18 + TypeScript + Vite + Tailwind + Recharts frontend |

**Dependency chain:** `api`, `worker`, `mcp_gateway` all depend on `core`. `web` is independent (talks to API via HTTP).

## Docker Services

| Service | Image | Ports | Purpose |
|---------|-------|-------|---------|
| postgres | pgvector/pgvector:pg16 | 5432 | Vector DB with pgvector extension |
| redis | redis:7-alpine | 6379 | Task queue (ARQ) + progress pub/sub |
| minio | minio/minio | 9000, 9001 | S3-compatible file storage |
| api | Dockerfile.api | 8000 | FastAPI + runs alembic migrations on startup |
| worker | Dockerfile.worker | — | ARQ worker (max_jobs=1, memory limit 2GB) |
| mcp-gateway | Dockerfile.mcp-gateway | 8001 | MCP SSE server for Claude |
| web | Dockerfile.web | 3000→80 | React SPA via nginx |

## Database

PostgreSQL 16 with pgvector. Migrations managed by Alembic (`alembic/versions/`).

**Migrations run automatically** on API container startup via `alembic upgrade head` (Dockerfile.api CMD). The `alembic/env.py` reads `DATABASE_URL` from env and strips `+asyncpg` for the sync driver.

### Tables

- **datasets** — File metadata, TDV profile, config, status (uploaded → profiling → profiled)
- **analysis_runs** — Execution tracking, manifest, progress (JSONB), result refs
- **signals** — Full signal record with seasonal arrays, 4 embedding vectors (pgvector HNSW indices), text description, status (active/superseded)
- **deviations** — Individual anomaly records: timestamps, severity, expected/observed values, z-scores, narratives

### Key Schema Details

- `signal_id` format: `{dataset}:{scenario}:{segment}:{run_id}`
- Embedding dimensions: shape=54, deviation=47, text=384, foundation=512
- Seasonal arrays: weekly[7], hourly[24], monthly[12] stored as `FLOAT[]`
- HNSW indices use `vector_cosine_ops` filtered to `status = 'active'`

## Critical Technical Knowledge

### STL Memory Safety
`baseline.py` has a `MAX_STL_POINTS = 10,000` safety cap. Transactional POS data classified as "hourly" can produce 60K+ points which causes STL/MSTL to explode past 32GB RAM. The cap forces daily aggregation.

### Matrix Profile (stumpy)
Moved to optional dependency (`[matrix-profile]`). Disabled in Docker via `DISABLE_MATRIX_PROFILE=1` env var because numba/LLVM runtime adds ~500MB memory overhead. The 3-stage deviation cascade (z-scores → Matrix Profile → change points) gracefully skips Stage 2 when disabled.

### DuckDB Identifier Quoting
Dataset names with hyphens (e.g. "Non-alc") must be double-quoted in DuckDB SQL. The batch runner's `_apply_normalization()` wraps the table name: `f'"{manifest.dataset_name}"'`.

### DuckDB VALUES Column Naming
DuckDB auto-names VALUES columns `col0, col1, col2...` (not `column0`). Normalization lookup SQL must use this convention.

### SQLAlchemy text() and PostgreSQL Casts
`::type` casts conflict with SQLAlchemy's `:param` named parameters. Always use `CAST(:param AS type)` instead of `:param::type` in `text()` queries.

### FastMCP Constructor
In the mcp SDK, `host` and `port` are constructor params on `FastMCP(...)`, not `run()` params. The `run()` call only takes `transport="sse"`.

### Signal Supersession
When re-running analysis, existing active signals for the same dataset:segment are marked `superseded` with a reference to the new signal_id. This preserves history.

### Batch Runner Phases
1. Load (DuckDB) → 2. Clean → 2.5. Normalize → 3. Segment → [free DuckDB] → 4. Parallel baseline+deviations (ProcessPoolExecutor, spawn) → 5. Collect results

Normalization happens at Phase 2.5: lookup tables `_norm_lookup_{column}`, enrichment columns `norm_{col}_{level}`. Disabled by default via `NormalizationConfig.enabled`.

## API Endpoints

### Datasets & Runs
- `POST /api/datasets` — Upload CSV/Parquet
- `GET /api/datasets`, `GET /api/datasets/{id}`
- `POST /api/datasets/{id}/profile` — Trigger TDV profiling
- `POST /api/datasets/{id}/analyze` — Trigger analysis run
- `GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/segments`
- `WebSocket /api/ws/runs/{id}` — Real-time progress

### Signals
- `GET /api/signals` — List with filters (dataset_name, segment_by, status)
- `GET /api/signals/{id}` — Full detail with seasonal arrays + embedding flags
- `GET /api/signals/{id}/similar` — pgvector similarity search (axis: shape/deviation/text)
- `POST /api/signals/search` — Text or signal-based search
- `POST /api/signals/cluster` — K-means clustering by embedding axis

### Deviations
- `GET /api/deviations` — Browse with filters (dataset, segment, severity, type)
- `GET /api/deviations/summary` — Aggregate stats (by severity, type, top segments)
- `GET /api/signals/{id}/deviations` — Deviations for a specific signal

## MCP Gateway Tools

8 tools exposed via SSE on port 8001:
`find_similar`, `get_signal`, `list_signals`, `explain_signal_similarity`, `discover_clusters`, `store_stats`, `list_deviations`, `summarize_deviations`

Connect via `.mcp.json`:
```json
{
  "mcpServers": {
    "circuit-signal": {
      "type": "sse",
      "url": "http://localhost:8001/sse"
    }
  }
}
```

## Frontend Stack

React 18 + TypeScript 5.5 + Vite 5.4 + Tailwind CSS 3.4 + Recharts 2.12 + TanStack React Query v5 + React Router v6.

Pages: Dashboard, Upload, Datasets, DatasetDetail, RunMonitor, SignalExplorer, SignalDetail, ClusterView.

## Development

```bash
# Start all services
cp .env.example .env  # Set ANTHROPIC_API_KEY
docker compose up -d

# Rebuild after code changes
docker compose build api worker mcp-gateway
docker compose up -d api worker mcp-gateway

# View logs
docker compose logs -f worker

# Run local alembic migration (from container/ dir)
alembic upgrade head

# Full reset (destroys all data)
docker compose down -v
```

## Entity Normalizer Tuning
- Default fuzzy threshold: 80
- All-caps penalty: -15
- Pack info penalty: -10 in canonical name selection
- `HierarchyClassifier.classify_with_rules()` needs `'default'` key in rules dict

## Embedding Dimensions

| Axis | Dims | Source |
|------|------|--------|
| Shape | 54 | weekly[7] + hourly[24] + monthly[12] + 11 normalized scalars |
| Deviation | 47 | severity_dist[4] + dayofweek[7] + month[12] + zscore_stats[4] + type_dist[3] + interarrival[4] + changepoint[3] + density[2] + window_hist[8] |
| Text | 384 | sentence-transformers (all-MiniLM-L6-v2) |
| Foundation | 512 | Reserved for future semantic embeddings |
