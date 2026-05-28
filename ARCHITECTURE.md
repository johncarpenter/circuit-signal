# Circuit Signal — Architecture

## What It Does

Circuit Signal turns raw transactional data — messy CSVs from POS systems, booking platforms, CRM exports — into structured time-series insights. Give it a data lake of flat files, and it will figure out what the columns mean, clean up the entity names, split the data into meaningful segments, detect anomalies and trends in each segment, correlate signals across segments and external data sources, and produce a report with charts and narrative.

The core insight is that most business data analysis follows a repeatable pattern: profile the data, normalize the entities, segment by dimension, analyze each segment's time series, then look for cross-segment patterns. Circuit Signal automates that pattern.

## System Overview

The system has five processing stages and four infrastructure layers:

```
Raw Data Files (CSV/Parquet/JSON)
        │
        ▼
┌─────────────────────────┐
│  Stage 1: PROFILE       │  What are these columns? Time? Category? Metric?
│  (TDV Profiler)         │  Output: tdv_graph.json
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│  Stage 2: NORMALIZE     │  "corona_lt" and "Corona Light" are the same thing.
│  (Entity Normalizer)    │  Output: norm_graph.json
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│  Stage 3: PLAN          │  Which datasets to join? How to segment? What to measure?
│  (Plan Builder)         │  Output: manifest.yaml
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│  Stage 4: EXECUTE       │  Load → Clean → Normalize → Segment → Parallel Analysis
│  (Batch Runner)         │  Output: per-segment baselines + deviations
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│  Stage 5: REPORT        │  Cross-segment correlation, charts, narrative report
│  (Report Agent)         │  Output: analysis_report.md + charts/
└─────────────────────────┘
```

The four infrastructure layers are MCP servers that expose tools:

| Layer | Server | Purpose |
|-------|--------|---------|
| Layer 0 | data-loader | Load, clean, profile, and segment raw data |
| Layer 1 | signal-discovery | Time-series baseline, deviation detection, forecasting |
| Layer 2 | signal-correlation | Cross-source temporal/spatial/entity correlation |
| Query Planner | query-planner | Graph traversal, dataset discovery, join planning |


## How Data Flows Through the System

### Concrete Example: Beer POS Data

Start with `data/beer/all-beer.csv` — 85K rows of beer sales from 90+ stores, with messy product names like `corona_lt`, `Corona Light`, `CORONA LT 12PK`, `bud light`, `Bud Light Lime`, `bud lite`.

**Stage 1 — Profile.** The TDV Profiler scans the file and classifies each column:

| Column | Classification | Reasoning |
|--------|---------------|-----------|
| `created` | Time | Parses as datetime, >80% success |
| `store_id` | Discriminator | String, cardinality ~200, <5% ratio |
| `product_name` | Discriminator | String, cardinality ~200 |
| `amount` | Value | Float, high coefficient of variation |

It also detects the temporal grain (hourly) and builds a graph of relationships between datasets, columns, and values. Output: `output/beer/tdv_graph.json`.

**Stage 2 — Normalize.** The Entity Normalizer takes the ~200 distinct product names and:
1. Text-normalizes them (lowercase, expand abbreviations like `lt→light`, strip pack info like `12PK`)
2. Fuzzy-clusters them into canonical forms (16 variants → 5 canonical products)
3. Classifies each canonical into a hierarchy (product → brand → category → department)

```
corona_lt        → Corona Light → brand: Corona    → category: Beer → dept: Beverages
Corona Light     → Corona Light → brand: Corona    → category: Beer → dept: Beverages
CORONA LT 12PK  → Corona Light → brand: Corona    → category: Beer → dept: Beverages
bud light        → Bud Light   → brand: Budweiser  → category: Beer → dept: Beverages
Bud Light Lime   → Bud Light   → brand: Budweiser  → category: Beer → dept: Beverages
```

Output: `output/beer/norm_graph.json` — a NetworkX graph with `RAW_VALUE → CANONICAL → BRAND → CATEGORY` edges.

**Stage 3 — Plan.** The Plan Builder consumes both graphs, determines that segmenting by `brand` (4 segments) is better than by raw `product_name` (200 segments, most too small), and generates a manifest that tells the Batch Runner exactly what to do. Output: `output/beer/manifest.yaml`.

**Stage 4 — Execute.** The Batch Runner reads the manifest and runs:

1. **Load** — Read CSV into DuckDB (in-memory)
2. **Clean** — Auto-detect and fix whitespace, case inconsistencies, null patterns
3. **Normalize** — Create a lookup table from the normalization graph, LEFT JOIN it onto the dataset, adding columns like `norm_product_name_brand`
4. **Segment** — Split by `norm_product_name_brand` → 4 Parquet files (Corona, Budweiser, Miller, Heineken), each ~20K rows
5. **Analyze (parallel)** — Spin up 4 worker processes, each runs:
   - **Baseline** (STL decomposition) — extract trend, seasonality, residual
   - **Deviations** (3-stage cascade) — z-scores → Matrix Profile → change points
6. **Collect** — Gather results into `batch_summary.json` + per-segment result JSONs

Key design choice: normalizing *before* segmenting means each segment has 4x more data (20K rows per brand vs 5K per raw product), producing much stronger statistical signals.

**Stage 5 — Report.** The Report Agent reads all segment results, generates matplotlib charts, computes cross-segment statistics, and writes a markdown report with executive summary, findings tables, store deep-dives, and chart gallery.

Final output for a single run:
```
reports/2026-02-26-c7ed12ea/
├── analysis_report.md              # Narrative report with embedded charts
├── analysis_report.pdf             # PDF export
├── charts/
│   ├── chart1_store01_revenue.png
│   ├── chart2_seasonal_pattern.png
│   └── chart3_temp_revenue_scatter.png
├── baselines/
│   └── {segment_id}/
│       ├── manifest.json
│       └── trend_coefficients.json
├── results/
│   ├── store-01.json               # Per-segment baseline + deviations
│   ├── store-02.json
│   └── ...
├── segments/
│   └── *.parquet                   # Segment data files
└── batch_summary.json              # Execution statistics
```


## Component Architecture

### TDV Profiler (`tdv_profiler/`)

Classifies every column in every file as **T**ime, **D**iscriminator, or **V**alue. This is the foundation — everything downstream depends on knowing which column is the timestamp, which columns you can segment by, and which columns contain the metrics you're analyzing.

**Classification heuristics:**

| Role | Detection Logic |
|------|----------------|
| Time | Datetime type or string parseable as datetime (>80% success). Integers only if in YYYYMMDD range. |
| Discriminator | String with cardinality ≤50 (always), or ratio <5% of rows. Integer only if cardinality <10. |
| Value | Float/double always. Integer if coefficient of variation >0.01 AND not a sequential ID. |
| Identifier | High cardinality (>50% of rows), non-temporal, non-value. |

Also detects temporal grain (hourly/daily/weekly/monthly) by computing the median interval between sorted timestamps.

Output is a NetworkX graph (`tdv_graph.json`) with four node types: `DATASET`, `DISCRIMINATOR`, `VALUE`, `VALUE_COLUMN`, connected by edges that represent containment and hierarchy.

### Entity Normalizer (`data_prep/entity_normalizer.py`)

Handles the reality that the same entity appears in data under many names. Three sub-components:

1. **TextNormalizer** — deterministic pipeline: lowercase → replace separators → extract pack info → expand abbreviations (`lt→light`, `pk→pack`) → collapse whitespace
2. **FuzzyClusterer** — groups similar normalized strings using `rapidfuzz.token_sort_ratio` (threshold: 80), picks the best canonical name per cluster (prefers title case, longer names, no underscores)
3. **HierarchyClassifier** — maps canonicals into a hierarchy. Two modes:
   - **Rules mode**: regex patterns → hierarchy levels (fast, deterministic, requires domain knowledge)
   - **LLM mode**: sends canonical names to Claude for classification (one API call during setup, not at query time)

Output is a `NormalizationGraph` (NetworkX) that can generate DuckDB lookup table SQL for downstream use.

### Plan Builder (`data_prep/plan_builder.py`)

Consumes the TDV graph and normalization graph to decide:
- Which datasets are relevant to the analysis goal
- How to join them (shared discriminators or ASOF joins for grain mismatches)
- How to segment (which hierarchy level produces segments large enough for analysis)
- What configuration the Batch Runner needs

Output: `manifest.yaml` — a declarative specification for the entire batch run.

### Batch Runner (`batch_runner/`)

The execution engine. Reads a manifest and orchestrates the full pipeline.

**Execution phases:**

| Phase | Process | Parallelism |
|-------|---------|-------------|
| 1. Load | Read data into DuckDB | Sequential |
| 2. Clean | Auto-detect and fix data quality issues | Sequential |
| 2.5. Normalize | LEFT JOIN lookup tables onto dataset | Sequential |
| 3. Segment | Split by discriminator, export Parquet | Sequential |
| 4. Analyze | Baseline + Deviations per segment | Parallel (ProcessPoolExecutor, spawn mode) |
| 5. Collect | Aggregate results, write summary | Sequential |

Phase 4 uses `ProcessPoolExecutor` with `spawn` context (not `fork`) to avoid DuckDB singleton conflicts. Each worker loads its segment's Parquet file independently.

**Manifest structure:**

```yaml
data_path: ../data/beer/all-beer.csv
dataset_name: all-beer
timestamp_col: created
freq: hourly
value_cols: [amount]

clean:
  auto_detect: true

normalization:
  enabled: true
  lookup_sql:
    product_name: "CREATE TABLE _norm_lookup_product_name AS SELECT ..."
  enrichment_columns: [product_name]
  hierarchy_levels: [product, brand, category, department]

deviations:
  lookback_window: 90d
  sensitivity: medium

scenarios:
  - name: by_brand
    segment_by: norm_product_name_brand
    min_segment_size: 50
```

### Layer 0 — Data Loader MCP (`mcp/layer0/`)

DuckDB-backed data loading, cleaning, profiling, and segmentation. Seven tools:

- `load_dataset` — read a file into DuckDB, auto-detect column roles
- `clean_dataset` — auto-detect issues (whitespace, duplicates, type mismatches) or apply fixes
- `suggest_segments` — score candidate segmentations by differentiation (Kruskal-Wallis), balance, coverage, and size
- `create_segments` — split by column(s), export as Parquet files
- `list_segments` — show unique values and counts for a column
- `export_segment` — export specific segments to files
- `resolve_entities` — LLM-assisted entity resolution for messy categorical columns

### Layer 1 — Signal Discovery MCP (`mcp/layer1/`)

Time-series analysis in three modes:

**Mode 1 — Baseline** (`discover_baseline`): STL/MSTL decomposition extracts trend, seasonality, and residual components. Saves artifacts (coefficients, patterns) for reuse.

**Mode 2 — Deviations** (`detect_deviations`): Compares recent data against the baseline using a three-stage cascade:
1. Statistical screening — rolling z-scores and IQR
2. Matrix Profile — contextual anomalies via `stumpy`
3. Change point detection — regime shifts via `ruptures`

Sensitivity thresholds: low (z>3.0), medium (z>2.5), high (z>2.0). Lookback windows: 7d, 30d, 90d.

**Mode 3 — Forecast** (`project_forecast`): Prophet-based forecasting with confidence intervals (80%, 95%) and scenario variants.

### Layer 2 — Signal Correlation MCP (`mcp/layer2/`)

Cross-source signal analysis. Takes Layer 1 outputs from multiple sources and finds relationships.

**Five correlation methods:**
1. Temporal co-occurrence — signals from different sources within N days of each other
2. Lagged correlation — Pearson correlation at lags 0 to max_lag
3. Spatial alignment — geographic proximity matching
4. Entity alignment — shared keys (customer_id, venue_id)
5. Pattern similarity — seasonal shape matching with DTW

Results are clustered (DBSCAN) into actionable insight groups with confidence assessment (weakest-link analysis).

### Query Planner MCP (`mcp/query-planner/`)

Graph-based dataset discovery and join planning. Loads the TDV graph and provides:
- Reverse value lookup — "Bud Light" → which datasets contain it
- Join path finding — how to connect two datasets (shared discriminators or hierarchy bridges)
- Plan building — generate a DataPlan with primary/supplementary datasets and join strategies
- Plan execution — load, filter, join (equi-join for same grain, ASOF for different grains), export

### Temporal-Aware Joins

When joining datasets with different temporal grains:

**Same grain** (both daily): equi-join on discriminator + date.

**Different grain** (POS hourly, marketing weekly): ASOF join — each POS row gets the most recent marketing value as of that date, preventing cartesian explosion.


## How the Pieces Connect

### MCP Server Configuration

All four servers are registered in `.mcp.json` and run as stdio processes via `uv`:

```json
{
  "mcpServers": {
    "data-loader":        { "command": "uv", "args": ["run", "--directory", "mcp/layer0", "data-loader"] },
    "signal-discovery":   { "command": "uv", "args": ["run", "--directory", "mcp/layer1", "signal-discovery"] },
    "signal-correlation": { "command": "uv", "args": ["run", "--directory", "mcp/layer2", "signal-correlation"] },
    "query-planner":      { "command": "uv", "args": ["run", "--directory", "mcp/query-planner", "query-planner"] }
  }
}
```

Each server is a `FastMCP` app using the MCP SDK. Tools are decorated functions that return JSON strings. The servers are stateless between calls except for Layer 2's signal store (`signal.duckdb`) and DuckDB's in-memory tables within a session.

### Two Execution Modes

The system can be driven two ways:

**1. Interactive (via Claude Code agents):**
A user describes an analysis goal in natural language. Claude Code orchestrates the pipeline through MCP tool calls — loading data, discovering baselines, detecting deviations, correlating signals. Three agent definitions in `.claude/agents/` handle this:

- **signal-discovery** (orchestrator) — executes the full pipeline: graph loading → dataset discovery → plan building → dispatches segment analysis → dispatches report generation
- **segment-analysis** — runs Layer 1 (baseline + deviations) on a single segment. One instance per segment, all concurrent.
- **report-agent** — reads all segment results, generates charts, writes the final markdown report

**2. Batch (via CLI):**
The `batch-runner` CLI reads a manifest and executes deterministically:
```bash
batch-runner manifest.yaml -o reports/ -w 4 --verbose
```

Both modes produce the same artifacts — the batch runner is the headless version of what the agents orchestrate interactively.

### Dependency Graph Between Packages

```
tdv_profiler (standalone)
     │
     ▼
data_prep (depends on tdv_profiler)
     │
     ▼
batch_runner (depends on data_prep, data-loader-mcp, signal-discovery-mcp)
```

MCP servers are independent packages. The batch runner imports their tool functions directly (not via MCP protocol) for in-process execution.


## Key Architectural Decisions

### DuckDB as primary storage
Single-process embedded SQL. No server to manage, fast aggregations, works entirely locally. Each batch runner invocation gets its own DuckDB instance; parallel workers use Parquet files to avoid singleton conflicts.

### Normalize before segment
Segmenting by raw entity names produces too many small segments. Normalizing first collapses variants into canonicals, then classifying into hierarchies gives a choice of granularity. Segmenting by `brand` instead of raw `product_name` means 4x more data per segment and much stronger statistical signals.

### Three-stage anomaly cascade
Each stage catches different anomaly types: z-scores catch point outliers, Matrix Profile catches contextual anomalies (unusual subsequences), change points catch regime shifts. Running all three with decreasing false-positive rates gives both coverage and precision.

### Graph-based data discovery
Instead of requiring users to know which files to join and how, the TDV graph captures column relationships across an entire data lake. The Query Planner traverses this graph to find relevant datasets and determine join keys automatically.

### Manifest-driven execution
YAML manifests are human-readable, version-controllable, and can be hand-edited. The data-prep pipeline generates them, the batch runner consumes them. This decouples planning from execution and makes runs reproducible.

### ProcessPoolExecutor with spawn
Python's `fork` context causes issues with DuckDB's process-level singleton. Using `spawn` creates clean interpreter processes per worker. The main process handles all DuckDB operations (load/clean/normalize/segment), then workers operate on exported Parquet files independently.

### MCP as the integration layer
Each analytical capability is an independent MCP server. This means they can be composed freely by Claude Code, deployed separately, or called directly from Python. The protocol boundary enforces clean interfaces — each tool takes JSON parameters and returns JSON results.


## Project Structure

```
circuit-signal/
├── .mcp.json                         # MCP server configuration
├── .claude/
│   └── agents/                       # Agent definitions (signal-discovery, segment-analysis, report-agent)
├── tdv_profiler/                     # TDV column classification (standalone package)
│   └── src/tdv_profiler/
│       ├── profiler.py               # Core classification engine
│       └── cli.py                    # tdv-profiler command
├── data_prep/                        # Entity normalization + plan building
│   └── src/data_prep/
│       ├── entity_normalizer.py      # Fuzzy clustering + hierarchy classification
│       ├── plan_builder.py           # DataPlan generation
│       ├── pipeline.py               # Orchestrates stages 1-3
│       └── graph_store.py            # Graph serialization
├── batch_runner/                     # Batch execution engine
│   └── src/batch_runner/
│       ├── cli.py                    # batch-runner command
│       ├── manifest.py               # YAML manifest parsing
│       ├── runner.py                 # Orchestration (load → clean → normalize → segment → parallel)
│       └── parallel.py               # ProcessPoolExecutor for Layer 1
├── mcp/
│   ├── layer0/                       # Data Loader MCP server
│   ├── layer1/                       # Signal Discovery MCP server
│   ├── layer2/                       # Signal Correlation MCP server
│   └── query-planner/                # Query Planner MCP server
├── data/                             # Sample datasets
├── output/                           # Persistent artifacts (graphs, manifests)
├── reports/                          # Analysis outputs (per-run directories)
└── templates/                        # Report HTML/CSS templates
```

All packages use `hatchling` for builds, `src/` layout, and `uv` for dependency management. Local dependencies are wired via `[tool.uv.sources]` path references.


## What the Output Looks Like

A completed analysis run produces a report like this (from the beer dataset):

> **Miller Beer Sales vs Weather Analysis — Tennessee & Georgia Stores**
>
> Temperature is a statistically significant driver of Miller beer sales in 4 of 6 stores. Hot days (≥85°F) generate 47-100% more Miller revenue than cold days (<45°F). Weekend effects are consistent across all stores (1.1x–1.8x weekday). Store 04 has a 5.6x seasonal swing (July peak vs March trough).

The report includes correlation tables, seasonal pattern charts, temperature scatter plots, and store-by-store deep-dives — all generated automatically from the segment analysis results.
