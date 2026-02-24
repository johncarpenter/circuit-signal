# Signal Correlation MCP Server (Layer 2) — Architecture Specification

## Overview

An MCP server that correlates signals discovered by Layer 1 instances across
multiple datasets. Given deviation outputs from multiple signal-discovery
sources, Layer 2 finds temporal, spatial, and entity-level alignments that
surface cross-domain commercial insights no single dataset can reveal.

Layer 1 answers: "What's happening in this dataset?"
Layer 2 answers: "What's happening across the business?"

## Design Philosophy

- **Multi-source by default**: Every analysis involves 2+ registered data sources
- **Signal-level, not row-level**: Layer 2 operates on the typed signal outputs from Layer 1 (deviations, baselines), never on raw data
- **Graph-native**: Correlations form a graph — nodes are signals, edges are relationships. Multi-hop insight paths are first-class
- **Actionable clustering**: Raw correlations are grouped into narrative "insight clusters" with actionability scoring
- **Persistent signal store**: All signals and correlations are stored in DuckDB for fast analytical queries across sessions

## System Context

```
┌─────────────────────────────────────────────────────────┐
│                     Claude Code                          │
│                (Orchestrator Agent)                       │
│                                                          │
│  Workflow:                                               │
│  1. Run Layer 1 on each dataset → get baselines/devs    │
│  2. Register each source with Layer 2                    │
│  3. Ingest Layer 1 signals into Layer 2                  │
│  4. Run correlation analysis                             │
│  5. Query insights                                       │
└──────────┬──────────────────────────────────────────────┘
           │ MCP Protocol (stdio)
┌──────────▼──────────────────────────────────────────────┐
│         Signal Correlation MCP Server (Layer 2)          │
│                                                          │
│  ┌────────────┐ ┌───────────┐ ┌────────────────────────┐│
│  │  Tool:     │ │ Tool:     │ │ Tool:                  ││
│  │  register  │ │ ingest    │ │ correlate              ││
│  │  _source   │ │ _signals  │ │ _signals               ││
│  └────────────┘ └───────────┘ └────────────────────────┘│
│  ┌────────────┐ ┌───────────┐ ┌────────────────────────┐│
│  │  Tool:     │ │ Tool:     │ │ Tool:                  ││
│  │  query     │ │ explain   │ │ list                   ││
│  │ _insights  │ │ _insight  │ │ _sources               ││
│  └────────────┘ └───────────┘ └────────────────────────┘│
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │              Correlation Engine                     │  │
│  │                                                    │  │
│  │  ┌─────────────┐  ┌──────────────────────────┐    │  │
│  │  │ Temporal     │  │ Spatial Alignment         │    │  │
│  │  │ Alignment    │  │ (geo-fence matching,      │    │  │
│  │  │ (co-occur,   │  │  configurable radius)     │    │  │
│  │  │  lagged xcor,│  └──────────────────────────┘    │  │
│  │  │  granger)    │                                  │  │
│  │  └─────────────┘  ┌──────────────────────────┐    │  │
│  │  ┌─────────────┐  │ Clustering / Story        │    │  │
│  │  │ Entity      │  │ Detection (DBSCAN on      │    │  │
│  │  │ Alignment   │  │ signal feature vectors    │    │  │
│  │  │ (shared key │  │ → insight clusters)       │    │  │
│  │  │  matching)  │  │                           │    │  │
│  │  └─────────────┘  └──────────────────────────┘    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │         Signal Store (DuckDB)                      │  │
│  │                                                    │  │
│  │  sources     — registered data sources + metadata  │  │
│  │  signals     — all ingested Layer 1 signals        │  │
│  │  correlations— discovered pairwise relationships   │  │
│  │  insights    — clustered multi-signal narratives   │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
       ▲                ▲                ▲
       │                │                │
  Layer 1 (A)      Layer 1 (B)      Layer 1 (C)
  Restaurant POS   Experience       Digital/search
  signals          booking signals  signals
```

## MCP Tools

### Tool 1: `register_source`

**Purpose**: Register a data source and describe what it represents semantically.
This context is critical for making correlations meaningful.

**Input Schema**:
```json
{
  "source_id": "string — unique identifier (e.g. 'edinburgh_pos', 'jwps_bookings')",
  "name": "string — human-readable name",
  "description": "string — what this data source represents",
  "domain": "string — 'pos' | 'bookings' | 'web_analytics' | 'social' | 'weather' | 'events' | 'retail' | 'crm' | 'other'",
  "geography": {
    "region": "string | null — e.g. 'Edinburgh', 'Scotland', 'UK'",
    "latitude": "float | null",
    "longitude": "float | null",
    "radius_km": "float | null — coverage radius"
  },
  "entity_keys": "string[] | null — shared identifier columns (e.g. ['customer_id', 'venue_id', 'product_sku'])",
  "baseline_path": "string | null — path to Layer 1 baseline artifacts for this source",
  "tags": "string[] | null — freeform tags for filtering (e.g. ['whisky', 'premium', 'scotland'])"
}
```

**Output Schema**:
```json
{
  "source_id": "string",
  "status": "registered | updated",
  "total_sources": "int — total registered sources"
}
```

---

### Tool 2: `ingest_signals`

**Purpose**: Ingest Layer 1 Mode 2 deviation outputs (or Mode 1 baseline summaries)
into the correlation store. Can accept direct JSON or a file path to Layer 1 output.

**Input Schema**:
```json
{
  "source_id": "string — must match a registered source",
  "signal_type": "string — 'deviations' | 'baseline'",
  "data": "object | null — direct Layer 1 output JSON (Mode 2 deviations or Mode 1 baselines)",
  "data_path": "string | null — path to Layer 1 output JSON file (alternative to data)",
  "context": {
    "analysis_timestamp": "ISO datetime | null",
    "data_window": {"start": "ISO | null", "end": "ISO | null"}
  }
}
```

**Processing**:
1. Validate source_id exists in registry
2. Parse signals from Layer 1 output format
3. Normalize each signal into the canonical signal schema:
   - `signal_id`: generated UUID
   - `source_id`: which data source
   - `column`: metric name from Layer 1
   - `signal_type`: `point_anomaly | trend_shift | seasonal_anomaly | regime_change | baseline_pattern`
   - `severity`: `low | medium | high | critical`
   - `ts_start`, `ts_end`: temporal bounds
   - `magnitude`: numeric deviation magnitude
   - `direction`: `increase | decrease | shift`
   - `confidence`: 0-1
   - `lat`, `lon`: from registered source geography (if available)
   - `entity_values`: dict of entity key values (if available)
   - `metadata`: original Layer 1 details preserved
4. Insert into DuckDB signals table
5. Return ingestion summary

**Output Schema**:
```json
{
  "source_id": "string",
  "signals_ingested": "int",
  "by_type": {"point_anomaly": 0, "trend_shift": 0, "regime_change": 0},
  "time_range": {"start": "ISO", "end": "ISO"},
  "total_signals_in_store": "int"
}
```

---

### Tool 3: `correlate_signals`

**Purpose**: The core analysis engine. Finds correlations across signals from
different sources. Produces pairwise correlations and clusters them into insights.

**Input Schema**:
```json
{
  "source_ids": "string[] | null — sources to correlate (null = all registered)",
  "time_window": {
    "start": "ISO | null",
    "end": "ISO | null"
  },
  "correlation_types": "string[] — which methods to run (default: all)",
  "options": {
    "temporal_window": "string — max time gap for co-occurrence (default: '7d')",
    "spatial_radius_km": "float — max distance for spatial alignment (default: 50.0)",
    "lag_max_periods": "int — max lag to scan for lagged correlation (default: 30)",
    "min_confidence": "float — minimum correlation confidence to report (default: 0.5)",
    "cluster_signals": "bool — group correlations into insight clusters (default: true)"
  }
}
```

**Correlation Types (all run by default)**:

1. **`temporal_co_occurrence`**
   - Find signals from different sources whose time ranges overlap or fall within `temporal_window`
   - Statistical test: hypergeometric test — is the co-occurrence rate higher than chance?
   - Output: pairs with overlap score and significance

2. **`lagged_correlation`**
   - For each pair of sources, extract signal time series (signal presence/magnitude over time)
   - Compute cross-correlation function with lags from `-lag_max_periods` to `+lag_max_periods`
   - Identify significant lag peaks
   - Optional: Granger causality test for significant lags
   - Output: pairs with optimal lag, correlation strength, and Granger p-value

3. **`spatial_alignment`**
   - For signals with geographic coordinates, find cross-source signals within `spatial_radius_km`
   - Spatial co-occurrence significance test
   - Output: pairs with distance and spatial cluster membership

4. **`entity_alignment`**
   - For sources sharing entity keys, find signals affecting the same entities
   - Cross-source entity-level co-occurrence
   - Output: pairs with shared entity counts and Jaccard similarity

5. **`pattern_similarity`**
   - Compare the shape of baseline seasonality patterns across sources
   - Useful for finding datasets that "move together" even without specific anomaly correlation
   - Uses dynamic time warping (DTW) or cosine similarity on seasonal components
   - Output: source pairs with similarity scores

**Post-processing — Insight Clustering**:
- Build a signal graph (NetworkX): nodes = signals, edges = discovered correlations
- Extract connected components as candidate insight clusters
- For clusters with 3+ signals: compute feature vectors and refine with DBSCAN
- Score each cluster on actionability: `f(severity, cross_source_count, confidence, persistence)`
- Generate narrative for each cluster

**Output Schema**:
```json
{
  "correlations_found": "int",
  "by_type": {
    "temporal_co_occurrence": "int",
    "lagged_correlation": "int",
    "spatial_alignment": "int",
    "entity_alignment": "int",
    "pattern_similarity": "int"
  },
  "pairwise_correlations": [
    {
      "correlation_id": "string",
      "signal_a": {"signal_id": "string", "source_id": "string", "column": "string", "type": "string"},
      "signal_b": {"signal_id": "string", "source_id": "string", "column": "string", "type": "string"},
      "correlation_type": "string",
      "strength": "float 0-1",
      "lag": "string | null — e.g. 'A leads B by 3 days'",
      "spatial_distance_km": "float | null",
      "confidence": "float 0-1",
      "narrative": "string"
    }
  ],
  "insights": [
    {
      "insight_id": "string",
      "title": "string — short descriptive title",
      "signals_involved": [
        {"source_id": "string", "column": "string", "signal_type": "string"}
      ],
      "correlation_types": ["string"],
      "strength": "float 0-1 — aggregate cluster strength",
      "lag_structure": "string | null — description of temporal sequence",
      "actionability_score": "float 0-1",
      "suggested_actions": ["string"],
      "narrative": "string — full explanation"
    }
  ],
  "meta": {
    "sources_analyzed": "int",
    "signals_analyzed": "int",
    "analysis_duration_seconds": "float"
  }
}
```

---

### Tool 4: `query_insights`

**Purpose**: Retrieve and filter previously discovered insights.

**Input Schema**:
```json
{
  "source_ids": "string[] | null — filter to insights involving these sources",
  "min_actionability": "float — minimum actionability score (default: 0.0)",
  "min_strength": "float — minimum correlation strength (default: 0.0)",
  "tags": "string[] | null — filter by source tags",
  "time_window": {"start": "ISO | null", "end": "ISO | null"},
  "limit": "int — max results (default: 20)",
  "sort_by": "string — 'actionability' | 'strength' | 'recency' (default: 'actionability')"
}
```

**Output Schema**:
```json
{
  "insights": ["... same insight objects as correlate_signals output ..."],
  "total_matching": "int",
  "returned": "int"
}
```

---

### Tool 5: `explain_insight`

**Purpose**: Deep-dive into a specific insight. Returns the full signal chain,
underlying data summaries, and confidence assessment.

**Input Schema**:
```json
{
  "insight_id": "string"
}
```

**Output Schema**:
```json
{
  "insight": {
    "insight_id": "string",
    "title": "string",
    "narrative": "string",
    "signals": [
      {
        "signal_id": "string",
        "source_id": "string",
        "source_name": "string",
        "column": "string",
        "signal_type": "string",
        "severity": "string",
        "timestamp_range": {"start": "ISO", "end": "ISO"},
        "magnitude": "float",
        "original_narrative": "string — Layer 1's narrative for this signal"
      }
    ],
    "correlations": [
      {
        "from_signal": "string",
        "to_signal": "string",
        "type": "string",
        "strength": "float",
        "lag": "string | null",
        "evidence": "string — statistical test result"
      }
    ],
    "graph_path": "string — description of the multi-hop path through the signal graph",
    "confidence_assessment": {
      "overall_confidence": "float",
      "weakest_link": "string — which correlation in the chain is least certain",
      "data_sufficiency": "string — whether enough data supports this finding",
      "alternative_explanations": ["string — other possible causes"]
    },
    "actionability": {
      "score": "float",
      "reasoning": "string",
      "suggested_actions": ["string"],
      "estimated_impact": "string | null"
    }
  }
}
```

---

### Tool 6: `list_sources`

**Purpose**: List all registered sources and their signal counts.

**Input Schema**:
```json
{}
```

**Output Schema**:
```json
{
  "sources": [
    {
      "source_id": "string",
      "name": "string",
      "domain": "string",
      "geography": {"region": "string | null"},
      "signal_count": "int",
      "latest_signal": "ISO | null",
      "tags": ["string"]
    }
  ]
}
```

---

## Signal Store Schema (DuckDB)

```sql
CREATE TABLE sources (
    source_id       VARCHAR PRIMARY KEY,
    name            VARCHAR NOT NULL,
    description     VARCHAR,
    domain          VARCHAR,
    region          VARCHAR,
    latitude        DOUBLE,
    longitude       DOUBLE,
    radius_km       DOUBLE,
    entity_keys     VARCHAR[],
    baseline_path   VARCHAR,
    tags            VARCHAR[],
    registered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE signals (
    signal_id       VARCHAR PRIMARY KEY,
    source_id       VARCHAR REFERENCES sources(source_id),
    column_name     VARCHAR NOT NULL,
    signal_type     VARCHAR NOT NULL,
    severity        VARCHAR,
    ts_start        TIMESTAMP NOT NULL,
    ts_end          TIMESTAMP,
    magnitude       DOUBLE,
    direction       VARCHAR,
    confidence      DOUBLE,
    latitude        DOUBLE,
    longitude       DOUBLE,
    entity_values   JSON,
    metadata        JSON,
    narrative       VARCHAR,
    ingested_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE correlations (
    correlation_id  VARCHAR PRIMARY KEY,
    signal_a_id     VARCHAR REFERENCES signals(signal_id),
    signal_b_id     VARCHAR REFERENCES signals(signal_id),
    correlation_type VARCHAR NOT NULL,
    strength        DOUBLE,
    lag_description VARCHAR,
    lag_periods     INTEGER,
    spatial_distance_km DOUBLE,
    confidence      DOUBLE,
    evidence        VARCHAR,
    narrative       VARCHAR,
    discovered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE insights (
    insight_id      VARCHAR PRIMARY KEY,
    title           VARCHAR,
    signal_ids      VARCHAR[],
    correlation_ids VARCHAR[],
    correlation_types VARCHAR[],
    strength        DOUBLE,
    actionability   DOUBLE,
    lag_structure   VARCHAR,
    suggested_actions JSON,
    narrative       VARCHAR,
    discovered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common query patterns
CREATE INDEX idx_signals_source ON signals(source_id);
CREATE INDEX idx_signals_time ON signals(ts_start, ts_end);
CREATE INDEX idx_signals_type ON signals(signal_type);
CREATE INDEX idx_correlations_type ON correlations(correlation_type);
CREATE INDEX idx_insights_actionability ON insights(actionability DESC);
```

## Correlation Engine Details

### Temporal Co-occurrence

For each pair of signals from different sources:
1. Check if time ranges overlap or gap < `temporal_window`
2. Compute overlap score: `overlap_duration / max(duration_a, duration_b)`
3. Significance test: given N_a signals from source A and N_b from source B
   across total time span T, what's the probability of K or more co-occurrences
   by chance? (hypergeometric distribution)
4. Report pairs where p-value < 0.05 and overlap_score > 0.1

### Lagged Correlation

1. For each pair of sources, create binary signal time series:
   presence/absence of deviations in each time period (daily or weekly bins)
2. Optionally use magnitude-weighted series instead of binary
3. Compute cross-correlation function for lags -L to +L
4. Find peak correlation and its lag
5. Granger causality test (VAR model) for significant lags
6. Report pairs where |correlation| > `min_confidence` and Granger p < 0.05

### Spatial Alignment

1. For signals with coordinates, compute pairwise haversine distances
2. Cross-source signal pairs within `spatial_radius_km` are candidates
3. Spatial co-occurrence significance: given the geographic distribution of
   signals from each source, is the spatial clustering tighter than random?
   (permutation test)
4. Group spatially co-located cross-source signals into spatial clusters

### Entity Alignment

1. For sources sharing entity keys, extract entity values from each signal's metadata
2. Find cross-source signal pairs affecting the same entities
3. Compute Jaccard similarity of affected entity sets
4. Significance: given the entity populations of each source, is the overlap
   greater than chance? (hypergeometric test on entity sets)

### Pattern Similarity

1. Load baseline seasonal components from Layer 1 artifacts
2. For each pair of columns across sources, compute similarity:
   - Normalize seasonal components to zero-mean unit-variance
   - Cosine similarity for same-frequency seasonality
   - Dynamic Time Warping (DTW) distance for potentially phase-shifted patterns
3. Report pairs with high similarity as "co-moving" patterns

### Insight Clustering

1. Build signal graph from all discovered correlations
2. Extract connected components (candidate clusters)
3. For large components, refine with DBSCAN:
   - Feature vector per signal: [time_normalized, magnitude_normalized, severity_encoded,
     source_domain_encoded, lat_normalized, lon_normalized]
   - DBSCAN eps tuned by elbow method on nearest-neighbor distances
4. Score each cluster:
   ```
   actionability = w1 * mean_severity + w2 * cross_source_diversity +
                   w3 * mean_confidence + w4 * persistence_score
   ```
   Where:
   - `mean_severity`: average severity of signals in cluster (critical=1.0, low=0.25)
   - `cross_source_diversity`: number of distinct sources / total registered sources
   - `mean_confidence`: average confidence of correlations in cluster
   - `persistence_score`: fraction of signals classified as "sustained"
5. Generate title and narrative via structured templates
6. Suggest actions based on signal types and domains involved

## Dependencies

### Core
```
duckdb>=0.9             # Signal store
networkx>=3.0           # Signal graph
numpy>=1.24
pandas>=2.0
scipy>=1.11             # Statistical tests, cross-correlation
scikit-learn>=1.3       # DBSCAN clustering, DTW
mcp[cli]>=1.0
```

### Optional
```
statsmodels>=0.14       # Granger causality (VAR)
dtw-python>=1.3         # Dynamic Time Warping
geopy>=2.4              # Haversine distance calculations
plotly>=5.0             # Visualization
```

## Implementation Phases

### Phase 1: Foundation
1. `list_sources` + `register_source` — source registry in DuckDB
2. `ingest_signals` — parse Layer 1 output into canonical signal format
3. Basic `correlate_signals` — temporal co-occurrence only
4. Test with synthetic signals from two sources

### Phase 2: Full Correlation
5. Lagged correlation + Granger causality
6. Spatial alignment
7. Entity alignment
8. Pattern similarity

### Phase 3: Insights
9. Signal graph construction
10. DBSCAN insight clustering
11. Actionability scoring
12. `query_insights` + `explain_insight`
13. Narrative generation templates

### Phase 4: Integration
14. End-to-end workflow: Layer 1 → Layer 2 automated pipeline
15. Incremental ingestion (new signals added to existing store)
16. Visualization: insight cluster graph export
17. Alert/notification hooks for high-actionability insights

## Agent Interaction Patterns

### First-time setup
```
Agent → register_source(source_id="restaurant_pos", domain="pos",
          geography={region: "Edinburgh"}, tags=["whisky", "spirits"])
Agent → register_source(source_id="jwps_bookings", domain="bookings",
          geography={region: "Edinburgh", lat: 55.95, lon: -3.21})
Agent → ingest_signals(source_id="restaurant_pos", signal_type="deviations",
          data_path="./restaurant_pos_deviations.json")
Agent → ingest_signals(source_id="jwps_bookings", signal_type="deviations",
          data_path="./jwps_deviations.json")
```

### Correlation analysis
```
Agent → correlate_signals(source_ids=["restaurant_pos", "jwps_bookings"],
          options={temporal_window: "7d", spatial_radius_km: 10})
  ← correlations + insight clusters
Agent reasons about insights, presents to user
```

### Ongoing monitoring
```
Agent → ingest_signals(source_id="restaurant_pos", signal_type="deviations",
          data_path="./latest_restaurant_deviations.json")
Agent → correlate_signals()  # re-run with new data
Agent → query_insights(min_actionability=0.7, sort_by="recency")
  ← latest high-value insights
```

### Deep dive
```
User: "Tell me more about that post-tour retail effect"
Agent → explain_insight(insight_id="ins_001")
  ← full signal chain, evidence, confidence, actions
```

## Output Design Principles

1. **Insight-first**: The primary output is clustered insights, not raw correlations.
   Pairwise correlations are available but the agent should present insights.

2. **Evidence chains**: Every insight includes the correlation evidence path.
   "Signal A → correlates with B (temporal, r=0.82, lag=2h) → correlates with C
   (spatial, 3.2km) → forming cluster about [topic]."

3. **Explicit uncertainty**: Confidence scores at every level. Weakest-link analysis
   tells the user which part of the finding is least certain.

4. **Alternative explanations**: The explain_insight tool should flag possible
   confounders or alternative causes (e.g., "both signals may be driven by a
   shared external event like a festival, rather than a causal relationship").

5. **Actionable framing**: Suggested actions are domain-specific based on the
   source domains involved (POS → pricing/inventory, bookings → capacity/marketing,
   digital → campaign optimization).
