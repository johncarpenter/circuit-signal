# Analyze Segment

Non-interactive agent that runs the full layer1 signal analysis pipeline on a single segment and writes all results to a structured JSON file. Designed to be invoked in parallel across multiple segments via the Task tool.

## Arguments

`$ARGUMENTS` — path to a segment CSV file (e.g. `data/segments/heineken_daily.csv`)

## Output

A single JSON file at `data/segments/results/{segment_stem}.json` containing all baseline, deviation, and forecast data for downstream cross-correlation analysis.

## Behavior

- **No interactive prompts** — this agent must run fully autonomously
- **No HTML output** — JSON only
- **No user-facing display** — minimize console output to status lines only
- **Fail fast** — if baseline fails, write an error JSON and stop

---

## Workflow

### Step 1 — Resolve inputs

- Parse `$ARGUMENTS` to get the segment CSV path
- If path has no directory prefix, prepend `data/segments/`
- If path has no extension, append `.csv`
- Resolve to absolute path
- Extract `segment_stem` from filename (without extension)
- Set `output_path` = `data/segments/results/{segment_stem}.json`
- Create `data/segments/results/` directory if needed (use Bash `mkdir -p`)

### Step 2 — Inspect segment

Call `mcp__signal-discovery__inspect_dataset` with:
- `data_path`: absolute path to segment CSV

Extract:
- `timestamp_col`: should be `period`
- `value_cols`: all numeric column names
- `row_count`: number of rows
- `time_range`: first and last values of `period` column
- `freq`: infer from spacing — check if consecutive timestamps are ~1h apart (hourly), ~1d (daily), ~7d (weekly), or ~30d (monthly)
- `stats`: per-column min, max, mean, std

### Step 3 — Run baseline

Call `mcp__signal-discovery__discover_baseline` with:
- `data_path`: absolute path
- `timestamp_col`: `period`
- `value_cols`: from step 2
- `freq`: from step 2

The result will be large. Parse the JSON and extract for each column:
- `column`: column name
- `variance_explained`: float
- `trend`: full trend object (direction, rate_per_period, change_points)
- `seasonality`: full array of seasonal components
- `residual_profile`: full object (std, is_stationary, distribution, skewness, kurtosis)
- `narrative`: string
- `_trend_values`: full array (needed for cross-correlation)
- `_residual_values`: full array (needed for cross-correlation)
- `_index`: full timestamp index array

Store `baseline_path` from the response.

### Step 4 — Run deviation detection

Call `mcp__signal-discovery__detect_deviations` with:
- `data_path`: absolute path
- `timestamp_col`: `period`
- `baseline_path`: from step 3
- `lookback_window`: use full range (e.g. `365d` or `730d` — pick based on row_count * freq)
- `sensitivity`: `medium`
- `value_cols`: from step 2

Extract:
- `analysis_window`: start/end
- `deviations`: full array of all deviations with all fields
- `summary`: total count, by_severity, narrative

If this step fails, set `deviations` section to `{"error": "<message>", "deviations": [], "summary": null}` and continue.

### Step 5 — Run forecast

Call `mcp__signal-discovery__project_forecast` with:
- `data_path`: absolute path
- `timestamp_col`: `period`
- `baseline_path`: from step 3
- `value_cols`: from step 2
- `horizon`: `30d`
- `scenarios`: `true`
- `confidence_levels`: `[0.80, 0.95]`

Extract:
- `forecasts`: full array with all scenarios and predictions
- `accuracy_profile`: backtest metrics

If this step fails, set `forecast` section to `{"error": "<message>", "forecasts": [], "accuracy_profile": null}` and continue.

### Step 6 — Assemble and write JSON

Use a Python script (via Bash with `python3 -c` or a temp file) to assemble the final JSON. Write it to the output path.

**JSON schema**:

```json
{
  "version": "1.0",
  "generated_at": "<ISO timestamp>",
  "segment": {
    "name": "<segment_stem>",
    "path": "<relative path to CSV>",
    "row_count": <int>,
    "time_range": { "start": "<ISO>", "end": "<ISO>" },
    "frequency": "<hourly|daily|weekly|monthly>",
    "value_columns": ["<col1>", "<col2>"]
  },
  "baselines": [
    {
      "column": "<name>",
      "variance_explained": <float>,
      "trend": {
        "direction": "<increasing|decreasing|flat>",
        "rate_per_period": <float>,
        "change_points": [
          { "timestamp": "<ISO>", "magnitude": <float>, "direction": "<increase|decrease>" }
        ]
      },
      "seasonality": [
        {
          "period": <int>,
          "period_label": "<daily|weekly|monthly>",
          "strength": <float>,
          "peak_phase": "<string>"
        }
      ],
      "residual_profile": {
        "std": <float>,
        "is_stationary": <bool>,
        "distribution": "<string>",
        "skewness": <float>,
        "kurtosis": <float>
      },
      "narrative": "<string>",
      "trend_values": [<float>, ...],
      "residual_values": [<float>, ...],
      "index": ["<ISO>", ...]
    }
  ],
  "deviations": {
    "analysis_window": { "start": "<ISO>", "end": "<ISO>" },
    "summary": {
      "total_deviations": <int>,
      "by_severity": { "critical": <int>, "high": <int>, "medium": <int>, "low": <int> },
      "narrative": "<string>"
    },
    "items": [
      {
        "column": "<name>",
        "type": "<point_anomaly|regime_change|...>",
        "severity": "<critical|high|medium|low>",
        "timestamp_range": { "start": "<ISO>", "end": "<ISO>" },
        "details": {
          "expected_value": <float>,
          "observed_value": <float>,
          "deviation_magnitude": <float>,
          "z_score": <float>,
          "confidence": <float>
        },
        "persistence": "<transient|sustained>",
        "narrative": "<string>"
      }
    ],
    "error": null
  },
  "forecast": {
    "horizon": "30d",
    "columns": [
      {
        "column": "<name>",
        "scenarios": [
          {
            "name": "<baseline|optimistic|pessimistic>",
            "description": "<string>",
            "predictions": [
              {
                "timestamp": "<ISO>",
                "point_forecast": <float>,
                "ci_80_lower": <float>,
                "ci_80_upper": <float>,
                "ci_95_lower": <float>,
                "ci_95_upper": <float>
              }
            ]
          }
        ],
        "accuracy_profile": {
          "backtest_mape": <float|null>,
          "backtest_coverage_80": <float|null>,
          "backtest_coverage_95": <float|null>,
          "trustworthy_horizon": "<string>"
        },
        "narrative": "<string>"
      }
    ],
    "error": null
  }
}
```

### Step 7 — Return summary

Output a single short message:

```
Segment analysis complete: {segment_stem}
  Rows: {row_count} | Freq: {freq} | Period: {start} → {end}
  Columns: {value_cols}
  Trend: {direction} | Variance explained: {pct}%
  Deviations: {total} ({critical} critical)
  Output: data/segments/results/{segment_stem}.json
```

---

## Error handling

- If the segment file does not exist, write error JSON and return immediately
- If `inspect_dataset` fails, write error JSON and return
- If `discover_baseline` fails, write error JSON and return (baseline is required)
- If `detect_deviations` fails, record error in deviations section, continue to forecast
- If `project_forecast` fails, record error in forecast section, continue to write JSON
- Always write the JSON file, even on partial failure — include `"error"` fields in failed sections

## Important

- Do NOT use `AskUserQuestion` — this agent runs autonomously
- Do NOT generate HTML or charts — JSON only
- Do NOT display large data tables — keep output minimal
- The `trend_values`, `residual_values`, and `index` arrays are essential for cross-correlation — always include them
- Parse MCP results carefully — they return stringified JSON inside a `result` field that needs `json.loads()`
