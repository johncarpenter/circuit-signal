---
name: research-experiments
description: >
  Generate focused research experiments from a business goal and available data.
  Produces 3-5 testable experiments with hypotheses, assumptions, projected outcomes,
  and ready-to-run signal-discovery prompts. Output saved to workspace/experiments/.
  Triggers: "research experiments", "generate experiments", "design experiments",
  "what should we analyze", "research plan", "experiment design".
---

# Research Experiment Generator

Turn a vague business question into 3-5 focused, testable research experiments — each with a hypothesis, assumptions, projected outcomes, and an exact signal-discovery prompt to execute it.

## Arguments

`$ARGUMENTS` — `<goal> [data:<path_or_description>] [industry:<industry>]`

Examples:
- `"How do we attract new luxury spirit buyers" data:workspace/data/spirits industry:hospitality`
- `"Is non-alc cannibalizing beer sales" data:workspace/data/nonalc`
- `"Which venues should we target for premium upgrades"`

## Workflow

Follow each step in order.

---

### Step 1 — Parse arguments

Extract from `$ARGUMENTS`:
- **goal**: the business question (required — if missing, use `AskUserQuestion` to ask)
- **data**: token matching `data:<path_or_description>` — path to a dataset directory or description of available data (optional)
- **industry**: token matching `industry:<value>` — industry context hint (optional, inferred from data if possible)

The goal is everything that isn't a `data:` or `industry:` token. Strip surrounding quotes.

---

### Step 2 — Gather data context

**If a data path was provided:**
1. Check if `dataset.yaml` exists in that directory — if so, read it for metadata (columns, description, granularity, time range)
2. Glob for data files (`*.csv`, `*.parquet`, `*.pq`, `*.json`) in that directory and note filenames
3. Pick one representative file and call `mcp__signal-discovery__inspect_dataset` to understand columns, data types, row count, and time range
4. Summarize: what entities exist, what metrics are available, what time granularity, what time span

**If no data path was provided:**
- Use `AskUserQuestion` to ask the user to describe their available data: what columns, what granularity (daily/weekly/monthly), what time range, what entities (products, stores, regions, etc.)

Store the data context summary for use in experiment design.

---

### Step 3 — Background research

Use `WebSearch` to find 2-3 relevant industry reports, studies, or articles related to the goal. Run 1-2 targeted searches combining the goal keywords with the industry context.

Example searches:
- `"luxury spirits buyer behavior trends 2025 2026"`
- `"non-alcoholic beer cannibalization craft beer research"`
- `"premium venue upgrade hospitality ROI"`

From the results, extract and summarize:
- Key statistics or benchmarks (e.g., "non-alc spirits grew 30% in 2025")
- Known patterns or behaviors (e.g., "premium buyers index 2x on weekday dining")
- Industry frameworks or segmentation approaches

Keep the summary to 3-5 bullet points with source links. This grounds the experiments in evidence rather than speculation.

---

### Step 4 — Design experiments

Generate 3-5 experiments. Each experiment must include ALL of the following fields:

**Title** — Short experiment name (5-10 words)

**Hypothesis** — A specific, falsifiable claim. Must be testable with the available data.
- Good: "Premium spirit sales increase >15% at venues that added cocktail menus in the last 6 months"
- Bad: "Premium spirits are popular" (not falsifiable)

**Assumptions** — 2-3 assumptions that must hold for the hypothesis to be valid. These are the conditions you're taking for granted.
- Example: "The POS data captures all spirit sales, not just on-premise"
- Example: "Menu changes are reflected in the venue metadata"

**Projected Outcomes** — Two scenarios:
- **If true**: What specific pattern will the signal-discovery pipeline reveal? Be concrete about expected magnitudes, timing, and shape.
- **If false**: What will the data show instead? This is equally important — a null result is still informative.

**Data Required** — Which specific datasets, columns, segments, and time ranges are needed from the available data. Reference actual column names from Step 2 where possible.

**Analysis Approach** — Which signal-discovery capabilities to use:
- `baseline` — for establishing normal patterns and seasonality
- `deviation` — for detecting anomalies and trend shifts
- `correlation` — for cross-segment or cross-source signal alignment
- Specify the combination and order.

**Signal-Discovery Prompt** — The exact, complete prompt to pass to the signal-discovery agent. This must be self-contained: include the data path, what to analyze, what to look for, and what output to produce. Write it as if the person running it has no context beyond the prompt itself.

**Decision Impact** — What specific business decision this experiment informs. Be concrete:
- Good: "Determines whether to expand cocktail menu programs to 50 additional venues in Q3"
- Bad: "Helps understand the market" (too vague)

### Experiment diversity guidelines

Ensure the 3-5 experiments cover different angles:
- At least one should use **baseline + deviation** (trend/anomaly focused)
- At least one should use **correlation** (cross-segment or cross-source)
- At least one should challenge conventional wisdom or test a contrarian hypothesis
- Experiments should be independent — each tests a different aspect of the goal

---

### Step 5 — Prioritize

Rank experiments by three criteria, scoring each High/Medium/Low:

| Criterion | High | Medium | Low |
|-----------|------|--------|-----|
| **Data Readiness** | All required data available now | Most data available, minor gaps | Need new data sources |
| **Decision Impact** | Directly informs a high-stakes decision | Informs a meaningful decision | Nice-to-know insight |
| **Confidence** | Strong theoretical basis + supporting evidence | Reasonable basis, some evidence | Speculative, exploratory |

Overall priority = weighted combination: Data Readiness (40%) + Decision Impact (40%) + Confidence (20%)

Assign a priority rank (1 = run first) to each experiment.

---

### Step 6 — Write output document

Create the output directory if it doesn't exist:
```
workspace/experiments/
```

Generate the filename: `{YYYY-MM-DD}-{goal-slug}.md`
- Date: today's date
- Slug: lowercase goal, spaces to hyphens, remove special chars, truncate to 50 chars

Save the document with this structure:

```markdown
# Research Experiments: {Goal}

> **Generated**: {YYYY-MM-DD}
> **Data Source**: {dataset path or description}
> **Industry**: {industry}

## Background Research

{Summary of web research findings — 3-5 bullet points with key statistics and source links}

## Experiments

### Experiment 1: {Title}

**Hypothesis**: {Specific, falsifiable claim}

**Assumptions**:
- {assumption 1}
- {assumption 2}
- {assumption 3}

**If true, we expect**: {Concrete projected outcome with expected magnitudes}

**If false, we expect**: {What the data shows instead}

**Data required**: {Datasets, columns, segments, time ranges}

**Analysis approach**: {baseline / deviation / correlation — with specifics}

**Decision impact**: {What business decision changes based on the result}

<details>
<summary>Signal-Discovery Prompt</summary>

{The exact, self-contained prompt to pass to the signal-discovery agent}

</details>

---

### Experiment 2: {Title}
...

(repeat for all experiments)

---

## Execution Priority

| # | Experiment | Data Ready | Impact | Confidence | Priority |
|---|-----------|-----------|--------|------------|----------|
| 1 | {title}   | High      | High   | Medium     | 1        |
| 2 | {title}   | High      | Medium | High       | 2        |
| ... | ...     | ...       | ...    | ...        | ...      |

## Next Steps

1. Run **Experiment {top_priority}** first — it has the best combination of data readiness and impact
2. Use the signal-discovery prompt from the experiment details above
3. After results are in, revisit assumptions and refine follow-up experiments
```

---

### Step 7 — Present results

Display:

1. The output file path
2. A summary table of all experiments (title + hypothesis, one line each)
3. The priority ranking table
4. Suggest running the top-priority experiment, showing the exact invocation:

```
Experiments saved to: workspace/experiments/{filename}

To run the top-priority experiment:
  /signal-discovery {paste the signal-discovery prompt from experiment N}
```

---

## Error Handling

| Error | Response |
|-------|----------|
| No goal provided | Ask for it with `AskUserQuestion` |
| Data path doesn't exist | Warn the user, continue without data context (ask them to describe data manually) |
| No data files found at path | Warn, continue without data context |
| Web search returns no results | Skip background research section, note it was unavailable |
| `inspect_dataset` fails | Continue with whatever metadata is available from filenames and dataset.yaml |

## Tips

- The signal-discovery prompts should reference actual file paths from the data context
- Each experiment should be independently runnable — no dependencies between experiments
- Prefer experiments that can be run with existing data over those requiring new data
- The contrarian experiment often produces the most interesting insights
