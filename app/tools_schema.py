"""Anthropic-format tool definitions for all 17 pipeline tools."""

TOOLS = [
    # -----------------------------------------------------------------------
    # Layer 0 — Data Loader (7 tools)
    # -----------------------------------------------------------------------
    {
        "name": "load_dataset",
        "description": (
            "Load a CSV, Parquet, or JSON file into the data store. "
            "Returns rich column profiling: roles (timestamp/numeric/categorical/identifier), "
            "per-column stats, segment candidates with reasons, and detected hierarchies."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_path": {
                    "type": "string",
                    "description": "Path to CSV, Parquet, or JSON file",
                },
                "dataset_name": {
                    "type": ["string", "null"],
                    "description": "Optional name for the dataset (defaults to filename stem)",
                },
            },
            "required": ["data_path"],
        },
    },
    {
        "name": "suggest_segments",
        "description": (
            "Auto-segmentation engine. Analyzes a loaded dataset and recommends how to "
            "split it into independent time series for Layer 1 analysis. "
            "Scores by differentiation, balance, coverage, and size."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "Name of a previously loaded dataset",
                },
                "timestamp_col": {
                    "type": "string",
                    "description": "Which column is the timestamp",
                },
                "value_cols": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Which numeric columns matter (null = all numeric)",
                },
                "min_segment_size": {
                    "type": "integer",
                    "description": "Minimum rows per segment (default: 50)",
                },
                "max_segments": {
                    "type": "integer",
                    "description": "Maximum number of segments to suggest (default: 30)",
                },
            },
            "required": ["dataset_id", "timestamp_col"],
        },
    },
    {
        "name": "create_segments",
        "description": (
            "Split data into segments based on column(s). Creates materialized DuckDB "
            "tables for each segment and optionally exports as files for Layer 1."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "Name of a previously loaded dataset",
                },
                "segment_by": {
                    "description": "Column(s) to segment on (string or list of strings)",
                },
                "timestamp_col": {
                    "type": "string",
                    "description": "Column containing timestamps",
                },
                "value_cols": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Columns to include (null = all numeric + timestamp)",
                },
                "min_segment_size": {
                    "type": "integer",
                    "description": "Drop segments smaller than this (default: 50)",
                },
                "export_format": {
                    "type": ["string", "null"],
                    "description": "'csv' or 'parquet' (null = no export)",
                },
                "export_dir": {
                    "type": ["string", "null"],
                    "description": "Directory for exported files",
                },
            },
            "required": ["dataset_id", "segment_by", "timestamp_col"],
        },
    },
    {
        "name": "list_segments",
        "description": (
            "List unique values and their counts for a column in a loaded dataset. "
            "Useful for exploring segment dimensions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_name": {
                    "type": "string",
                    "description": "Name of a previously loaded dataset",
                },
                "column": {
                    "type": "string",
                    "description": "Column name to segment by",
                },
            },
            "required": ["dataset_name", "column"],
        },
    },
    {
        "name": "export_segment",
        "description": (
            "Export a specific segment (or all segments for a dataset) to files "
            "that Layer 1 can consume."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "Name of a previously loaded dataset",
                },
                "segment_id": {
                    "type": ["string", "null"],
                    "description": "Specific segment to export (null = all)",
                },
                "fmt": {
                    "type": "string",
                    "description": "Export format: 'csv' or 'parquet' (default: 'csv')",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Directory for exported files",
                },
            },
            "required": ["dataset_id"],
        },
    },
    {
        "name": "clean_dataset",
        "description": (
            "Detect and fix data quality issues in a loaded dataset. "
            "Plan mode (default): auto-detect issues. Apply mode: execute fixes. "
            "Detects whitespace/case issues, fuzzy duplicates, timezone problems, "
            "numeric-as-string, high null rates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "Name of a previously loaded dataset",
                },
                "operations": {
                    "type": ["array", "null"],
                    "items": {"type": "object"},
                    "description": "List of cleaning operations to apply (for apply mode)",
                },
                "auto_detect": {
                    "type": "boolean",
                    "description": "Scan for issues and suggest fixes (default true)",
                },
                "apply": {
                    "type": "boolean",
                    "description": "If true, apply operations; if false, return plan only",
                },
            },
            "required": ["dataset_id"],
        },
    },
    {
        "name": "resolve_entities",
        "description": (
            "Use LLM to resolve messy entity names in a categorical column. "
            "Groups distinct values into canonical entities, handling abbreviations, "
            "packaging variants, and regional naming differences."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "description": "Name of a previously loaded dataset",
                },
                "column": {
                    "type": "string",
                    "description": "Categorical column to resolve",
                },
                "context": {
                    "type": ["string", "null"],
                    "description": "Description of what this column represents",
                },
                "model": {
                    "type": "string",
                    "description": "Anthropic model to use (default: claude-sonnet-4-20250514)",
                },
            },
            "required": ["dataset_id", "column"],
        },
    },
    # -----------------------------------------------------------------------
    # Layer 1 — Signal Discovery (4 tools)
    # -----------------------------------------------------------------------
    {
        "name": "inspect_dataset",
        "description": (
            "Quick exploratory scan of a dataset. Returns column info, data types, "
            "timestamp candidates, basic stats, and sample rows."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_path": {
                    "type": "string",
                    "description": "Path to CSV, Parquet, or JSON file",
                },
                "sample_rows": {
                    "type": "integer",
                    "description": "Number of sample rows to return (default 5)",
                },
            },
            "required": ["data_path"],
        },
    },
    {
        "name": "discover_baseline",
        "description": (
            "Mode 1: Decompose time series to establish baseline patterns. "
            "Discovers trend, seasonality, and residual characteristics. "
            "Saves baseline artifacts for use by detect_deviations and project_forecast."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_path": {
                    "type": "string",
                    "description": "Path to CSV, Parquet, or JSON file",
                },
                "timestamp_col": {
                    "type": "string",
                    "description": "Name of the timestamp column",
                },
                "value_cols": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Columns to analyze (null = auto-detect all numeric)",
                },
                "freq": {
                    "type": ["string", "null"],
                    "description": "Frequency hint: 'hourly','daily','weekly','monthly' (null = auto-detect)",
                },
                "output_dir": {
                    "type": ["string", "null"],
                    "description": "Where to save baseline artifacts",
                },
            },
            "required": ["data_path", "timestamp_col"],
        },
    },
    {
        "name": "detect_deviations",
        "description": (
            "Mode 2: Compare recent data against the baseline. "
            "Detects trend shifts, seasonal anomalies, point anomalies, and regime changes "
            "using z-scores, Matrix Profile, and change point detection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_path": {
                    "type": "string",
                    "description": "Path to data file",
                },
                "timestamp_col": {
                    "type": "string",
                    "description": "Name of timestamp column",
                },
                "baseline_path": {
                    "type": "string",
                    "description": "Path to Mode 1 baseline artifacts directory",
                },
                "lookback_window": {
                    "type": "string",
                    "description": "How far back to analyze: '7d','30d','90d' (default: '90d')",
                },
                "sensitivity": {
                    "type": "string",
                    "description": "Detection sensitivity: 'low','medium','high'",
                },
                "value_cols": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Columns to check (null = all baselined columns)",
                },
            },
            "required": ["data_path", "timestamp_col", "baseline_path"],
        },
    },
    {
        "name": "project_forecast",
        "description": (
            "Mode 3: Generate confidence-bounded projections with scenario variants. "
            "Includes backtest accuracy metrics and trustworthy horizon estimates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "data_path": {
                    "type": "string",
                    "description": "Path to data file",
                },
                "timestamp_col": {
                    "type": "string",
                    "description": "Name of timestamp column",
                },
                "baseline_path": {
                    "type": "string",
                    "description": "Path to Mode 1 baseline artifacts",
                },
                "value_cols": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Columns to forecast (null = all baselined)",
                },
                "horizon": {
                    "type": "string",
                    "description": "Forecast horizon: '7d','30d','90d','365d'",
                },
                "scenarios": {
                    "type": "boolean",
                    "description": "Generate deviation-adjusted scenarios (default true)",
                },
                "confidence_levels": {
                    "type": ["array", "null"],
                    "items": {"type": "number"},
                    "description": "Confidence intervals (default [0.80, 0.95])",
                },
            },
            "required": ["data_path", "timestamp_col", "baseline_path"],
        },
    },
    # -----------------------------------------------------------------------
    # Layer 2 — Signal Correlation (6 tools)
    # -----------------------------------------------------------------------
    {
        "name": "register_source",
        "description": (
            "Register a data source that feeds signals into the correlation engine. "
            "Describes what this data source represents semantically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "Unique identifier (e.g. 'edinburgh_pos')",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable name",
                },
                "description": {
                    "type": ["string", "null"],
                    "description": "What this data source represents",
                },
                "domain": {
                    "type": "string",
                    "description": "Source domain: 'pos','bookings','web_analytics','social','weather','events','retail','crm','other'",
                },
                "geography": {
                    "type": ["object", "null"],
                    "description": "Location context: {region, latitude, longitude, radius_km}",
                },
                "entity_keys": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Shared identifier columns",
                },
                "baseline_path": {
                    "type": ["string", "null"],
                    "description": "Path to Layer 1 baseline artifacts for this source",
                },
                "tags": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Freeform tags for filtering",
                },
            },
            "required": ["source_id", "name"],
        },
    },
    {
        "name": "list_sources",
        "description": "List all registered data sources with their signal counts and metadata.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "ingest_signals",
        "description": (
            "Ingest Layer 1 output (baselines or deviations) into the correlation store. "
            "Normalizes signals into a canonical format for cross-source analysis. "
            "Provide either 'data' (direct JSON) or 'data_path' (file path)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "Must match a registered source",
                },
                "signal_type": {
                    "type": "string",
                    "description": "Type of Layer 1 output: 'deviations' or 'baseline'",
                },
                "data": {
                    "type": ["object", "null"],
                    "description": "Direct Layer 1 output JSON object",
                },
                "data_path": {
                    "type": ["string", "null"],
                    "description": "Path to Layer 1 output JSON file",
                },
                "context": {
                    "type": ["object", "null"],
                    "description": "Optional context: {analysis_timestamp, data_window: {start, end}}",
                },
            },
            "required": ["source_id"],
        },
    },
    {
        "name": "correlate_signals",
        "description": (
            "Run cross-source signal correlation analysis. Finds temporal co-occurrences, "
            "lagged relationships, spatial alignments, entity-level matches, and "
            "seasonal pattern similarities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_ids": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Sources to correlate (null = all registered)",
                },
                "time_window": {
                    "type": ["object", "null"],
                    "description": "Filter signals: {start: ISO, end: ISO}",
                },
                "correlation_types": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Methods to run (null = all)",
                },
                "options": {
                    "type": ["object", "null"],
                    "description": "Tuning parameters: temporal_window, spatial_radius_km, lag_max_periods, min_confidence, cluster_signals",
                },
            },
        },
    },
    {
        "name": "query_insights",
        "description": "Retrieve and filter previously discovered insights.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_ids": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Filter to insights involving these sources",
                },
                "min_actionability": {
                    "type": "number",
                    "description": "Minimum actionability score (0-1, default 0.0)",
                },
                "min_strength": {
                    "type": "number",
                    "description": "Minimum correlation strength (0-1, default 0.0)",
                },
                "tags": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Filter by source tags",
                },
                "time_window": {
                    "type": ["object", "null"],
                    "description": "Filter by time: {start: ISO, end: ISO}",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20)",
                },
                "sort_by": {
                    "type": "string",
                    "description": "Sort order: 'actionability','strength','recency'",
                },
            },
        },
    },
    {
        "name": "explain_insight",
        "description": (
            "Deep-dive into a specific insight. Returns the full signal chain, "
            "correlation evidence, confidence assessment, alternative explanations, "
            "and actionability reasoning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "insight_id": {
                    "type": "string",
                    "description": "The insight ID to explain",
                },
            },
            "required": ["insight_id"],
        },
    },
]
