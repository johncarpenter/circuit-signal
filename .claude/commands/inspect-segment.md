# Inspect Segment

Run full signal analysis (baseline, deviations, forecast) on a segment CSV via layer1 (`signal-discovery`) and generate an interactive HTML report with embedded charts.

## Arguments

`$ARGUMENTS` — path to a segment CSV file (e.g. `data/segments/heineken_daily.csv` or `heineken_daily`)

## Workflow

Follow each step in order.

---

### Step 1 — Resolve segment file

- If `$ARGUMENTS` is a full path, use it directly
- If it's just a filename, look in `data/segments/`
- If `$ARGUMENTS` is empty, glob for `data/segments/*.csv` and ask the user to pick with `AskUserQuestion`
- Verify the file exists before proceeding

---

### Step 2 — Inspect the segment

Call `mcp__signal-discovery__inspect_dataset` with:
- `data_path`: absolute path to the segment CSV

From the result, extract:
- `timestamp_col`: should be `period` (the standard output from `create_segment`)
- `value_cols`: all numeric columns (exclude `period`)
- `freq`: infer from data spacing (hourly, daily, weekly, monthly)
- `row_count`, `time_range`, basic stats

Display a brief summary:

**Segment**: `{filename}`
**Rows**: `{row_count}` | **Freq**: `{freq}` | **Period**: `{start}` → `{end}`
**Metrics**: list value columns with min/max/mean

---

### Step 3 — Run baseline discovery

Call `mcp__signal-discovery__discover_baseline` with:
- `data_path`: absolute path to segment CSV
- `timestamp_col`: `period`
- `value_cols`: numeric columns from step 2
- `freq`: detected frequency from step 2

The result will be large. Extract and store:
- `baseline_path`: path to saved baseline artifacts
- `baselines`: array with trend, seasonality, residual info per column
- `dataset_summary`: row count, time range, data quality
- Chart directory path (from the report — typically `{stem}_{freq}_baseline_charts/`)

Tell the user: "Baseline complete. Running deviation detection..."

---

### Step 4 — Run deviation detection

Call `mcp__signal-discovery__detect_deviations` with:
- `data_path`: absolute path to segment CSV
- `timestamp_col`: `period`
- `baseline_path`: from step 3
- `lookback_window`: `90d` (or full range if < 90 days)
- `sensitivity`: `medium`
- `value_cols`: same as step 3

The result will be large. Extract and store:
- `analysis_window`: start/end
- `deviations`: array of all detected deviations
- `summary`: total count, by severity, narrative

Group deviations by column and severity for the report.

Tell the user: "Deviations detected. Running forecast..."

---

### Step 5 — Run forecast

Call `mcp__signal-discovery__project_forecast` with:
- `data_path`: absolute path to segment CSV
- `timestamp_col`: `period`
- `baseline_path`: from step 3
- `value_cols`: same as step 3
- `horizon`: `30d`
- `scenarios`: `true`
- `confidence_levels`: `[0.80, 0.95]`

Extract and store:
- `forecasts`: per-column forecast data with confidence intervals
- `backtest`: accuracy metrics
- Chart paths if generated

Tell the user: "Forecast complete. Generating HTML report..."

---

### Step 6 — Generate HTML report

Write a standalone HTML file to `data/segments/{segment_stem}_report.html`.

The report must follow the visual style of `comparison.html`:
- Clean card-based layout with white `.section` cards on `#f5f5f5` background
- Green gradient header (`#1b5e20` → `#388e3c`)
- CSS variables for consistent theming
- Rounded corners (`12px`), soft shadows
- System font stack (`'Segoe UI', system-ui, -apple-system, sans-serif`)
- Responsive, single-column layout

**Use a Python script** (run via `python3`) to generate the HTML. The script should:

1. Read the segment CSV with pandas
2. Read any baseline chart PNGs and encode them as base64 for embedding
3. Generate additional matplotlib charts:
   - **Time series overview**: raw data with 7-day and 30-day moving averages (line chart)
   - **Day-of-week pattern**: average value by weekday (bar chart)
   - **Monthly pattern**: average value by month (bar chart)
   - **Trend decomposition**: use the baseline trend values if available, otherwise compute
   - **Deviation timeline**: plot raw data with deviation points highlighted (red dots for critical, orange for high, yellow for medium)
   - **Forecast**: historical data + forecast line with confidence bands (shaded 80% and 95%)
4. Assemble everything into a single HTML file with embedded base64 images

**HTML structure** (sections in order):

```
Header
  - Title: "{dataset} — Signal Analysis Report"
  - Subtitle: "{start} → {end} | {freq} | {row_count} periods"
  - Badges: one per metric column
  - Generated timestamp

Section 1: Executive Summary
  - KPI cards in a grid: total periods, trend direction, deviations found (by severity), variance explained
  - Use colored badges: green for good, amber for warning, red for critical

Section 2: Time Series Overview
  - Embedded chart: raw data + moving averages
  - Brief narrative from baseline

Section 3: Trend Analysis
  - Embedded trend chart (from baseline or generated)
  - Change points listed in a clean table
  - Trend direction and rate

Section 4: Seasonality Patterns
  - Embedded seasonality chart (from baseline or generated)
  - Day-of-week bar chart
  - Monthly bar chart (if enough data)
  - Peak phase info

Section 5: Deviation Detection
  - Summary stats: total deviations, breakdown by severity
  - Deviation timeline chart with anomalies highlighted
  - Table of top 10 deviations (timestamp, observed vs expected, z-score, severity)
  - Severity badges: critical=red, high=orange, medium=amber

Section 6: Forecast
  - Forecast chart with confidence bands
  - Backtest accuracy metrics
  - Scenario variants if available

Section 7: Residual Analysis
  - Residual chart (from baseline or generated)
  - Stats table: std dev, stationarity, skewness, kurtosis
  - Distribution assessment
```

**Chart styling** (matplotlib):
- Figure size: `(14, 5)` for full-width, `(7, 5)` for half-width
- Color palette: `#1b5e20` (primary), `#388e3c` (secondary), `#e8f5e9` (fill), `#f57f17` (warning), `#c62828` (critical)
- White background, minimal gridlines (`alpha=0.3`)
- DPI: 150 for crisp rendering
- Clean axis labels, no chartjunk

**Important implementation notes**:
- The Python script should accept the segment CSV path and all analysis results as JSON files (write temp JSON files from the MCP results before running the script)
- Use `base64.b64encode` to embed all PNGs directly in the HTML — no external file dependencies
- The final HTML must be completely self-contained (inline CSS, inline images, no external resources)
- Handle missing data gracefully (if forecast or deviations fail, still produce the report with available sections)

---

### Step 7 — Present results

Display:

**Report generated**: `data/segments/{segment_stem}_report.html`

Open the report:
```bash
open data/segments/{segment_stem}_report.html
```

Show a brief summary of key findings:
- Trend direction and strength
- Number of deviations by severity
- Forecast outlook

---

## Error handling

- If `inspect_dataset` fails, show the error and stop
- If `discover_baseline` fails, show the error and stop (baseline is required for everything else)
- If `detect_deviations` fails, show warning and continue — generate report without deviation section
- If `project_forecast` fails, show warning and continue — generate report without forecast section
- If the Python chart generation script fails, show the error, try to fix, and retry once. If it fails again, generate a simpler HTML report using just tables and the baseline PNGs (no custom matplotlib charts)
