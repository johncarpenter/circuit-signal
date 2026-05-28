# Signal Discovery Agent Memory

## Tool Patterns

### discover_baseline output format
- Returns a dict with keys: `dataset_summary`, `baselines`, `baseline_path`, `report_path`
- `baselines` is a **list** (not a dict) of baseline objects, each with `column`, `variance_explained`, `trend`, `seasonality`, `narrative`
- Output is often too large for direct return — saved to file at `.claude/projects/.../tool-results/`
- To read: `json.load(f)['result']` then `json.loads(result_str)` gives the final dict

### ingest_signals data format
- Requires the native Layer 1 MCP output format (dict with `deviations` key and list of deviation objects)
- The `data_path` parameter works when the file contains the exact Layer 1 format
- Loading via `data_path` to a manually-constructed JSON works if the structure matches the Layer 1 schema

### TDV graph with empty profiles
- The graph may load with `nodes: 0` from `graph_summary` even when profiles exist
- Fall back to reading `output/{dataset}/tdv_graph.json` directly with Python to inspect `profiles` key
- Profiles contain `source_path`, `row_count` but may lack column details if profiler didn't complete fully

## Data Conventions

### Beer POS data
- `amount` column is in **cents** — divide by 100 for USD
- `created` timestamps include " UTC" suffix — replace with "+00:00" for `datetime.fromisoformat()`
- Product names are messy bartender entries — need regex + keyword matching to classify
- store_id values are UUIDs — no geographic metadata embedded

### Aggregation for time series analysis
- Hourly POS data → aggregate to **daily totals** before baseline/deviation analysis
- This produces 1,000-2,000 daily rows across 6 years — good for STL decomposition
- Keep product breakdowns as separate columns alongside `total_amount_usd`

## matplotlib
- Must install via `uv pip install matplotlib numpy` in data_prep environment
- Use `matplotlib.use('Agg')` before importing pyplot (no display server)
- Save to `{run_dir}/charts/` with `dpi=150, bbox_inches='tight'`

## Pipeline Notes

### When graph has no joins
- If `graph_summary` returns empty or graph profiles are thin, skip `build_plan`/`execute_plan`
- Build the combined dataset manually in Python and write to `{run_dir}/combined_*.csv`
- Then load that combined CSV with `load_dataset`

### Segment files should be daily aggregated
- Don't pass raw hourly transaction CSVs to `discover_baseline` — aggregate to daily first
- Include both `total_amount_usd` and per-subcategory columns (e.g. `JW_Black`, `Bud_Light`)

### Football/event calendar correlation
- When deviations cluster around Saturdays in Sep-Nov, cross-reference with game schedules
- `playoffstatus.com/secfootball` has historical SEC game results with scores and dates
- Most useful: check if spike date is a Saturday + whether a Tennessee/Georgia home game occurred
