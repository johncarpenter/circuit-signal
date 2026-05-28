# Signal Discovery Agent Memory

## Key Patterns

### load_graph requires absolute path
The `mcp__query-planner__load_graph` tool resolves paths relative to the MCP server's working directory, not the project root. Always pass the absolute path: `/Users/john/Documents/Workspace/Circuit/circuit-signal/output/tdv_graph.json`.

### baseline column JSON schema
The `columns/*.json` baseline files have keys: `column`, `variance_explained`, `trend` (direction, rate_per_period, change_points), `seasonality` (list of {period, period_label, strength, peak_phase}), `residual_profile` (std, is_stationary, distribution, skewness, kurtosis), `narrative`. NOT `mean`/`std` at the top level.

### ingest_signals does not accept column baseline files
`mcp__signal-correlation__ingest_signals` with `signal_type: "baseline"` cannot parse the column-level `.json` output from `discover_baseline`. It needs deviation-format output. For cross-store correlation, use the deviation JSONs or skip Layer 2 and do manual comparison if no deviations were produced.

### suggest_segments with many stores
When segmenting by a column with >15 unique values above `min_segment_size`, `suggest_segments` returns empty suggestions. Instead, call `create_segments` directly with a high `min_segment_size` threshold to filter to viable stores only.

### discover_baseline timestamp format issue
Some segment CSVs have mixed timestamp formats (with and without microseconds). If `discover_baseline` fails with a strptime format error, the segment has inconsistent timestamps — skip that store or pre-process the CSV.

### report-agent skill not available
The `report-agent` skill is not installed in this environment. Generate the report and charts directly using matplotlib via a Python subprocess and Write the markdown report manually.

### Dataset-specific graph paths
Each DATASET has its own TDV graph in `output/{DATASET}/tdv_graph.json` and `output/{DATASET}/data-notes.md`, not at the top-level `output/` path. Always check for dataset-specific subdirectories first.

### SQL quoting with apostrophes in store names
DuckDB SQL strings with apostrophes (e.g., "Porto's Bakery") break when interpolated via Python f-strings. Always use pandas filtering or parameterized queries when store/product names contain single quotes.

### discover_baseline returns large payloads — use `baseline_path` field
The `discover_baseline` result includes `baseline_path` pointing to the on-disk artifacts directory. Use this path for `detect_deviations`. The result JSON itself is too large to pass inline; parse it from the saved tool-result file using `json.load`.

### detect_deviations result structure
Top-level keys: `analysis_window`, `deviations`, `summary`. Each deviation has: `column`, `type`, `severity`, `timestamp_range`, `details` (expected_value, observed_value, deviation_magnitude, z_score, confidence), `persistence`, `narrative`. Summary has `by_severity`, `most_affected_columns`, `narrative`.

### matplotlib suptitle pad parameter
`fig.suptitle(..., pad=N)` is not a valid kwarg in this version of matplotlib. Use `fig.suptitle(...)` without `pad=` and adjust spacing with `plt.subplots_adjust()` or `plt.tight_layout()` instead.

### correlate_signals output too large
`correlate_signals` returns very large payloads (200K+ chars). Use `query_insights` directly after ingestion to get ranked actionable insights — it returns compact JSON that fits in context.
