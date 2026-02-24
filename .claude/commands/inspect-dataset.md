# Prepare Dataset

Interactive data preparation workflow. Loads raw data via layer0 (`data-loader`), explores segments, chooses aggregation, and outputs a time series CSV ready for layer1 signal analysis.

## Arguments

`$ARGUMENTS` — optional file path or filename (e.g. `data/heineken.csv` or `heineken.csv`)

## Workflow

Follow each step in order. Use `AskUserQuestion` for every user choice.

---

### Step 1 — Pick dataset

- If `$ARGUMENTS` is provided and looks like a file path, use it directly
- If `$ARGUMENTS` is just a filename (no directory), prepend `data/`
- If `$ARGUMENTS` is empty:
  - Glob for `data/**/*.{csv,parquet,pq,json}` in the project root
  - Present the list to the user with `AskUserQuestion` and let them choose
- Verify the file exists before proceeding

---

### Step 2 — Load dataset

Call `mcp__data-loader__load_dataset` with:
- `data_path`: absolute path to the chosen file

Store the returned JSON — you will need `dataset_name`, `columns`, `timestamp_candidates`, `suggested_segment_columns`, `numeric_columns`, and `sample_values` in later steps.

---

### Step 3 — Present schema

Display a clear summary:

**Dataset**: `{dataset_name}` — `{row_count}` rows

**Columns**:
| Column | Type | Sample Values |
|--------|------|---------------|
| ...    | ...  | ...           |

**Timestamp candidates**: list them
**Suggested segment columns**: list with unique value counts
**Numeric columns**: list them

---

### Step 4 — Choose segment column

Using the `suggested_segment_columns` from step 2:

- If there are segment candidates, ask the user which column to segment by (include a "Skip — use whole dataset" option)
- If there are no segment candidates, tell the user and skip to step 7

---

### Step 5 — Explore segment values

If the user chose a segment column:

Call `mcp__data-loader__list_segments` with:
- `dataset_name`: from step 2
- `column`: the chosen segment column

Display the results as a table:
| Value | Count |
|-------|-------|
| ...   | ...   |

---

### Step 6 — Choose segment value

Ask the user which segment value to filter on. Options should include:
- Each individual value from the list
- "All — no filter" to use the whole dataset

If there are more than 4 values, list the top values in the question description and let the user type a custom value via "Other".

---

### Step 7 — Choose timestamp column, frequency, and metrics

Ask the user three things (can be combined into one or two `AskUserQuestion` calls):

**Timestamp column**: From `timestamp_candidates`. If there's exactly one candidate, confirm it. If multiple, ask user to pick.

**Aggregation frequency**: One of:
- `hourly`
- `daily`
- `weekly`
- `monthly`

**Metrics**: Which aggregations to compute. Suggest defaults based on numeric columns. Common patterns:
- `[{"col": "*", "agg": "count"}]` — transaction count per period
- `[{"col": "amount", "agg": "sum"}, {"col": "amount", "agg": "avg"}]` — sum + average of a numeric column
- Let user pick from: `count(*)`, `sum(col)`, `avg(col)`, `min(col)`, `max(col)` for each numeric column

Present sensible defaults and let the user confirm or adjust.

---

### Step 8 — Create segment

Call `mcp__data-loader__create_segment` with:
- `dataset_name`: from step 2
- `timestamp_col`: chosen timestamp column
- `freq`: chosen frequency
- `metrics`: chosen metrics list (JSON array of `{"col": "...", "agg": "..."}` objects)
- `segment_col`: chosen segment column (or omit if skipped)
- `segment_value`: chosen value (or omit if "all"/skipped)

---

### Step 9 — Present results

From the `create_segment` response, display:

**Output**: `{output_path}`
**Rows**: `{rows}` | **Period**: `{period_range.start}` → `{period_range.end}`

**Stats**:
| Metric | Min | Max | Mean | Sum | Zeros |
|--------|-----|-----|------|-----|-------|
| ...    | ... | ... | ...  | ... | ...   |

**Preview** (first 5 rows as a table)

---

### Step 10 — Suggest next step

From `suggested_layer1_call` in the response, show the user the exact call:

```
Ready for signal analysis. Suggested next step:

  discover_baseline(
    data_path = "{output_path}",
    timestamp_col = "period",
    value_cols = [...],
    freq = "{freq}"
  )
```

---

## Error handling

- If `mcp__data-loader__load_dataset` fails, show the error and stop
- If `mcp__data-loader__list_segments` fails, show the error and skip to step 7
- If `mcp__data-loader__create_segment` fails, show the error and let the user adjust parameters
