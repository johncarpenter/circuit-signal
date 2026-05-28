# Data Preparation Pipeline — Implementation Spec

## Overview

Build a unified data preparation pipeline that integrates three modules into a single orchestrated flow. The pipeline transforms raw, messy data lake files into analysis-ready segments for the existing Layer 1/2 signal discovery system.

### The Problem

Without preparation, the batch_runner produces too many fragmented segments from messy data:
- `"corona_lt"`, `"Corona Light"`, `"CORONA LT 12PK"` each become separate segments
- 16 raw product names → 16 parallel workers, each with weak statistics
- Layer 2 correlation across fragments is meaningless

### The Solution

Run normalization BEFORE segmentation:
- 16 messy names → 5 canonical entities → 4 brands
- 4 parallel workers, each with 4x the data
- 75% reduction in compute, dramatically better statistical significance

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 1: PROFILE  (run once per data lake change)              │
│                                                                 │
│  TDV Profiler scans all datasets:                               │
│    → Classifies columns as Time / Discriminator / Value         │
│    → Discovers hierarchies via functional dependencies           │
│    → Identifies shared discriminators across datasets            │
│    → Routes: temporal datasets → pipeline, others → Vanna/SQL   │
│    → Outputs: tdv_graph.json                                    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 2: NORMALIZE  (run once per data lake change)            │
│                                                                 │
│  For each discriminator column identified by Stage 1:           │
│    → Extract distinct values from actual data (DuckDB)          │
│    → Fuzzy cluster similar values (rapidfuzz, token_sort_ratio) │
│    → Classify clusters into hierarchy (rules or LLM)            │
│    → Build DuckDB lookup tables for runtime JOIN                │
│    → Outputs: norm_graph.json                                   │
│                                                                 │
│  16 messy product names → 5 canonical → 4 brands → 2 categories│
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 3: PLAN  (run per analysis request)                      │
│                                                                 │
│  Load tdv_graph.json + norm_graph.json:                         │
│    → Select relevant datasets via graph traversal               │
│    → Determine join paths (shared discriminators)               │
│    → Choose segmentation level based on analytical goal          │
│    → Generate enhanced Manifest for batch_runner                 │
│    → Outputs: manifest.json (batch_runner compatible)            │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 4: EXECUTE  (batch_runner, modified)                     │
│                                                                 │
│  Sequential (DuckDB, main process):                             │
│    → Load datasets per plan                                     │
│    → Apply normalization lookup (LEFT JOIN on raw values)        │
│    → Execute temporal-aware joins (ASOF for grain mismatches)    │
│    → Segment unified table by normalized discriminator           │
│                                                                 │
│  Parallel (ProcessPoolExecutor):                                │
│    → Dispatch Layer 1 per segment (baseline + deviations)       │
│    → Collect results                                            │
│                                                                 │
│  KEY: Normalization is a DuckDB JOIN in the sequential phase.   │
│  It runs BEFORE segmentation, so parallel dispatch operates     │
│  on fewer, richer segments.                                     │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 5: ANALYZE  (existing Layer 1 + 2, UNCHANGED)            │
│                                                                 │
│  Layer 1: Per-segment signal discovery                          │
│  Layer 2: Cross-segment correlation                             │
│  Report generation                                              │
└─────────────────────────────────────────────────────────────────┘
```

### Existing Code Integration Points

The existing batch_runner flow is:

```
load → clean → segment → dispatch (parallel) → collect
```

The new flow inserts a normalization step:

```
load → clean → NORMALIZE → segment → dispatch (parallel) → collect
```

The `NORMALIZE` step is a DuckDB LEFT JOIN injected between the existing `clean` and `segment` phases in `runner.py`. The existing `data_loader.tools.load`, `data_loader.tools.clean`, `data_loader.tools.batch_create`, and `batch_runner.parallel` modules are NOT modified.

### File Structure

```
project/
├── data_prep/                       # NEW PACKAGE
│   ├── __init__.py
│   ├── tdv_profiler.py              # Stage 1: TDV classification + discriminator graph
│   ├── entity_normalizer.py         # Stage 2: Fuzzy clustering + hierarchy classification
│   ├── plan_builder.py              # Stage 3: Graph-aware execution planning
│   ├── graph_store.py               # Serialization/deserialization of graph artifacts
│   └── pipeline.py                  # Orchestrates Stages 1-3, generates manifest
│
├── batch_runner/                    # EXISTING — minor modifications
│   ├── manifest.py                  # Add normalization config to Manifest (MODIFY)
│   ├── parallel.py                  # UNCHANGED
│   └── runner.py                    # Add normalization step between clean and segment (MODIFY)
│
├── data_loader/                     # EXISTING — UNCHANGED
│   ├── storage.py
│   └── tools/
│       ├── load.py
│       ├── clean.py
│       └── batch_create.py
│
└── configs/
    └── normalization_rules/         # Per-domain classification rules
        └── retail_products.json
```

---

## Module Specifications

### Module 1: `data_prep/tdv_profiler.py`

**Purpose:** Scan a data lake directory, classify every column in every dataset as Time/Discriminator/Value, build a graph of relationships between datasets.

**Dependencies:** `duckdb`, `networkx`

#### Class: `TDVProfiler`

Scans a single dataset and classifies each column.

**Classification heuristics (these are tunable — see Edge Cases section):**

| Role | Detection Logic |
|------|----------------|
| **Time** | Datetime types detected directly. Strings tested via `pandas.to_datetime()` with >80% success threshold. Integers only if in YYYYMMDD range (19000101-20991231). |
| **Discriminator** | String/varchar columns with absolute cardinality ≤ 50 are always discriminators (handles small datasets). For larger cardinalities, ratio < 5% of total rows. Integer columns only if cardinality < 10. |
| **Value** | Float/double types are always values (never identifiers). Integer values require coefficient of variation > 0.01 and must not correlate with row number (r > 0.9 indicates sequential ID). |
| **Identifier** | High-cardinality (> 50% of rows) non-temporal, non-value columns. |

**Temporal grain detection:** Compute median interval between consecutive sorted timestamps. Classify as: hourly (<3600s), daily (<86400s), weekly (<604800s), monthly (<2592000s).

**Methods:**
```python
def profile_dataset(self, source_path: str, dataset_id: str = None) -> DatasetProfile
```

#### Class: `DiscriminatorGraph`

A directed NetworkX graph with four node types and four edge types.

**Node types:**
- `DATASET` — a physical dataset. Attributes: source_path, row_count, is_temporal, tdv_signature, primary_time_col, time_grain
- `DISCRIMINATOR` — a column name that appears as a discriminator. Attributes: column_name, datasets (list of dataset IDs containing this column)
- `VALUE` — a specific discriminator value. Attributes: discriminator (column name), value
- `VALUE_COLUMN` — a measurable signal column. Attributes: column_name, stats

**Edge types:**
- `DATASET_HAS_DISCRIMINATOR` — dataset → discriminator column
- `DISCRIMINATOR_HAS_VALUE` — discriminator → specific value
- `CHILD_OF` — value → parent value (hierarchy). Discovered via functional dependency: if `COUNT(DISTINCT a, b) == COUNT(DISTINCT a)` and `COUNT(DISTINCT a) > COUNT(DISTINCT b)`, then `a` is a child of `b` (e.g., SKU → Brand)
- `DATASET_HAS_VALUE_COL` — dataset → value column

**Key methods:**
```python
def add_dataset(self, profile: DatasetProfile, db: duckdb.DuckDBPyConnection)
    """Add a profiled dataset. Automatically discovers co-occurrence and hierarchies."""

def find_datasets_for_value(self, value: str, discriminator_col: str = None) -> list[dict]
    """Reverse lookup: 'Bud Light' → which datasets contain it (direct or via hierarchy)."""

def find_join_path(self, dataset_a_id: str, dataset_b_id: str) -> dict | None
    """How can two datasets be joined? Returns shared discriminators or hierarchy bridge."""

def find_related_datasets(self, dataset_id: str) -> list[dict]
    """All datasets sharing discriminators with this one."""

def get_summary(self) -> dict
    """Graph summary for LLM context or logging."""
```

#### Class: `DataLakeScanner`

Orchestrates scanning of an entire directory. Iterates over `.csv` and `.parquet` files, profiles each, adds to the graph.

```python
def scan_directory(self, directory: str, recursive: bool = True) -> dict
    """Scan all supported files. Returns scan summary with counts."""
```

---

### Module 2: `data_prep/entity_normalizer.py`

**Purpose:** Normalize messy discriminator values into canonical entities and classify them into a hierarchy.

**Dependencies:** `rapidfuzz`, `networkx`

#### Class: `TextNormalizer`

Static methods for text normalization before fuzzy matching.

**Normalization steps (in order):**
1. Lowercase
2. Replace separators (`_`, `-`, `/`) with spaces
3. Extract pack info (e.g., "12pk", "24oz") into separate field
4. Remove standalone numbers
5. Expand abbreviations: `lt` → `light`, `pk` → `pack`, `cn` → `can`, etc.
6. Collapse whitespace

```python
@staticmethod
def normalize(text: str) -> dict
    """Returns {'original', 'normalized', 'pack_info', 'tokens'}"""
```

#### Class: `FuzzyClusterer`

Groups normalized values using `rapidfuzz.fuzz.token_sort_ratio`.

**Algorithm:**
1. Normalize all values
2. Group exact normalized matches (cheap dedup)
3. Pairwise fuzzy match between group representatives
4. Merge groups scoring above threshold (default: 80)
5. Pick best canonical name per cluster (prefer title case, longer names, no underscores)

```python
def cluster(self, values: list[str]) -> list[dict]
    """Returns [{'canonical': str, 'members': [...], 'confidence': float}]"""
```

**Important threshold tuning:** At threshold 75, "bud light" and "bud light lime" merge (they share 2/3 tokens). At 80, they stay separate. Start at 80 for retail product data. Allow per-column override in config.

#### Class: `HierarchyClassifier`

Two classification modes:

**Rules mode** — regex patterns map to hierarchy positions:
```python
rules = {
    'patterns': [
        {'match': r'corona.*(?:light|lt)', 'brand': 'Corona',
         'subcategory': 'Light Beer', 'category': 'Beer', 'department': 'Beverages'},
    ],
    'default': {'brand': 'Unknown', ...}
}
```

**LLM mode** — builds a prompt with the canonical entities (post-clustering, so typically <50 entities instead of hundreds of raw values), sends to LLM for structured JSON classification. Parse response. Fall back to rules mode if LLM fails.

```python
def classify_with_rules(self, entities: list[str], rules: dict) -> list[dict]
def build_llm_prompt(self, entities: list[str], context: str, existing_hierarchy: dict = None) -> str
def parse_llm_response(self, response_text: str) -> list[dict]
```

**Hierarchy levels** are configurable. Default for retail: `['product', 'brand', 'subcategory', 'category', 'department']`

#### Class: `NormalizationGraph`

Stores the complete normalization mapping as a NetworkX graph.

**Graph structure:**
```
RAW_VALUE ──(NORMALIZES_TO)──► CANONICAL ──(BELONGS_TO)──► BRAND ──(BELONGS_TO)──► CATEGORY ──► DEPARTMENT
```

**Key methods:**
```python
def normalize(self, raw_value: str) -> str | None
    """Lookup canonical form of a raw value."""

def get_hierarchy(self, raw_value: str) -> dict | None
    """Full hierarchy: {'product': 'Corona Light', 'brand': 'Corona', 'category': 'Beer', ...}"""

def build_duckdb_lookup(self) -> str
    """Generate CREATE TABLE SQL for the normalization lookup table."""

def get_all_at_level(self, level: str) -> list[str]
    """All distinct values at a hierarchy level (e.g., all brands)."""
```

#### Class: `EntityNormalizationPipeline`

End-to-end: raw values → cluster → classify → graph.

```python
def run(self, raw_values: list[str], classification_mode: str = "rules",
        rules: dict = None, llm_classify_fn = None) -> NormalizationGraph
```

---

### Module 3: `data_prep/graph_store.py`

**Purpose:** Serialize/deserialize the TDV graph and normalization graph to JSON files.

```python
class GraphStore:
    @staticmethod
    def save_tdv(scanner: DataLakeScanner, output_path: str)
    
    @staticmethod
    def load_tdv(input_path: str) -> tuple[DiscriminatorGraph, dict]
    
    @staticmethod
    def save_norm(norm_graphs: dict[str, NormalizationGraph], output_path: str)
        """Save per-column normalization graphs. Key = column name."""
    
    @staticmethod
    def load_norm(input_path: str) -> dict[str, NormalizationGraph]
```

Uses `networkx.readwrite.json_graph.node_link_data` for graph serialization.

---

### Module 4: `data_prep/plan_builder.py`

**Purpose:** Given both graphs and an analytical goal, produce an execution plan that the batch_runner can consume.

#### Class: `PlanBuilder`

```python
def __init__(self, tdv_graph: DiscriminatorGraph, tdv_profiles: dict,
             norm_graphs: dict[str, NormalizationGraph])

def build_plan_for_value(self, target_value: str, target_disc: str = None) -> DataPlan
    """'Bud Light' → finds POS + marketing + weather, builds joins and normalization."""

def build_plan_for_datasets(self, dataset_ids: list[str]) -> DataPlan
    """Explicit dataset selection. Auto-discovers join paths."""

def estimate_segments(self, dataset_id: str) -> dict
    """Returns {level: count} for each hierarchy level. Helps choose segmentation granularity."""
```

#### Class: `DataPlan`

```python
@dataclass
class DataPlan:
    primary_dataset: dict          # {dataset_id, source_path, time_col, discriminators, values, time_grain}
    supplementary_datasets: list   # [{dataset_id, source_path, time_col, join_key, time_grain, values}]
    normalization_sql: dict        # {column_name: CREATE TABLE SQL for lookup}
    enrichment_sql: str            # JOIN lookup onto main dataset
    filters: list                  # [{column, operator, value}]
    segment_by: str                # hierarchy level to segment on
    segment_estimates: dict        # {brand: 4, category: 2, ...}
    execution_config: dict         # {max_workers, freq, lookback_window, sensitivity, min_segment_size}
```

---

### Module 5: `data_prep/pipeline.py`

**Purpose:** Orchestrate Stages 1-3 and produce a manifest for the batch_runner.

#### Class: `PreparationPipeline`

```python
def __init__(self, config: PipelineConfig)

def run_stage1_profile(self) -> dict
    """Scan data lake → tdv_graph.json. Skip if exists and force_reprofile=False."""

def run_stage2_normalize(self, target_datasets: list[str] = None) -> dict
    """For each discriminator in target datasets, run normalization → norm_graph.json."""

def run_stage3_plan(self, target_datasets: list[str] = None, segment_by: str = None) -> DataPlan
    """Load both graphs, build execution plan."""

def generate_manifest(self, plan: DataPlan) -> Manifest
    """Convert DataPlan to batch_runner Manifest with normalization step injected."""
```

#### Dataclass: `PipelineConfig`

```python
@dataclass
class PipelineConfig:
    # Data lake
    data_lake_dir: str
    tdv_graph_path: str = "tdv_graph.json"
    norm_graph_path: str = "norm_graph.json"
    
    # Profiling
    force_reprofile: bool = False
    profiler_overrides: dict = field(default_factory=dict)  # {"dataset_id": {"col": "discriminator"}}
    
    # Normalization
    normalize_columns: list = field(default_factory=list)  # auto-detected if empty
    normalization_mode: str = "rules"  # or "llm"
    normalization_rules: dict = field(default_factory=dict)
    fuzzy_threshold: int = 80
    hierarchy_levels: list = field(default_factory=lambda: ["product", "brand", "subcategory", "category", "department"])
    
    # Execution
    segment_by: str = "brand"
    timestamp_col: str = None       # auto-detected from TDV
    value_cols: list = field(default_factory=list)  # auto-detected from TDV
    max_workers: int = 4
    freq: str = "D"
    lookback_window: int = 30
    sensitivity: float = 2.0
    min_segment_size: int = 30
```

---

### Modification 1: `batch_runner/manifest.py`

Add normalization config to the Manifest dataclass:

```python
@dataclass
class NormalizationConfig:
    enabled: bool = False
    lookup_sql: dict[str, str] = field(default_factory=dict)  # {column: CREATE TABLE sql}
    enrichment_columns: list[str] = field(default_factory=list)  # which raw columns to normalize
    hierarchy_levels: list[str] = field(default_factory=list)  # added columns after normalization
```

Add `normalization: NormalizationConfig` field to the existing `Manifest` dataclass.

---

### Modification 2: `batch_runner/runner.py`

Insert a normalization phase between the existing clean and segment phases.

**Add this function:**

```python
def _apply_normalization(manifest: Manifest) -> None:
    """
    Phase 2.5: Apply entity normalization.
    
    Runs AFTER cleaning, BEFORE segmentation.
    Creates lookup tables in DuckDB and JOINs them onto the main dataset,
    adding hierarchy columns (brand, category, department, etc.).
    """
    if not manifest.normalization or not manifest.normalization.enabled:
        return
    
    import data_loader.storage as storage
    db = storage._backend._conn
    
    for col_name, lookup_sql in manifest.normalization.lookup_sql.items():
        # Create the lookup table
        logger.info("Creating normalization lookup for column: %s", col_name)
        db.execute(lookup_sql)
        
        # Count the lookup entries
        count = db.execute("SELECT COUNT(*) FROM _normalization_lookup").fetchone()[0]
        logger.info("  Lookup table: %d entries", count)
        
        # Join onto the main dataset, adding hierarchy columns
        # Use a prefixed table name to avoid collision if normalizing multiple columns
        dataset_table = manifest.dataset_name
        hierarchy_cols = manifest.normalization.hierarchy_levels
        
        select_cols = ", ".join([
            f'COALESCE(n."{level}", \'Unknown\') AS "norm_{col_name}_{level}"'
            for level in hierarchy_cols
        ])
        
        db.execute(f"""
            CREATE OR REPLACE TABLE {dataset_table} AS
            SELECT d.*, {select_cols}
            FROM {dataset_table} d
            LEFT JOIN _normalization_lookup n
                ON CAST(d."{col_name}" AS VARCHAR) = n.raw_value
        """)
        
        new_count = db.execute(f"SELECT COUNT(*) FROM {dataset_table}").fetchone()[0]
        logger.info("  Enriched %s: %d rows, added columns: %s",
                     dataset_table, new_count,
                     [f"norm_{col_name}_{l}" for l in hierarchy_cols])
        
        # Clean up lookup table for next column
        db.execute("DROP TABLE IF EXISTS _normalization_lookup")
```

**Modify `run_batch()` to call it:**

In the existing `run_batch()` function, insert the call between Phase 2 (clean) and Phase 3 (segment):

```python
    # ── Phase 2: Clean (existing) ──────────────────────
    # ... existing clean code ...

    # ── Phase 2.5: Normalize (NEW) ─────────────────────
    _apply_normalization(manifest)

    # ── Phase 3: Segment (existing) ────────────────────
    # ... existing segment code ...
```

No other changes to runner.py. The segment phase will now see the added `norm_*` columns and can segment by them.

---

## Temporal-Aware Joins

When fusing multiple datasets with different time grains, use DuckDB ASOF joins to prevent cartesian explosions.

**The problem:** POS is daily per store per SKU. Marketing is weekly per brand. A naive JOIN on `brand` produces `365 × 52 = 18,980` rows per brand instead of 365.

**The solution:** ASOF JOIN matches each primary row to the most recent supplementary row where `supplementary.time <= primary.time`.

```sql
-- Same grain: equi-join on discriminator + date
SELECT p.*, s.* EXCLUDE (join_key)
FROM primary_table p
LEFT JOIN supplementary_table s
ON p."region" = s."region"
AND CAST(p."date" AS DATE) = CAST(s."date" AS DATE)

-- Different grain: ASOF join (prevents cartesian explosion)
SELECT p.*, s.tv_spend, s.digital_spend
FROM primary_table p
ASOF LEFT JOIN (
    SELECT * FROM marketing_spend ORDER BY week_start
) s
ON p."brand" = s."brand"
AND CAST(p."date" AS DATE) >= CAST(s."week_start" AS DATE)
```

The grain for each dataset is stored in the TDV graph (detected during profiling). The plan builder reads both grains and chooses the join strategy automatically.

---

## Edge Cases and Heuristic Tuning

These are known issues discovered during development. Address them in the implementation.

### TDV Profiler

| Issue | Cause | Fix |
|-------|-------|-----|
| `pack_size` (int values like 12, 24) classified as Time | Integer date heuristic too broad | Restrict to YYYYMMDD range specifically (19000101-20991231). Small ints should never match. |
| `units_sold` (Poisson-distributed integers) classified as Discriminator | Low cardinality ratio on small datasets | Integer columns need cardinality < 10 AND ratio < 1% to be discriminators. |
| `tv_spend` (float with near-unique values) classified as Identifier | High cardinality ratio | Float/double types should ALWAYS be classified as Value, never Identifier. Floats are measurements. |
| `brand` in small dataset (3 values in 39 rows = 7.7%) missed as Discriminator | Cardinality ratio exceeds 5% threshold | String columns with absolute cardinality ≤ 50 should always be discriminators regardless of ratio. |
| `product_master` (reference table) classified as temporal | Some column passed date heuristic | Non-temporal reference tables have no time column correlating with values. Add a check: Time column must have more than N distinct values (e.g., > 10 dates). |

### Entity Normalizer

| Issue | Cause | Fix |
|-------|-------|-----|
| "Bud Light" and "Bud Light Lime" merge into one cluster | token_sort_ratio gives ~85% (2/3 tokens match) | Raise threshold to 80+. Consider adding a "distinctive token" check: if removing a token changes meaning, keep clusters separate. |
| "Coca-Cola" and "Coca-Cola Zero" merge | Same token overlap issue | Same fix. LLM mode handles this correctly since it understands product semantics. |
| Store names normalize but shouldn't be classified into product hierarchy | Pipeline normalizes all discriminators | Add a `skip_columns` config option. Or: detect that store names don't match any classification rule and skip hierarchy classification for that column. |
| Canonical name picks "BUD LIGHT 24PK" over "Bud Light" | Scoring heuristic prefers longer names | Penalize all-caps more heavily. Prefer names without pack info in the canonical. |

### Batch Runner Integration

| Issue | Cause | Fix |
|-------|-------|-----|
| Manifest scenario `segment_by: "brand"` fails because column doesn't exist | Normalization adds `norm_product_name_brand`, not `brand` | The manifest must use the prefixed column name, or the normalization step should use unprefixed names when there's no collision. |
| Multiple normalization columns create multiple `_normalization_lookup` tables | Each column needs its own lookup | Drop and recreate the lookup table per column, or use per-column table names (`_norm_lookup_{column}`). |

---

## Configuration Examples

### Retail Products (Rules Mode)

```json
{
  "data_lake_dir": "/data/lake",
  "normalization_mode": "rules",
  "fuzzy_threshold": 80,
  "normalization_rules": {
    "patterns": [
      {"match": "corona.*(?:light|lt)", "brand": "Corona", "subcategory": "Light Beer", "category": "Beer", "department": "Beverages"},
      {"match": "corona.*extra", "brand": "Corona", "subcategory": "Lager", "category": "Beer", "department": "Beverages"},
      {"match": "corona", "brand": "Corona", "subcategory": "Lager", "category": "Beer", "department": "Beverages"},
      {"match": "bud.*(?:light|lt).*lime", "brand": "Budweiser", "subcategory": "Flavored Beer", "category": "Beer", "department": "Beverages"},
      {"match": "bud.*(?:light|lt)", "brand": "Budweiser", "subcategory": "Light Beer", "category": "Beer", "department": "Beverages"},
      {"match": "miller.*(?:lite|light|lt)", "brand": "Miller", "subcategory": "Light Beer", "category": "Beer", "department": "Beverages"},
      {"match": "tide", "brand": "Tide", "subcategory": "Laundry Detergent", "category": "Laundry", "department": "Household"},
      {"match": "coca.*cola.*zero", "brand": "Coca-Cola", "subcategory": "Diet Soda", "category": "Soft Drinks", "department": "Beverages"},
      {"match": "coca.*cola", "brand": "Coca-Cola", "subcategory": "Regular Soda", "category": "Soft Drinks", "department": "Beverages"}
    ],
    "default": {"brand": "Unknown", "subcategory": "Unknown", "category": "Unknown", "department": "Unknown"}
  },
  "segment_by": "brand",
  "max_workers": 4
}
```

### LLM Mode

```json
{
  "data_lake_dir": "/data/lake",
  "normalization_mode": "llm",
  "fuzzy_threshold": 80,
  "segment_by": "category"
}
```

In LLM mode, the pipeline:
1. Clusters raw values (reduces volume by ~70%)
2. Sends only canonical entities to the LLM (typically <50 entities)
3. LLM returns structured JSON with hierarchy classification
4. Cost is minimal: one LLM call during setup, not at query time

The LLM prompt includes any existing hierarchy (from previous runs) so new entities get placed consistently.

---

## Testing Strategy

### Unit Tests

```
tests/
├── test_tdv_profiler.py
│   ├── test_time_detection (datetime, string dates, YYYYMMDD ints, pack_size rejection)
│   ├── test_discriminator_detection (string, low-card int, small datasets, boolean)
│   ├── test_value_detection (float always value, int with variance, sequential ID rejection)
│   ├── test_hierarchy_discovery (SKU→Brand→Category functional dependency)
│   └── test_graph_queries (find_datasets_for_value, find_join_path, traversal)
│
├── test_entity_normalizer.py
│   ├── test_text_normalization (abbreviations, pack extraction, separators)
│   ├── test_fuzzy_clustering (exact match, near match, threshold boundary)
│   ├── test_hierarchy_classification (rules mode, LLM prompt generation, response parsing)
│   └── test_normalization_graph (lookup, hierarchy traversal, DuckDB SQL generation)
│
├── test_plan_builder.py
│   ├── test_plan_for_value (single dataset, multi-dataset with joins)
│   ├── test_plan_for_datasets (direct join, hierarchical join, no join)
│   └── test_segment_estimation (counts at each hierarchy level)
│
├── test_pipeline_integration.py
│   ├── test_full_pipeline (stages 1-3 end to end)
│   ├── test_manifest_generation (valid manifest with normalization config)
│   └── test_segment_reduction (16 raw → 4 brands, verify row counts)
│
└── test_runner_normalization.py
    ├── test_normalization_injection (lookup table created, JOIN executed)
    ├── test_normalized_segmentation (segments use hierarchy columns)
    └── test_backward_compatibility (normalization disabled = existing behavior)
```

### Integration Test

Create a synthetic dataset with known messy values. Run the full pipeline. Assert:

1. TDV profiler correctly classifies all columns
2. Normalizer reduces 16 product names to 5 canonicals to 4 brands
3. Plan builder chooses correct join paths
4. Batch runner produces 4 segments (not 16)
5. Each segment has ~4x the rows compared to un-normalized run
6. Layer 1 results have tighter confidence intervals (more data per segment)

---

## Dependencies

```
duckdb>=1.0
networkx>=3.0
rapidfuzz>=3.0
pandas>=2.0
numpy>=1.24
```

`rapidfuzz` is strongly preferred over `fuzzywuzzy` — it's 10-100x faster (C++ implementation) and has no GPL dependency on python-Levenshtein.

---

## Artifacts Produced

| Artifact | Created By | Consumed By | Lifecycle |
|----------|-----------|-------------|-----------|
| `tdv_graph.json` | Stage 1 (TDV Profiler) | Stages 2, 3 | Regenerate when data lake structure changes |
| `norm_graph.json` | Stage 2 (Entity Normalizer) | Stage 3 | Regenerate when discriminator values change significantly |
| `manifest.json` | Stage 3 (Plan Builder) | Stage 4 (Batch Runner) | Generated per analysis request |
| `batch_summary.json` | Stage 4 (Batch Runner) | Reporting / Layer 2 | Generated per execution |
| Segment Parquet files | Stage 4 (Batch Runner) | Layer 1 parallel workers | Transient, per execution |
| Per-segment result JSONs | Stage 4 (Batch Runner) | Report agent / Layer 2 | Persistent, per execution |
