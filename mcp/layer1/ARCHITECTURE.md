# Signal Discovery MCP Server — Architecture Specification

## Overview

An MCP (Model Context Protocol) server that exposes time-series signal discovery as tools for Claude Code. Given any single-table dataset with at least one timestamp column, the server autonomously discovers temporal patterns, tracks deviations, and projects forecasts.

## Design Philosophy

- **Zero-configuration discovery**: The agent should be able to point this at an unfamiliar dataset and get useful results without manual parameter tuning
- **Three operating modes** that build sequentially: Baseline → Deviation → Projection
- **Tools, not pipelines**: Each mode is an MCP tool that can be called independently, enabling the LLM agent to reason about what to run and when
- **Local-first**: All processing runs locally using open-source libraries. API-based models (TimeGPT) are optional enhancements, never dependencies

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Claude Code                     │
│         (LLM Agent / Orchestrator)               │
└──────────────┬──────────────────────────────────┘
               │ MCP Protocol (stdio)
┌──────────────▼──────────────────────────────────┐
│          Signal Discovery MCP Server             │
│                                                  │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐ │
│  │  Tool:     │ │  Tool:     │ │  Tool:       │ │
│  │  discover  │ │  detect    │ │  project     │ │
│  │  _baseline │ │  _deviations│ │  _forecast  │ │
│  │  (Mode 1)  │ │  (Mode 2)  │ │  (Mode 3)   │ │
│  └─────┬──────┘ └─────┬──────┘ └──────┬───────┘ │
│        │              │               │          │
│  ┌─────▼──────────────▼───────────────▼───────┐ │
│  │           Analysis Engine                   │ │
│  │                                             │ │
│  │  ┌───────────┐ ┌──────────┐ ┌────────────┐ │ │
│  │  │ STL/MSTL  │ │ ruptures │ │  stumpy    │ │ │
│  │  │ decompose │ │ chgpoint │ │  matrix    │ │ │
│  │  │           │ │          │ │  profile   │ │ │
│  │  └───────────┘ └──────────┘ └────────────┘ │ │
│  │  ┌───────────┐ ┌──────────┐ ┌────────────┐ │ │
│  │  │ scipy     │ │ prophet  │ │  stats     │ │ │
│  │  │ stats     │ │ forecast │ │  tests     │ │ │
│  │  └───────────┘ └──────────┘ └────────────┘ │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │           Data Layer                        │ │
│  │                                             │ │
│  │  ┌───────────┐ ┌──────────────────────────┐ │ │
│  │  │ Ingest    │ │ Baseline Store           │ │ │
│  │  │ CSV/JSON/ │ │ (JSON cache of Mode 1    │ │ │
│  │  │ Parquet/  │ │  decompositions for      │ │ │
│  │  │ DuckDB    │ │  Mode 2 & 3 reference)   │ │ │
│  │  └───────────┘ └──────────────────────────┘ │ │
│  └─────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
```

## MCP Tools

### Tool 1: `discover_baseline`

**Purpose**: Decompose time series to establish "what normal looks like"

**Input Schema**:
```json
{
  "data_path": "string — path to CSV/Parquet/JSON file",
  "timestamp_col": "string — name of the timestamp column",
  "value_cols": "string[] | null — columns to analyze (null = auto-detect all numeric)",
  "freq": "string | null — 'hourly','daily','weekly','monthly' (null = auto-detect)",
  "output_dir": "string | null — where to save baseline artifacts (default: ./.signal-baselines/)"
}
```

**Processing**:
1. **Ingest & Validate**: Load data, parse timestamps, sort, detect frequency if not provided, report data quality (gaps, nulls, duplicates)
2. **Auto-detect analyzable columns**: If `value_cols` is null, find all numeric columns. Skip columns with >50% nulls or zero variance
3. **For each column**:
   a. Determine appropriate seasonal periods from frequency (daily → [7, 365.25], hourly → [24, 168])
   b. Run STL or MSTL decomposition → trend, seasonal component(s), residual
   c. Calculate variance explained: `1 - var(residual) / var(original)`
   d. Run ADF test on residual to assess stationarity
   e. Calculate residual distribution stats (mean, std, skew, kurtosis) for Mode 2 thresholds
   f. Detect structural change points in trend component via `ruptures` PELT
4. **Persist baseline**: Save decomposition parameters and summary stats to `output_dir`

**Output Schema**:
```json
{
  "dataset_summary": {
    "rows": "int",
    "time_range": {"start": "ISO datetime", "end": "ISO datetime"},
    "frequency_detected": "string",
    "columns_analyzed": "int",
    "data_quality": {
      "completeness": "float 0-1",
      "gaps_detected": "int",
      "duplicate_timestamps": "int"
    }
  },
  "baselines": [
    {
      "column": "string",
      "variance_explained": "float 0-1",
      "trend": {
        "direction": "increasing | decreasing | flat",
        "rate_per_period": "float",
        "change_points": [
          {"timestamp": "ISO", "magnitude": "float", "direction": "string"}
        ]
      },
      "seasonality": [
        {
          "period": "int",
          "period_label": "string (e.g. 'weekly', 'annual')",
          "strength": "float 0-1",
          "peak_phase": "string (e.g. 'Saturday', 'July')"
        }
      ],
      "residual_profile": {
        "std": "float",
        "is_stationary": "bool",
        "distribution": "normal | skewed | heavy-tailed"
      },
      "narrative": "string — LLM-ready plain English summary"
    }
  ],
  "baseline_path": "string — path to saved baseline artifacts"
}
```

---

### Tool 2: `detect_deviations`

**Purpose**: Compare recent data against established baseline, flag significant deviations

**Input Schema**:
```json
{
  "data_path": "string — path to data file (can be same or newer data)",
  "timestamp_col": "string",
  "baseline_path": "string — path to Mode 1 baseline artifacts",
  "lookback_window": "string | null — '7d','30d','90d' (null = all data after baseline)",
  "sensitivity": "string — 'low' | 'medium' | 'high' (z-score thresholds: 3.0 / 2.5 / 2.0)",
  "value_cols": "string[] | null"
}
```

**Processing**:
1. **Load baseline** from Mode 1 artifacts
2. **For each column**:
   a. **Trend deviation**: Fit trend on recent window, compare slope to baseline. Flag if >2σ different
   b. **Seasonal deviation**: Compare current seasonal shape to baseline via cross-correlation
   c. **Residual anomalies** (3-stage cascade):
      - Stage 1: Rolling z-score against baseline residual distribution
      - Stage 2: `stumpy` matrix profile on residual — flag discords
      - Stage 3: `ruptures` change point detection on recent residuals
   d. **Classify**: `trend_shift | seasonal_anomaly | point_anomaly | regime_change`

**Output Schema**:
```json
{
  "analysis_window": {"start": "ISO", "end": "ISO"},
  "deviations": [
    {
      "column": "string",
      "type": "trend_shift | seasonal_anomaly | point_anomaly | regime_change",
      "severity": "low | medium | high | critical",
      "timestamp_range": {"start": "ISO", "end": "ISO"},
      "details": {
        "expected_value": "float | null",
        "observed_value": "float | null",
        "deviation_magnitude": "float",
        "z_score": "float | null",
        "confidence": "float 0-1"
      },
      "persistence": "transient | sustained",
      "narrative": "string"
    }
  ],
  "summary": {
    "total_deviations": "int",
    "by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
    "most_affected_columns": ["string"],
    "narrative": "string — executive summary"
  }
}
```

---

### Tool 3: `project_forecast`

**Purpose**: Confidence-bounded projections with scenario variants

**Input Schema**:
```json
{
  "data_path": "string",
  "timestamp_col": "string",
  "baseline_path": "string",
  "value_cols": "string[] | null",
  "horizon": "string — '7d','30d','90d','365d'",
  "scenarios": "bool — generate deviation-adjusted scenarios (default: true)",
  "confidence_levels": "float[] — (default: [0.80, 0.95])"
}
```

**Processing**:
1. Load baseline decomposition and any active Mode 2 deviations
2. **For each column**:
   a. **Baseline forecast**: Prophet fit → extrapolate with uncertainty intervals
   b. **Deviation-adjusted scenario**: If Mode 2 found active deviations, project "what if current deviation persists"
   c. **Backtest accuracy**: Walk-forward validation → MAPE, CI coverage
   d. **Trustworthy horizon**: Point where CI width exceeds useful threshold

**Output Schema**:
```json
{
  "forecasts": [
    {
      "column": "string",
      "scenarios": [
        {
          "name": "baseline | deviation_adjusted",
          "description": "string",
          "predictions": [
            {
              "timestamp": "ISO",
              "point_forecast": "float",
              "ci_80_lower": "float",
              "ci_80_upper": "float",
              "ci_95_lower": "float",
              "ci_95_upper": "float"
            }
          ]
        }
      ],
      "accuracy_profile": {
        "backtest_mape": "float",
        "backtest_coverage_80": "float",
        "backtest_coverage_95": "float",
        "trustworthy_horizon": "string"
      },
      "narrative": "string"
    }
  ]
}
```

---

### Utility Tool: `inspect_dataset`

**Purpose**: Quick exploratory scan — helps agent decide what to analyze

**Input Schema**:
```json
{
  "data_path": "string",
  "sample_rows": "int (default: 5)"
}
```

**Output Schema**:
```json
{
  "file_info": {
    "format": "csv | parquet | json",
    "rows": "int",
    "columns": "int",
    "size_mb": "float"
  },
  "columns": [
    {
      "name": "string",
      "dtype": "string",
      "nulls": "int",
      "unique": "int",
      "is_timestamp_candidate": "bool",
      "is_numeric": "bool",
      "sample_values": ["any"],
      "stats": {"min": "any", "max": "any", "mean": "float|null", "std": "float|null"}
    }
  ],
  "timestamp_candidates": ["string"],
  "sample_rows": "array of objects"
}
```

---

## Baseline Store Format

```
.signal-baselines/
├── manifest.json                    # Dataset metadata, analysis timestamp
├── columns/
│   ├── revenue.json                 # Per-column decomposition summary + stats
│   ├── visitors.json
│   └── ...
└── decompositions/
    ├── revenue_trend.parquet        # Full trend component time series
    ├── revenue_seasonal.parquet     # Full seasonal component(s)
    ├── revenue_residual.parquet     # Full residual series
    └── ...
```

## Dependencies

### Core (required)
```
pandas>=2.0
numpy>=1.24
scipy>=1.11
statsmodels>=0.14       # STL/MSTL decomposition, ADF test
ruptures>=1.1           # Change point detection (PELT)
stumpy>=1.12            # Matrix Profile
pyarrow>=14.0           # Parquet support
mcp[cli]>=1.0           # MCP SDK
```

### Forecasting (Mode 3)
```
prophet>=1.1
```

### Optional
```
nixtla>=0.5             # TimeGPT zero-shot (API-based)
plotly>=5.0              # Interactive charts
kaleido>=0.2            # Static chart export
duckdb>=0.9             # Large file support
```

## Implementation Phases

### Phase 1: MVP (prove it works)
1. `inspect_dataset` tool
2. `discover_baseline` tool — STL decomposition
3. Test with existing restaurant POS data

### Phase 2: Deviation Detection
4. `detect_deviations` tool — full 3-stage cascade
5. Test with synthetic anomaly injection

### Phase 3: Forecasting
6. `project_forecast` tool — Prophet-based
7. Backtest accuracy reporting

### Phase 4: Enhancements
8. DuckDB for large files
9. TimeGPT optional forecaster
10. Chart generation
11. Layer 2 correlation hooks

## Layer 2 Handoff (Future)

Mode 2 outputs include metadata for cross-dataset correlation:
- Timestamp range, column name, magnitude, direction, confidence
- Geographic/entity context if present

A separate Layer 2 correlation MCP server would ingest deviation outputs from multiple Layer 1 instances and find temporal/spatial alignment. The output schema supports this without re-processing raw data.
