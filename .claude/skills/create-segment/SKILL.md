# Create Segment

Create an aggregated time series segment from a loaded dataset via layer0 (`data-loader`). Outputs a CSV to `data/segments/` ready for layer1 signal analysis.

## Arguments

`$ARGUMENTS` — dataset name and optional filters in the form: `<dataset> [segment_col=value] [freq] [metrics]`

Examples:
- `heineken` — interactive, will prompt for all options
- `heineken store_id=41fdbe8c daily` — filter by store, daily frequency
- `heineken description=Heineken hourly count,sum(amount)` — filter + freq + metrics

## Workflow

Follow each step in order. Use `AskUserQuestion` for every user choice that isn't already provided in `$ARGUMENTS`.

---

### Step 1 — Parse arguments

Parse `$ARGUMENTS` to extract any pre-specified values:
- **dataset**: first token (required — if empty, glob for `data/**/*.{csv,parquet,pq,json}` and ask user to pick)
- **segment filter**: token matching `column=value` pattern (optional)
- **frequency**: token matching `hourly|daily|weekly|monthly` (optional)
- **metrics**: comma-separated token like `count,sum(amount),avg(amount)` (optional)

Anything not provided in arguments will be asked interactively.

---

### Step 2 — Load dataset

If the dataset is not already loaded, call `mcp__data-loader__load_dataset` with:
- `data_path`: absolute path — if dataset looks like a filename, prepend `data/` and append `.csv` if no extension

Store the returned JSON — you will need `dataset_name`, `columns`, `timestamp_candidates`, `suggested_segment_columns`, and `numeric_columns`.

If the dataset is already loaded (from a previous step in the conversation), reuse the existing metadata.

---

### Step 3 — Resolve segment filter

If a segment filter (`column=value`) was provided in arguments, use it directly.

If not provided:
- If there are `suggested_segment_columns`, ask the user which column to segment by (include "Skip — use whole dataset")
- If user picks a segment column, call `mcp__data-loader__list_segments` to show available values
- Ask which value to filter on (include "All — no filter")
- If no segment candidates exist, skip filtering

---

### Step 4 — Resolve timestamp column

From `timestamp_candidates`:
- If exactly one candidate, use it automatically
- If multiple, ask the user to pick

---

### Step 5 — Resolve frequency

If frequency was provided in arguments, use it directly.

If not, ask the user:
- `hourly`
- `daily` (recommended default)
- `weekly`
- `monthly`

---

### Step 6 — Resolve metrics

If metrics were provided in arguments, parse them:
- `count` → `{"col": "*", "agg": "count"}`
- `sum(col)` → `{"col": "col", "agg": "sum"}`
- `avg(col)` → `{"col": "col", "agg": "avg"}`
- `min(col)` → `{"col": "col", "agg": "min"}`
- `max(col)` → `{"col": "col", "agg": "max"}`

If not provided, suggest defaults based on numeric columns:
- Always include `count(*)`
- For each numeric column, suggest `sum(col)`
- Let the user confirm or adjust

---

### Step 7 — Build output path

Construct the output filename under `data/segments/`:

Pattern: `{dataset}_{segment_col}_{segment_value}_{freq}.csv`

- If no segment filter: `{dataset}_{freq}.csv`
- Sanitize values (lowercase, replace spaces/special chars with underscores)

Example: `data/segments/heineken_store_id_41fdbe8c_daily.csv`

Use the absolute path: `{project_root}/data/segments/{filename}`

---

### Step 8 — Create segment

Call `mcp__data-loader__create_segment` with:
- `dataset_name`: from step 2
- `timestamp_col`: from step 4
- `freq`: from step 5
- `metrics`: from step 6 (JSON array of `{"col": "...", "agg": "..."}` objects)
- `segment_col`: from step 3 (omit if no filter)
- `segment_value`: from step 3 (omit if no filter)
- `output_path`: from step 7

---

### Step 9 — Present results

From the `create_segment` response, display:

**Output**: `data/segments/{filename}`
**Rows**: `{rows}` | **Period**: `{period_range.start}` → `{period_range.end}`

**Stats**:
| Metric | Min | Max | Mean | Sum | Zeros |
|--------|-----|-----|------|-----|-------|
| ...    | ... | ... | ...  | ... | ...   |

**Preview** (first 5 rows as a table)

---

### Step 10 — Suggest next step

Show the user the exact call for signal analysis:

```
Ready for signal analysis. Suggested next step:

  discover_baseline(
    data_path = "data/segments/{filename}",
    timestamp_col = "period",
    value_cols = [...],
    freq = "{freq}"
  )
```

---

## Error handling

- If `mcp__data-loader__load_dataset` fails, show the error and stop
- If `mcp__data-loader__list_segments` fails, show the error and skip to step 8 without segment filter
- If `mcp__data-loader__create_segment` fails, show the error and let the user adjust parameters
