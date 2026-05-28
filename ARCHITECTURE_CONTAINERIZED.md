# Circuit Signal — Containerized Platform Architecture

**Status:** Proposal
**Version:** 1.0
**Author:** John / Discontinuity.ai
**Date:** March 2026
**Supersedes:** ARCHITECTURE.md (MVP), LAYER3_SIGNAL_STORE_SPEC v0.2

---

## What's Changing

The MVP proved the core thesis: STL decomposition + anomaly cascade + cross-segment correlation produces genuinely useful retail behavioral intelligence. But the MVP is a developer tool — it requires Claude Code to orchestrate, runs on a single machine, stores state on the local filesystem, and has no user interface beyond markdown reports.

This document describes the architecture for Circuit Signal as a standalone, containerized product. The goals:

1. **Web interface for data ingestion.** Upload CSVs, configure analysis, monitor pipeline progress. No Claude Code required.
2. **Persistent signal store (the RLM).** Every analysis run accumulates into a queryable Retail Language Model. Signals persist across sessions, users, and datasets.
3. **Query interface — both app and MCP.** Interactive web UI for exploring the signal store, plus an MCP server endpoint for Claude Code / LLM agent integration.
4. **Containerized deployment.** Docker Compose for local dev, Kubernetes-ready for production (GKE).

The analytical core — TDV profiling, entity normalization, STL decomposition, anomaly cascade, signal correlation — is unchanged. What changes is how it's orchestrated, where state lives, and how users interact with it.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              USERS                                      │
│                                                                         │
│   Browser (Web UI)          Claude Code / MCP Clients        API        │
│        │                           │                          │         │
└────────┼───────────────────────────┼──────────────────────────┼─────────┘
         │                           │                          │
         ▼                           ▼                          ▼
┌─────────────────┐  ┌──────────────────────┐  ┌─────────────────────────┐
│   Web Frontend   │  │   MCP Gateway        │  │   API Gateway           │
│   (React SPA)    │  │   (SSE transport)    │  │   (FastAPI)             │
│                  │  │                      │  │                         │
│   • Upload       │  │   • signal-query     │  │   POST /datasets        │
│   • Dashboard    │  │     tools exposed    │  │   POST /datasets/{id}/  │
│   • Explorer     │  │     over MCP         │  │         analyze         │
│   • Reports      │  │   • Auth via API key │  │   GET  /runs/{id}       │
│                  │  │                      │  │   GET  /signals          │
└────────┬─────────┘  └──────────┬───────────┘  │   POST /signals/search  │
         │                       │              │   GET  /store/stats     │
         │                       │              │   ...                   │
         └───────────┬───────────┘              └────────────┬────────────┘
                     │                                       │
                     └──────────────┬────────────────────────┘
                                    │
                     ┌──────────────▼──────────────┐
                     │        Internal Bus          │
                     │        (Redis)               │
                     │                              │
                     │  • Task queue (ARQ)          │
                     │  • Pipeline job state        │
                     │  • Pub/sub for progress      │
                     │  • WebSocket relay           │
                     └──────┬──────────┬────────────┘
                            │          │
               ┌────────────▼──┐  ┌────▼────────────┐
               │  Pipeline      │  │  Query Service   │
               │  Worker(s)     │  │                  │
               │                │  │  • find_similar  │
               │  • Profile     │  │  • cluster       │
               │  • Normalize   │  │  • explain       │
               │  • Plan        │  │  • get/list      │
               │  • Execute     │  │  • store_stats   │
               │  • Report      │  │                  │
               │  • Register    │  │  FAISS indices   │
               │    signals     │  │  in memory       │
               └───────┬───────┘  └────────┬─────────┘
                       │                   │
                       ▼                   ▼
         ┌─────────────────────────────────────────────┐
         │              Data Layer                      │
         │                                             │
         │  ┌───────────┐  ┌──────────┐  ┌──────────┐ │
         │  │ PostgreSQL │  │  MinIO   │  │  Redis   │ │
         │  │ + pgvector │  │ (Object  │  │ (Queue + │ │
         │  │            │  │  Store)  │  │  Cache)  │ │
         │  │ • signals  │  │          │  │          │ │
         │  │ • metadata │  │ • CSVs   │  │ • jobs   │ │
         │  │ • vectors  │  │ • Parquet│  │ • state  │ │
         │  │ • runs     │  │ • Charts │  │ • pubsub │ │
         │  │ • users    │  │ • Reports│  │          │ │
         │  └───────────┘  └──────────┘  └──────────┘ │
         └─────────────────────────────────────────────┘
```

---

## Container Inventory

Seven containers. Docker Compose runs them all locally; in production each becomes a Kubernetes deployment.

| Container | Image Base | Role | Scaling | Stateful? |
|-----------|-----------|------|---------|-----------|
| **web** | Node 22 / nginx | React SPA + static assets | Horizontal | No |
| **api** | Python 3.12 | FastAPI gateway — uploads, pipeline control, query routing | Horizontal | No |
| **mcp-gateway** | Python 3.12 | MCP SSE transport — exposes signal-query tools over MCP protocol | 1 replica | No |
| **worker** | Python 3.12 | Pipeline execution — Stages 1–5 + signal registration | Horizontal (1 job per worker) | No |
| **postgres** | PostgreSQL 16 + pgvector | Relational data, vector indices, signal store | 1 primary + read replicas | Yes |
| **minio** | MinIO | Object storage for files and artifacts | 1 instance (dev), GCS (prod) | Yes |
| **redis** | Redis 7 | Task queue, job state, pub/sub for progress, ephemeral cache | 1 instance | Semi |

### What Moved Where

| MVP Component | Containerized Equivalent |
|--------------|------------------------|
| Claude Code orchestrator | `worker` container (ARQ task queue replaces agent orchestration) |
| `batch-runner` CLI | `worker` container (same code, triggered by API instead of CLI) |
| MCP servers (Layer 0–2) | `worker` container (imported as libraries, not MCP protocol) |
| Signal-ingest MCP | `worker` container (registration happens at end of pipeline) |
| Signal-query MCP | `query` logic inside `api` container + `mcp-gateway` for MCP clients |
| DuckDB (metadata) | `postgres` container (pgvector for vectors, standard tables for metadata) |
| DuckDB (in-pipeline) | Still DuckDB, ephemeral per-job inside `worker` (loaded into memory, discarded after) |
| Local filesystem (CSVs, Parquet, charts) | `minio` container (S3-compatible object storage) |
| FAISS indices on disk | pgvector in `postgres` (vector similarity is SQL, not a separate index file) |
| `.claude/agents/` | Removed — pipeline is deterministic, driven by manifest + task queue |

**Key decision: DuckDB stays inside the worker.** The pipeline's analytical core (load → clean → normalize → segment → STL → anomaly cascade) works best with DuckDB's single-process embedded model. Each worker job gets an ephemeral DuckDB instance, processes the data, and writes results to PostgreSQL + MinIO. DuckDB is a compute engine here, not a storage engine.

---

## Data Flow: Upload → Pipeline → Signal Store → Query

### 1. Upload

```
User uploads CSV(s) via web UI or API
    │
    ▼
API validates file(s):
  • File type check (CSV, Parquet, JSON)
  • Size limit check
  • Virus/malware scan (ClamAV sidecar in prod)
    │
    ▼
API stores file(s) in MinIO:
  bucket: uploads/{dataset_id}/{filename}
    │
    ▼
API creates dataset record in PostgreSQL:
  datasets table: {id, name, created_by, status: "uploaded", file_refs: [...]}
    │
    ▼
API returns dataset_id to user
```

### 2. Profile & Configure

```
User triggers profiling (or it auto-runs on upload)
    │
    ▼
API enqueues task: {type: "profile", dataset_id}
    │
    ▼
Worker picks up task:
  1. Downloads file(s) from MinIO → ephemeral DuckDB
  2. Runs TDV Profiler (Stage 1)
  3. Runs Entity Normalizer (Stage 2)
  4. Stores TDV graph + normalization graph in PostgreSQL (JSONB)
  5. Updates dataset status: "profiled"
  6. Publishes progress events to Redis pub/sub
    │
    ▼
API returns profile results to UI:
  • Column classifications (Time, Discriminator, Value)
  • Entity clusters found
  • Suggested segmentation strategies
  • Detected temporal grain
    │
    ▼
User reviews profile, optionally adjusts:
  • Override column classifications
  • Choose segmentation level (brand vs product vs store)
  • Set analysis parameters (sensitivity, lookback window)
  • Add tags (geography, category, etc.)
    │
    ▼
API stores configuration as analysis_config in PostgreSQL
```

### 3. Analyze

```
User triggers analysis (or auto-runs after profiling if config is default)
    │
    ▼
API generates manifest from profile + config:
  • Same YAML manifest format as MVP batch-runner
  • Stored in PostgreSQL (analysis_runs table)
    │
    ▼
API enqueues task: {type: "analyze", run_id, manifest}
    │
    ▼
Worker picks up task:
  1. Downloads file(s) from MinIO → ephemeral DuckDB
  2. Runs Plan Builder (Stage 3) — generates execution plan from manifest
  3. Runs Batch Runner (Stage 4):
     a. Load → Clean → Normalize → Segment (sequential, in DuckDB)
     b. Export segments as Parquet → MinIO (segments/{run_id}/*.parquet)
     c. For each segment (parallel within worker via ProcessPoolExecutor):
        - STL decomposition (baseline)
        - Three-stage anomaly cascade (deviations)
        - Store results JSON → MinIO (results/{run_id}/{segment}.json)
     d. Progress events published to Redis after each segment completes
  4. Runs Report Agent (Stage 5):
     a. Reads all segment results
     b. Generates matplotlib charts → MinIO (charts/{run_id}/*.png)
     c. Generates markdown report → MinIO (reports/{run_id}/report.md)
     d. Cross-segment correlation (Layer 2) if multiple segments
  5. Signal Registration (Stage 6 — NEW):
     a. For each segment:
        - Extract shape embedding (Tier 1, numpy)
        - Extract deviation embedding (Tier 2, numpy)
        - Generate text description (Anthropic API, batched)
        - Compute text embedding (sentence-transformers)
     b. Bulk insert into PostgreSQL:
        - signals table (metadata + decomposed components)
        - pgvector columns (shape_embedding, deviation_embedding, text_embedding)
     c. Mark any prior signals for same dataset:segment as superseded
  6. Updates run status: "completed"
  7. Publishes completion event to Redis
    │
    ▼
User sees:
  • Real-time progress bar (via WebSocket, fed by Redis pub/sub)
  • Completed report with charts
  • Signal store updated with new signals
```

### 4. Query

```
User queries the signal store via:
  A) Web UI explorer — form-based search, visual results
  B) API endpoint — POST /signals/search
  C) MCP client — signal-query tools over SSE transport

All three route to the same query logic:
    │
    ▼
Query Service (inside api container):
  1. Parse query (natural language OR signal_id OR filters)
  2. If natural language:
     a. Embed query text with sentence-transformers (loaded in-process)
     b. pgvector similarity search on text_embedding column
  3. If signal_id:
     a. Look up signal's embedding
     b. pgvector similarity search on requested axis (shape/deviation/text/ensemble)
  4. Apply metadata filters (dataset, tags, status, grain)
  5. Return ranked results with descriptions and shape summaries
    │
    ▼
Results displayed in:
  • Web UI: card-based results with similarity scores, expandable signal details
  • API: JSON response
  • MCP: tool result JSON (same schema as v0.2 spec)
```

---

## Service Specifications

### `api` — FastAPI Gateway

The central service. Handles HTTP requests from the web frontend and external API consumers. Routes queries to PostgreSQL/pgvector directly (no separate query service container — the query logic is a library inside the API process).

**Why query lives inside the API, not a separate container:** In the MVP spec, `signal-query` was a separate MCP server because the read path needed isolation from the write path's lock contention. With pgvector, there's no file-level locking — reads and writes are concurrent PostgreSQL transactions. A separate container adds network hop latency for every query with no isolation benefit. The query module is imported as a library into the API process.

```
Endpoints:

# --- Dataset Management ---
POST   /api/datasets                     # Upload CSV(s), create dataset
GET    /api/datasets                     # List datasets
GET    /api/datasets/{id}                # Dataset detail + profile results
DELETE /api/datasets/{id}                # Soft-delete dataset and associated signals
POST   /api/datasets/{id}/profile        # Trigger profiling
PATCH  /api/datasets/{id}/config         # Update analysis configuration

# --- Analysis Runs ---
POST   /api/datasets/{id}/analyze        # Trigger analysis run
GET    /api/runs                          # List runs (filterable by dataset, status)
GET    /api/runs/{id}                     # Run detail + progress
GET    /api/runs/{id}/report             # Rendered report (HTML or markdown)
GET    /api/runs/{id}/charts/{name}      # Individual chart image (proxied from MinIO)
GET    /api/runs/{id}/segments           # List segments with summary stats

# --- Signal Store (Query) ---
GET    /api/signals                       # List signals (filterable, paginated)
GET    /api/signals/{id}                  # Full signal record
POST   /api/signals/search               # Similarity search (NL or signal-to-signal)
POST   /api/signals/cluster              # Discover occasion archetypes
POST   /api/signals/explain              # Explain similarity between two signals
GET    /api/store/stats                   # Signal store summary statistics

# --- External Signals ---
POST   /api/external-signals             # Upload + register external time series

# --- System ---
GET    /api/health                        # Readiness/liveness
GET    /api/ws/runs/{id}                  # WebSocket for real-time pipeline progress
```

**Tech stack:**
- FastAPI + Uvicorn (4 workers default)
- SQLAlchemy 2.0 + asyncpg (PostgreSQL async driver)
- sentence-transformers loaded in-process (for text query embedding at query time)
- boto3 / aioboto3 (MinIO / S3 client)
- ARQ client (enqueue pipeline tasks)

**Configuration (environment variables):**
```
DATABASE_URL=postgresql+asyncpg://circuit:***@postgres:5432/circuit
REDIS_URL=redis://redis:6379
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=circuit
MINIO_SECRET_KEY=***
ANTHROPIC_API_KEY=***              # Passed through to workers; API itself doesn't call Anthropic
TEXT_ENCODER_MODEL=all-MiniLM-L6-v2
MAX_UPLOAD_SIZE_MB=500
CORS_ORIGINS=["http://localhost:3000"]
```

### `worker` — Pipeline Worker

Consumes tasks from the ARQ queue and executes the full analysis pipeline. This is where all the heavy computation happens. Stateless between jobs — each job gets an ephemeral DuckDB instance that's discarded after.

**Task types:**

| Task | Trigger | Duration | CPU | Memory |
|------|---------|----------|-----|--------|
| `profile` | Dataset upload or manual | 5–30s | Low | Low |
| `analyze` | User-triggered | 1–30min (depends on data size) | High (parallel STL) | High (DuckDB in-memory) |
| `ingest_external` | External signal upload | 5–15s | Low | Low |
| `backfill_embeddings` | Admin/maintenance | Variable | Medium | Medium |

**Internal architecture:**
```
worker process
├── ARQ consumer (async event loop)
│   └── picks up tasks from Redis queue
├── Pipeline orchestrator
│   ├── TDV Profiler        (imported from tdv_profiler package)
│   ├── Entity Normalizer   (imported from data_prep package)
│   ├── Plan Builder         (imported from data_prep package)
│   ├── Batch Runner         (imported from batch_runner package)
│   │   ├── Layer 0 tools   (imported directly, not via MCP)
│   │   ├── Layer 1 tools   (imported directly, not via MCP)
│   │   └── Layer 2 tools   (imported directly, not via MCP)
│   └── Signal Registrar     (NEW — embedding extraction + DB write)
├── DuckDB instance          (ephemeral, per-job)
├── MinIO client             (read uploads, write results)
├── PostgreSQL client        (write signals, update run status)
└── Redis client             (publish progress events)
```

**The MCP servers become libraries.** In the MVP, Layer 0–2 were MCP servers with FastMCP decorators. In the containerized version, the worker imports their tool functions directly — the same pattern the batch-runner already uses. The MCP protocol boundary is unnecessary when everything runs in-process. The tool functions remain clean, testable units; they just aren't wrapped in MCP transport.

**Concurrency model:** Each worker process handles one job at a time. Within a job, the Batch Runner uses `ProcessPoolExecutor(spawn)` for parallel segment analysis (same as MVP). Scale by running multiple worker containers.

**Configuration:**
```
DATABASE_URL=postgresql://circuit:***@postgres:5432/circuit
REDIS_URL=redis://redis:6379
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=circuit
MINIO_SECRET_KEY=***
ANTHROPIC_API_KEY=***              # For text description generation during signal registration
TEXT_ENCODER_MODEL=all-MiniLM-L6-v2
WORKER_CONCURRENCY=1               # Jobs per worker process
WORKER_MAX_MEMORY_MB=4096          # Kill job if exceeded
BATCH_PARALLEL_WORKERS=4           # ProcessPoolExecutor size for segment analysis
```

### `mcp-gateway` — MCP Protocol Adapter

Exposes signal-query tools over MCP's SSE transport, enabling Claude Code and other MCP clients to query the signal store without going through the REST API.

**This is a thin adapter.** It imports the same query module that the API uses, wraps each function as an MCP tool, and serves them over Server-Sent Events (the MCP HTTP transport). No business logic lives here — it's pure protocol translation.

**Tools exposed (identical schema to v0.2 signal-query spec):**
- `find_similar` — similarity search (NL or signal-to-signal)
- `cluster_signals` — discover occasion archetypes
- `get_signal` — full signal record
- `list_signals` — browse with filters
- `explain_similarity` — compare two signals
- `store_stats` — store summary

**MCP client configuration (for Claude Code users):**
```json
{
  "mcpServers": {
    "circuit-signal": {
      "type": "sse",
      "url": "http://localhost:8001/mcp",
      "headers": { "Authorization": "Bearer {api_key}" }
    }
  }
}
```

**Tech stack:**
- FastMCP with SSE transport (same SDK as MVP, different transport)
- Imports `signal_query` module from shared package
- Single-process, single-replica (MCP SSE is stateful per connection)

### `web` — React Frontend

Single-page application served by nginx. Communicates with the API via REST + WebSocket.

**Views:**

| View | Purpose |
|------|---------|
| **Upload** | Drag-and-drop CSV upload, multi-file support, progress indicator |
| **Dataset Detail** | Profile results (column classifications, entity clusters), configuration panel, trigger analysis |
| **Run Monitor** | Real-time progress (WebSocket), segment-by-segment status, estimated time remaining |
| **Report Viewer** | Rendered markdown report with inline charts, exportable as PDF |
| **Signal Explorer** | Search the signal store — natural language input, filter sidebar, card-based results |
| **Signal Detail** | Full signal record — seasonal shape visualization, deviation timeline, related signals |
| **Cluster View** | Occasion archetypes — cluster map visualization, archetype cards, member lists |
| **Store Dashboard** | Signal store statistics, ingestion timeline, dataset coverage |

**Tech stack:**
- React 18 + TypeScript
- Tailwind CSS
- Recharts (for signal visualizations — seasonal shapes, deviation timelines)
- React Query (server state management)
- React Router

### `postgres` — PostgreSQL + pgvector

Single PostgreSQL instance with pgvector extension for vector similarity search. Replaces both DuckDB (for metadata) and FAISS (for embeddings) from the MVP.

**Schema:**

```sql
-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- For fuzzy text search on signal descriptions

-- Datasets
CREATE TABLE datasets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    created_by      TEXT,                    -- User or API key identifier
    status          TEXT NOT NULL DEFAULT 'uploaded',
                                             -- uploaded | profiling | profiled | error
    file_refs       JSONB NOT NULL,          -- [{bucket, key, filename, size_bytes}]
    profile         JSONB,                   -- TDV graph + normalization graph
    config          JSONB,                   -- Analysis configuration (overrides)
    tags            JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    deleted_at      TIMESTAMPTZ              -- Soft delete
);

-- Analysis Runs
CREATE TABLE analysis_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id      UUID REFERENCES datasets(id),
    status          TEXT NOT NULL DEFAULT 'queued',
                                             -- queued | profiling | analyzing | reporting |
                                             -- registering | completed | failed
    manifest        JSONB NOT NULL,          -- Full manifest (YAML parsed to JSON)
    progress        JSONB DEFAULT '{}',      -- {segments_total, segments_done, current_stage, ...}
    result_refs     JSONB,                   -- MinIO paths to results, charts, report
    error           TEXT,                    -- Error message if failed
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- Signals (the RLM core)
CREATE TABLE signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id       TEXT UNIQUE NOT NULL,     -- {dataset}:{segment}:{run_id}
    dataset_id      UUID REFERENCES datasets(id),
    run_id          UUID REFERENCES analysis_runs(id),

    -- Source metadata
    dataset_name    TEXT NOT NULL,
    segment         TEXT NOT NULL,
    segment_by      TEXT NOT NULL,
    time_range      TSTZRANGE,
    temporal_grain  TEXT NOT NULL,
    row_count       INTEGER,
    tags            JSONB DEFAULT '{}',

    -- Decomposed components
    trend_slope     DOUBLE PRECISION,
    trend_intercept DOUBLE PRECISION,
    seasonal_weekly DOUBLE PRECISION[7],
    seasonal_hourly DOUBLE PRECISION[24],
    seasonal_monthly DOUBLE PRECISION[12],
    seasonality_strength DOUBLE PRECISION,
    residual_std    DOUBLE PRECISION,

    -- Deviation summary
    deviation_count_90d INTEGER,
    deviation_density DOUBLE PRECISION,
    critical_pct    DOUBLE PRECISION,
    change_points   JSONB,                   -- [{date, magnitude, direction}]

    -- Embeddings
    shape_embedding     vector(54),
    deviation_embedding vector(47),
    foundation_embedding vector(512),        -- NULL until Tier 3 enabled
    text_description    TEXT,
    text_embedding      vector(384),

    -- Lifecycle
    status          TEXT NOT NULL DEFAULT 'active',
                                             -- active | superseded | tombstoned
    superseded_by   TEXT,                    -- signal_id of newer version
    registered_at   TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Vector indices (pgvector HNSW — faster than IVFFlat for <100K vectors)
CREATE INDEX idx_signals_shape ON signals
    USING hnsw (shape_embedding vector_cosine_ops)
    WHERE status = 'active';

CREATE INDEX idx_signals_deviation ON signals
    USING hnsw (deviation_embedding vector_cosine_ops)
    WHERE status = 'active';

CREATE INDEX idx_signals_text ON signals
    USING hnsw (text_embedding vector_cosine_ops)
    WHERE status = 'active';

CREATE INDEX idx_signals_foundation ON signals
    USING hnsw (foundation_embedding vector_cosine_ops)
    WHERE status = 'active' AND foundation_embedding IS NOT NULL;

-- Metadata indices
CREATE INDEX idx_signals_dataset ON signals(dataset_name);
CREATE INDEX idx_signals_segment_by ON signals(segment_by);
CREATE INDEX idx_signals_status ON signals(status);
CREATE INDEX idx_signals_tags ON signals USING gin(tags);
CREATE INDEX idx_signals_description ON signals USING gin(text_description gin_trgm_ops);

-- External signals (weather, events, economic — same table, different dataset convention)
-- Use dataset_name = 'external:{source}' to distinguish
-- e.g., "external:noaa", "external:yahoo_finance"
```

**Why pgvector over FAISS:** The MVP used FAISS because it was local and fast. In a multi-container environment, FAISS requires either a shared filesystem (fragile) or a dedicated vector service (over-engineered for <100K vectors). pgvector gives us vector similarity search as SQL queries, transactional consistency with metadata, and a single data layer to manage. HNSW indices provide <10ms query times for the scale we're targeting. The partial index on `status = 'active'` keeps superseded signals out of the search path without deleting them.

### `minio` — Object Storage

S3-compatible object storage for all file artifacts. In production, replaced by GCS with the same API (via S3 compatibility layer or direct GCS client).

**Bucket structure:**
```
circuit-signal/
├── uploads/
│   └── {dataset_id}/
│       └── {filename}                    # Raw uploaded files
├── segments/
│   └── {run_id}/
│       └── {segment_name}.parquet        # Segmented data files
├── results/
│   └── {run_id}/
│       └── {segment_name}.json           # Layer 1 baseline + deviation results
├── charts/
│   └── {run_id}/
│       └── {chart_name}.png              # Generated matplotlib charts
├── reports/
│   └── {run_id}/
│       ├── report.md                     # Markdown report
│       └── report.pdf                    # PDF export (optional)
└── graphs/
    └── {dataset_id}/
        ├── tdv_graph.json                # TDV profiler output
        └── norm_graph.json               # Entity normalizer output
```

### `redis` — Task Queue & Pub/Sub

**Three roles:**

1. **Task queue (ARQ).** Pipeline jobs are enqueued by the API and consumed by workers. ARQ provides retry logic, timeout handling, and job result storage.

2. **Progress pub/sub.** Workers publish progress events (`{run_id, stage, segment, percent}`) to Redis channels. The API's WebSocket handler subscribes and relays to the frontend.

3. **Ephemeral cache.** Query results, cluster labels, and sentence-transformer model weights (if needed across restarts) can be cached in Redis. TTL-based expiry, no persistence required.

---

## Package Reorganization

The MVP's package structure was optimized for MCP server independence. The containerized version reorganizes around three deployment targets: worker, api, and shared libraries.

```
circuit-signal/
├── docker-compose.yml
├── docker-compose.prod.yml
├── Dockerfile.api
├── Dockerfile.worker
├── Dockerfile.mcp-gateway
├── Dockerfile.web
│
├── packages/
│   ├── core/                             # Shared analytical libraries
│   │   ├── pyproject.toml
│   │   └── src/circuit_core/
│   │       ├── tdv_profiler/             # TDV column classification (from tdv_profiler/)
│   │       ├── data_prep/                # Entity normalization, plan builder (from data_prep/)
│   │       ├── batch_runner/             # Pipeline execution engine (from batch_runner/)
│   │       ├── signal_analysis/          # Layer 1 tools: baseline, deviations, forecast
│   │       ├── signal_correlation/       # Layer 2 tools: cross-source correlation
│   │       ├── signal_registry/          # NEW: embedding extraction + DB registration
│   │       ├── query_planner/            # Graph-based dataset discovery
│   │       └── schema/                   # Shared types: SignalRecord, RunConfig, etc.
│   │
│   ├── api/                              # FastAPI gateway
│   │   ├── pyproject.toml                # depends on circuit-core
│   │   └── src/circuit_api/
│   │       ├── main.py                   # FastAPI app factory
│   │       ├── routes/
│   │       │   ├── datasets.py           # Upload, profile, configure
│   │       │   ├── runs.py               # Analysis run control + monitoring
│   │       │   ├── signals.py            # Signal store queries
│   │       │   ├── external.py           # External signal ingestion
│   │       │   └── system.py             # Health, stats
│   │       ├── services/
│   │       │   ├── query.py              # Signal similarity search (pgvector queries)
│   │       │   ├── clustering.py         # Occasion archetype discovery
│   │       │   └── text_encoder.py       # Sentence-transformer for query embedding
│   │       ├── models/                   # SQLAlchemy models
│   │       ├── tasks.py                  # ARQ task definitions (enqueue only)
│   │       └── ws.py                     # WebSocket handler for progress relay
│   │
│   ├── worker/                           # Pipeline worker
│   │   ├── pyproject.toml                # depends on circuit-core
│   │   └── src/circuit_worker/
│   │       ├── main.py                   # ARQ worker entry point
│   │       ├── tasks/
│   │       │   ├── profile.py            # Stages 1–2
│   │       │   ├── analyze.py            # Stages 3–5 + signal registration
│   │       │   ├── ingest_external.py    # External signal processing
│   │       │   └── backfill.py           # Embedding backfill maintenance
│   │       └── progress.py              # Redis pub/sub progress publisher
│   │
│   ├── mcp_gateway/                      # MCP protocol adapter
│   │   ├── pyproject.toml                # depends on circuit-core, circuit-api (query module)
│   │   └── src/circuit_mcp/
│   │       ├── main.py                   # FastMCP SSE server
│   │       └── tools.py                  # Tool definitions wrapping query service
│   │
│   └── web/                              # React frontend
│       ├── package.json
│       └── src/
│           ├── pages/
│           │   ├── Upload.tsx
│           │   ├── DatasetDetail.tsx
│           │   ├── RunMonitor.tsx
│           │   ├── ReportViewer.tsx
│           │   ├── SignalExplorer.tsx
│           │   ├── SignalDetail.tsx
│           │   ├── ClusterView.tsx
│           │   └── Dashboard.tsx
│           ├── components/
│           │   ├── SeasonalShape.tsx      # Visualize 7-day + 24-hour + 12-month patterns
│           │   ├── DeviationTimeline.tsx   # Interactive deviation event viewer
│           │   ├── SimilarityCard.tsx      # Signal comparison card
│           │   └── ClusterMap.tsx          # 2D embedding projection (UMAP/t-SNE)
│           └── api/
│               └── client.ts              # Generated API client (OpenAPI → TypeScript)
│
├── alembic/                              # Database migrations
│   ├── alembic.ini
│   └── versions/
│       └── 001_initial_schema.py
│
├── scripts/
│   ├── seed_store.py                     # Load sample data for development
│   └── migrate.py                        # Alembic wrapper
│
└── deploy/
    ├── kubernetes/
    │   ├── api.yaml
    │   ├── worker.yaml
    │   ├── mcp-gateway.yaml
    │   ├── web.yaml
    │   ├── postgres.yaml
    │   └── redis.yaml
    └── helm/                             # Future: Helm chart
```

---

## Docker Compose (Development)

```yaml
version: "3.9"

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: circuit
      POSTGRES_USER: circuit
      POSTGRES_PASSWORD: circuit_dev
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U circuit"]
      interval: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: circuit
      MINIO_ROOT_PASSWORD: circuit_dev
    ports:
      - "9000:9000"
      - "9001:9001"    # MinIO console
    volumes:
      - miniodata:/data

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    environment:
      DATABASE_URL: postgresql+asyncpg://circuit:circuit_dev@postgres:5432/circuit
      REDIS_URL: redis://redis:6379
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: circuit
      MINIO_SECRET_KEY: circuit_dev
      TEXT_ENCODER_MODEL: all-MiniLM-L6-v2
    ports:
      - "8000:8000"
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
      minio: { condition: service_started }

  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      DATABASE_URL: postgresql://circuit:circuit_dev@postgres:5432/circuit
      REDIS_URL: redis://redis:6379
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: circuit
      MINIO_SECRET_KEY: circuit_dev
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      TEXT_ENCODER_MODEL: all-MiniLM-L6-v2
      BATCH_PARALLEL_WORKERS: 4
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
      minio: { condition: service_started }
    deploy:
      replicas: 2    # Two workers for parallel job processing

  mcp-gateway:
    build:
      context: .
      dockerfile: Dockerfile.mcp-gateway
    environment:
      DATABASE_URL: postgresql+asyncpg://circuit:circuit_dev@postgres:5432/circuit
      TEXT_ENCODER_MODEL: all-MiniLM-L6-v2
    ports:
      - "8001:8001"
    depends_on:
      postgres: { condition: service_healthy }

  web:
    build:
      context: .
      dockerfile: Dockerfile.web
    ports:
      - "3000:80"
    depends_on:
      - api

volumes:
  pgdata:
  miniodata:
```

---

## Authentication & Multi-tenancy

### Phase 1 (Single-tenant, local dev)

No authentication. All data is accessible to all users. API keys for MCP gateway are static environment variables.

### Phase 2 (Multi-tenant, production)

- **API keys** for programmatic access (MCP gateway, REST API)
- **OAuth2 / OIDC** for web UI (via Keycloak on GKE, or Auth0)
- **Row-level security** in PostgreSQL: `datasets.created_by` and `signals.dataset_id → datasets.created_by` enforce tenant isolation
- **MinIO bucket policies** per tenant (prefix-based: `uploads/{tenant_id}/`)

Tenant isolation is critical for the 1864 portfolio use case — multiple portfolio companies' POS data in the same signal store, each company seeing only their own data, but with the option to enable cross-tenant analytics for the GP view.

---

## Migration from MVP

### Code Migration

| MVP Source | Target Package | Changes Required |
|-----------|---------------|-----------------|
| `tdv_profiler/` | `packages/core/src/circuit_core/tdv_profiler/` | None — pure library, no I/O changes |
| `data_prep/` | `packages/core/src/circuit_core/data_prep/` | None — pure library |
| `batch_runner/` | `packages/core/src/circuit_core/batch_runner/` | Replace local file paths with MinIO get/put |
| `mcp/layer0/` tools | `packages/core/src/circuit_core/batch_runner/` | Strip MCP decorators, keep tool functions |
| `mcp/layer1/` tools | `packages/core/src/circuit_core/signal_analysis/` | Strip MCP decorators, keep tool functions |
| `mcp/layer2/` tools | `packages/core/src/circuit_core/signal_correlation/` | Strip MCP decorators, keep tool functions |
| `mcp/query-planner/` | `packages/core/src/circuit_core/query_planner/` | Strip MCP decorators, keep tool functions |
| Signal registration logic (v0.2 spec) | `packages/core/src/circuit_core/signal_registry/` | Replace FAISS + DuckDB with pgvector inserts |
| Signal query logic (v0.2 spec) | `packages/api/src/circuit_api/services/query.py` | Replace FAISS search with pgvector SQL |

The analytical core is portable because the MVP's MCP tools are just decorated Python functions. Stripping the `@mcp.tool()` decorator and importing directly is a one-line change per tool. The only substantive change is replacing local filesystem I/O with MinIO (for files) and PostgreSQL (for metadata + vectors).

### Data Migration

For existing signal stores from the MVP (DuckDB + FAISS):

```bash
# Export signals from DuckDB
python scripts/migrate_signals.py \
    --source signal_store/signals.duckdb \
    --embeddings signal_store/embeddings/ \
    --target postgresql://circuit:***@postgres:5432/circuit
```

---

## Scaling Considerations

| Component | Bottleneck | Scaling Strategy |
|-----------|-----------|-----------------|
| `api` | Request throughput | Horizontal (add replicas behind load balancer) |
| `worker` | Pipeline compute (STL, anomaly cascade) | Horizontal (add worker replicas, each handles one job) |
| `worker` | Memory (DuckDB in-memory with large datasets) | Vertical (increase memory limit per worker) |
| `postgres` | Vector search at scale (>100K signals) | Read replicas for queries; HNSW index tuning; partition by dataset |
| `postgres` | Write throughput during batch registration | Bulk inserts with `COPY`; batched pgvector operations |
| `minio` | Storage volume | Lifecycle policies (expire old segments/results after N days) |
| `web` | N/A (static files) | CDN in production |

**Expected signal store size:** At 50 segments per analysis run and 10 runs per week, the store grows by ~500 signals/week. At 54-dimension shape embeddings + 47-dimension deviation embeddings + 384-dimension text embeddings per signal, the vector data is ~2KB per signal. Even at 100K signals, the total vector data is ~200MB — well within single-instance PostgreSQL capacity.

---

## Implementation Priority

| Phase | Deliverable | Effort |
|-------|------------|--------|
| **1. Foundation** | Docker Compose with postgres + redis + minio. Alembic schema migration. `circuit-core` package with existing code reorganized (strip MCP decorators). | 1 week |
| **2. Worker** | ARQ worker consuming `profile` and `analyze` tasks. MinIO read/write for files. PostgreSQL write for run status + signals. | 1 week |
| **3. API** | FastAPI with dataset upload, run triggering, signal query endpoints. pgvector similarity search. WebSocket progress relay. | 1 week |
| **4. Web MVP** | Upload page, run monitor (WebSocket progress), report viewer, basic signal explorer. | 1 week |
| **5. MCP Gateway** | FastMCP SSE server wrapping query endpoints. Claude Code integration test. | 2–3 days |
| **6. Signal Explorer** | Full signal detail view, explain similarity, cluster visualization, natural language search. | 1 week |
| **7. Production Hardening** | Auth (API keys + OAuth), error handling, retry logic, monitoring (Prometheus + Grafana), rate limiting. | 1 week |
| **8. Kubernetes** | Deployment manifests, Helm chart, GKE deploy, GCS instead of MinIO, Cloud SQL instead of local PostgreSQL. | 1 week |

**Total estimate to production: 6–8 weeks**, with a functional demo (Phases 1–4) available at ~4 weeks.

---

*Architecture version: 1.0 — March 2026*
*Circuit Signal — Containerized Platform*
